"""DCSS Game API wrapper for LLM-controlled gameplay."""
import json
import logging
from dcss_ai.overlay import send_game_started
import os
import re
import time
from typing import Optional, List, Dict, Tuple, Any

from dcss_ai.webtiles import WebTilesConnection

from .state import GameState
from .actions import GameActions
from .ui import UIHandler
from .overlay import OverlayStats
from .utils import _strip_formatting, _strip_html

logger = logging.getLogger(__name__)

OVERLAY_STATS_PATH = os.environ.get("DCSS_OVERLAY_STATS", os.path.expanduser("~/code/dcss-stream/stats.json"))


class DCSSGame(GameState, GameActions, UIHandler, OverlayStats):
    """High-level API for controlling DCSS via webtiles WebSocket.

    All state is updated incrementally from WebSocket messages.
    Properties are free (no turn cost). Actions consume turns.
    """

    def __init__(self, stats_path: str = OVERLAY_STATS_PATH):
        self._ws: Optional[WebTilesConnection] = None
        self._connected = False
        self._in_game = False
        self._game_ids: List[str] = []
        self._stats_path = stats_path

        # Persistent stats (loaded from overlay file)
        self._attempt = 0
        self._wins = 0
        self._deaths = 0
        self._load_persistent_stats()

        # Player stats
        self._hp = 0
        self._max_hp = 0
        self._mp = 0
        self._max_mp = 0
        self._ac = 0
        self._ev = 0
        self._sh = 0
        self._str = 0
        self._int = 0
        self._dex = 0
        self._xl = 1
        self._place = ""
        self._depth = 0
        self._god = ""
        self._gold = 0
        self._position = (0, 0)
        self._turn = 0
        self._is_dead = False
        self._actions_since_narrate = 0
        self._session_ended = False
        self._species = ""
        self._title = ""
        self._consecutive_timeouts = 0
        self._consecutive_failed_moves = 0

        # Inventory
        self._inventory: Dict[int, Dict[str, Any]] = {}

        # Message history and map state
        self._messages: List[str] = []
        self._map_cells: Dict[Tuple[int, int], str] = {}
        self._tile_fg: Dict[Tuple[int, int], int] = {}
        self._cell_features: Dict[Tuple[int, int], int] = {}
        self._cell_overlays: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._monsters: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._monster_names: Dict[int, str] = {}

        # Menu state
        self._current_menu: Optional[Dict[str, Any]] = None
        self._menu_items: List[Dict[str, Any]] = []

        # UI popup state
        self._current_popup: Optional[Dict[str, Any]] = None

        # Pending text prompt
        self._pending_prompt: Optional[str] = None

        # New: player status effects, piety, contamination, etc.
        self._status_effects: List[Dict[str, str]] = []
        self._poison_survival: int = 0
        self._real_hp_max: int = 0
        self._piety_rank: int = 0
        self._penance: bool = False
        self._contam: int = 0
        self._noise: int = -1
        self._adjusted_noise: int = -1
        self._form: int = 0
        self._quiver_desc: str = ""
        self._elapsed_time: int = 0
        self._xl_progress: int = 0
        self._weapon_index: int = -1
        self._offhand_index: int = -1
        self._ac_mod: int = 0
        self._ev_mod: int = 0
        self._sh_mod: int = 0
        self._doom: int = 0
        self._lives: int = 0
        self._deaths: int = 0

        # Notepad
        self._notepad: Dict[str, List[str]] = {}

    # --- Connection/lifecycle ---

    def connect(self, url: str, username: str, password: str) -> bool:
        """Connect to DCSS webtiles server and login."""
        self._username = username
        try:
            self._ws = WebTilesConnection(url)
            self._ws.recv_messages(timeout=0.5)

            self._ws._send({"msg": "register", "username": username, "password": password, "email": ""})
            reg_msgs = self._ws.recv_messages(timeout=2.0)

            registered = any(m.get("msg") == "login_success" for m in reg_msgs)

            if registered:
                self._ws._send({"msg": "go_lobby"})
                found, lobby_msgs = self._ws.wait_for("go_lobby", timeout=10.0)
                all_msgs = reg_msgs + lobby_msgs
                for msg in all_msgs:
                    if msg.get("msg") == "set_game_links":
                        self._game_ids = re.findall(r'#play-([^"]+)"', msg.get("content", ""))
                        break
            else:
                self._ws.disconnect()
                time.sleep(0.2)
                self._ws = WebTilesConnection(url)
                self._ws.recv_messages(timeout=0.5)
                self._game_ids = self._ws.login(username, password)

            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"Connection failed: {e}")

    def start_game(self, species_key: str, background_key: str, weapon_key: str = "", game_id: str = "") -> str:
        """Start a new game, abandoning any stale saves first. Returns initial state."""
        if self._session_ended:
            return "Session has ended (death/win recorded). Say GAME_OVER to finish."
        if not self._connected or not self._ws:
            raise RuntimeError("Not connected to server")

        if self._in_game:
            self.quit_game()

        gid = game_id or self._game_ids[0]
        startup_msgs = self._ws.start_game(gid, species_key, background_key, weapon_key)

        had_newgame = any(m.get("msg") == "ui-state" and m.get("type") == "newgame-choice"
                         for m in startup_msgs)
        if not had_newgame:
            logger.info("Stale save detected, abandoning...")
            self._in_game = True
            self.quit_game()
            self._attempt += 1
            self.update_overlay("Clearing stale save, restarting...")
            time.sleep(0.5)
            self._ws.recv_messages(timeout=1.0)
            startup_msgs = self._ws.start_game(gid, species_key, background_key, weapon_key)

        for msg in startup_msgs:
            self._process_msg(msg)

        self._in_game = True
        self._is_dead = False
        self._messages.clear()

        for _ in range(5):
            msgs = self._ws.recv_messages(timeout=1.0)
            for msg in msgs:
                self._process_msg(msg)
            if not msgs:
                break

        send_game_started()
        return self.get_state_text()

    def quit_game(self):
        """Quit current game."""
        if self._in_game and self._ws:
            self._ws.quit_game()
            self._in_game = False

    def disconnect(self):
        """Disconnect from server."""
        if self._ws:
            try:
                if self._in_game:
                    self.quit_game()
                self._ws.disconnect()
            except Exception:
                pass
        self._connected = False
        self._in_game = False

    # --- Internals ---

    def _act(self, *keys: str, timeout: float = 5.0, menu_ok: bool = False) -> List[str]:
        """Send keys, wait for input_mode, return new messages."""
        if not self._ws or not self._in_game:
            return ["Not in game"]

        NARRATE_INTERVAL = int(os.environ.get("DCSS_NARRATE_INTERVAL", "5"))
        if NARRATE_INTERVAL > 0 and not menu_ok and self._actions_since_narrate >= NARRATE_INTERVAL:
            return [f"[ERROR: You must call narrate() before continuing. You've taken {self._actions_since_narrate} actions without narrating for stream viewers.]"]
        if not menu_ok:
            self._actions_since_narrate += 1

        if not menu_ok and self._pending_prompt:
            if self._pending_prompt == "stat_increase":
                return ["[ERROR: Stat increase prompt is waiting! Call choose_stat('s'), choose_stat('i'), or choose_stat('d') to pick Strength, Intelligence, or Dexterity.]"]
            return [f"[ERROR: A prompt is pending: {self._pending_prompt}]"]

        if not menu_ok and self._current_menu:
            title = self._current_menu.get("title", "a menu")
            return [f"[ERROR: {title} is still open. Use read_ui() to see it, select_menu_item() to interact, or dismiss() to close it first.]"]
        if not menu_ok and self._current_popup:
            return ["[ERROR: A popup is still open. Use read_ui() to see it or dismiss() to close it first.]"]

        msg_start = len(self._messages)

        leftover = self._ws.recv_messages(timeout=0.05)
        for msg in leftover:
            self._process_msg(msg)

        for key in keys:
            self._ws.send_key(key)

        deadline = time.time() + timeout
        got_input = False
        got_player = False

        while time.time() < deadline and not self._is_dead:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            msgs = self._ws.recv_messages(timeout=min(0.5, remaining))

            if not msgs and remaining < 1.0:
                logger.warning(f"_act timeout approaching, keys={keys}, got_input={got_input}, got_player={got_player}")

            for msg in msgs:
                self._process_msg(msg)
                mt = msg.get("msg")
                if mt == "input_mode":
                    mode = msg.get("mode")
                    logger.debug(f"input_mode={mode} (keys={keys})")
                    if mode == 1:
                        got_input = True
                    elif mode == 5:
                        self._ws.send_key(" ")
                    elif mode == 7:
                        recent = self._messages[-5:] if self._messages else []
                        stat_prompt = any("(S)trength" in m for m in recent)
                        if stat_prompt:
                            self._pending_prompt = "stat_increase"
                            logger.info(f"Stat increase prompt detected (keys={keys})")
                            got_input = True
                        else:
                            logger.info(f"Text input prompt during _act, escaping (keys={keys})")
                            self._ws.send_key("key_esc")
                    elif mode == 0:
                        pass
                    elif mode == 4:
                        # Targeting mode — waiting for direction input
                        # Don't escape, let the caller handle it
                        logger.debug(f"Targeting mode (mode=4) during _act (keys={keys})")
                        got_input = True
                    else:
                        logger.info(f"Unknown input_mode={mode}, escaping (keys={keys})")
                        self._ws.send_key("key_esc")
                elif mt == "player":
                    got_player = True
                elif mt == "close":
                    logger.info(f"Game closed (death). keys={keys}")
                    self._is_dead = True
                    self._in_game = False
                    self._deaths += 1
                elif mt in ("ui-push", "ui-state"):
                    ui_type = msg.get("type", "unknown")
                    logger.info(f"UI popup ({mt}) type={ui_type} during _act (keys={keys})")
                    self._handle_ui_msg(msg)
                    got_input = True
                elif mt == "ui-pop":
                    self._current_popup = None
                elif mt in ("menu", "update_menu", "update_menu_items"):
                    logger.info(f"Menu message ({mt}) tag={msg.get('tag', '?')} during _act (keys={keys})")
                    self._handle_menu_msg(msg)
                    got_input = True
                elif mt in ("close_menu", "close_all_menus"):
                    self._current_menu = None
                    self._menu_items = []

            if got_input and got_player:
                break
            if got_input:
                extra = self._ws.recv_messages(timeout=0.1)
                for msg in extra:
                    self._process_msg(msg)
                break

        if not got_input and not self._is_dead:
            self._consecutive_timeouts += 1
            logger.warning(f"_act finished without input_mode=1! keys={keys}, timeout={timeout}, consecutive={self._consecutive_timeouts}")
            if self._consecutive_timeouts >= 3:
                logger.warning(f"3+ consecutive timeouts — sending recovery escapes + Ctrl+R to resync")
                for _ in range(3):
                    self._ws.send_key("key_esc")
                    time.sleep(0.1)
                # Ctrl+R forces DCSS to redraw/resend full game state
                self._ws.send_key("key_ctrl_r")
                time.sleep(0.3)
                # Drain all responses and rebuild state
                for _ in range(5):
                    recovery_msgs = self._ws.recv_messages(timeout=0.5)
                    if not recovery_msgs:
                        break
                    for msg in recovery_msgs:
                        self._process_msg(msg)
                        mt = msg.get("msg")
                        if mt == "ui-pop":
                            self._current_popup = None
                            logger.info("Recovery: dismissed phantom popup")
                        elif mt in ("close_menu", "close_all_menus"):
                            self._current_menu = None
                            self._menu_items = []
                            logger.info("Recovery: closed phantom menu")
                        elif mt == "input_mode" and msg.get("mode") == 1:
                            logger.info("Recovery: got input_mode=1, state resynced")
                self._consecutive_timeouts = 0
        else:
            self._consecutive_timeouts = 0

        new_msgs = self._messages[msg_start:]

        if any("Unknown command" in m for m in new_msgs):
            new_msgs.append("[HINT: 'Unknown command' means a key you sent was invalid in this context. Check if you're sending the right arguments.]")

        return new_msgs

    def _process_msg(self, msg: dict):
        """Route a message to the appropriate handler."""
        mt = msg.get("msg")
        if mt == "player":
            self._update_player(msg)
        elif mt == "map":
            self._update_map(msg)
        elif mt == "msgs":
            self._update_messages(msg)

    def _update_player(self, msg: Dict[str, Any]):
        field_map = {
            "hp": "_hp", "hp_max": "_max_hp",
            "mp": "_mp", "mp_max": "_max_mp",
            "ac": "_ac", "ev": "_ev", "sh": "_sh",
            "str": "_str", "int": "_int", "dex": "_dex",
            "xl": "_xl", "place": "_place", "depth": "_depth",
            "god": "_god", "gold": "_gold", "turn": "_turn",
            "species": "_species", "title": "_title",
            "poison_survival": "_poison_survival",
            "real_hp_max": "_real_hp_max",
            "piety_rank": "_piety_rank",
            "penance": "_penance",
            "contam": "_contam",
            "adjusted_noise": "_adjusted_noise",
            "form": "_form",
            "quiver_desc": "_quiver_desc",
            "time": "_elapsed_time",
            "progress": "_xl_progress",
            "weapon_index": "_weapon_index",
            "offhand_index": "_offhand_index",
            "ac_mod": "_ac_mod",
            "ev_mod": "_ev_mod",
            "sh_mod": "_sh_mod",
            "doom": "_doom",
            "lives": "_lives",
            "deaths": "_deaths",
        }
        for json_key, attr in field_map.items():
            if json_key in msg:
                setattr(self, attr, msg[json_key])
        if "pos" in msg:
            pos = msg["pos"]
            if isinstance(pos, dict):
                self._position = (pos.get("x", 0), pos.get("y", 0))
        if "inv" in msg:
            for slot_str, item_data in msg["inv"].items():
                slot = int(slot_str)
                if item_data:
                    self._inventory[slot] = item_data
                else:
                    self._inventory.pop(slot, None)
        if "status" in msg:
            self._status_effects = []
            for s in msg["status"]:
                effect = {}
                if "light" in s:
                    effect["light"] = s["light"]
                if "text" in s:
                    effect["text"] = s["text"]
                if "desc" in s:
                    effect["desc"] = s["desc"]
                if effect:
                    self._status_effects.append(effect)

    def _update_map(self, msg: Dict[str, Any]):
        cells = msg.get("cells", [])
        if not cells:
            return
        cur_x, cur_y = None, None
        for cell in cells:
            if "x" in cell: cur_x = cell["x"]
            if "y" in cell: cur_y = cell["y"]
            if cur_x is not None and cur_y is not None:
                if "g" in cell:
                    self._map_cells[(cur_x, cur_y)] = cell["g"]
                if "f" in cell:
                    self._cell_features[(cur_x, cur_y)] = cell["f"]
                # Store cell overlays (silenced, sanctuary, halo, etc.)
                overlay_keys = ("silenced", "sanctuary", "halo", "liquefied",
                                "orb_glow", "quad_glow", "disjunct", "awakened_forest",
                                "blasphemy", "highlighted_summoner")
                overlays = {}
                for ok in overlay_keys:
                    if ok in cell:
                        overlays[ok] = cell[ok]
                if overlays:
                    self._cell_overlays[(cur_x, cur_y)] = overlays
                elif (cur_x, cur_y) in self._cell_overlays:
                    # Clear overlays if cell updated without them
                    del self._cell_overlays[(cur_x, cur_y)]
                # Store fg tile flags for behavior/status decoding
                if "fg" in cell:
                    fg = cell["fg"]
                    if isinstance(fg, list):
                        # [lo, hi] split for 64-bit values
                        self._tile_fg[(cur_x, cur_y)] = (fg[1] << 32) | (fg[0] & 0xFFFFFFFF)
                    else:
                        self._tile_fg[(cur_x, cur_y)] = fg
                if "mon" in cell:
                    if cell["mon"]:
                        mon_data = cell["mon"]
                        mon_id = mon_data.get("id")
                        if "name" in mon_data and mon_id is not None:
                            self._monster_names[mon_id] = mon_data["name"]
                        existing = self._monsters.get((cur_x, cur_y), {})
                        existing.update(mon_data)
                        if "name" not in existing and mon_id in self._monster_names:
                            existing["name"] = self._monster_names[mon_id]
                        self._monsters[(cur_x, cur_y)] = existing
                    elif (cur_x, cur_y) in self._monsters:
                        del self._monsters[(cur_x, cur_y)]
                cur_x += 1

    def _update_messages(self, msg: Dict[str, Any]):
        for m in msg.get("messages", []):
            text = m.get("text", "")
            if text:
                clean = re.sub(r'<[^>]+>', '', text).strip()
                if clean:
                    self._messages.append(clean)
        if len(self._messages) > 200:
            self._messages = self._messages[-100:]

    @staticmethod
    def _strip_formatting(text: str) -> str:
        """Strip DCSS formatting codes from text (e.g. color tags)."""
        return _strip_formatting(text)

    @staticmethod
    def _strip_html(text: str) -> str:
        return _strip_html(text)
