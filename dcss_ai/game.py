"""DCSS Game API wrapper for LLM-controlled gameplay."""
import json
import logging
import os
import re
import time
from typing import Optional, List, Dict, Tuple, Any
from dcss_ai.webtiles import WebTilesConnection

logger = logging.getLogger(__name__)

OVERLAY_STATS_PATH = os.environ.get("DCSS_OVERLAY_STATS", os.path.expanduser("~/code/dcss-stream/stats.json"))


class DCSSGame:
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
        self._species = ""
        self._title = ""
        
        # Inventory
        self._inventory: Dict[int, Dict[str, Any]] = {}
        
        # Message history and map state
        self._messages: List[str] = []
        self._map_cells: Dict[Tuple[int, int], str] = {}
        self._monsters: Dict[Tuple[int, int], Dict[str, Any]] = {}
    
    # --- Connection/lifecycle ---
    
    def connect(self, url: str, username: str, password: str) -> bool:
        """Connect to DCSS webtiles server and login."""
        self._username = username
        try:
            self._ws = WebTilesConnection(url)
            self._ws.recv_messages(timeout=0.5)
            
            # Try register first (also logs in on success)
            self._ws._send({"msg": "register", "username": username, "password": password, "email": ""})
            reg_msgs = self._ws.recv_messages(timeout=2.0)
            
            registered = any(m.get("msg") == "login_success" for m in reg_msgs)
            
            if registered:
                # Register succeeded and logged us in — go to lobby
                self._ws._send({"msg": "go_lobby"})
                found, lobby_msgs = self._ws.wait_for("go_lobby", timeout=10.0)
                all_msgs = reg_msgs + lobby_msgs
                # Extract game IDs
                import re
                for msg in all_msgs:
                    if msg.get("msg") == "set_game_links":
                        self._game_ids = re.findall(r'#play-([^"]+)"', msg.get("content", ""))
                        break
            else:
                # User exists — login normally
                # Need fresh connection since register may have corrupted state
                self._ws.disconnect()
                import time; time.sleep(0.2)
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
        if not self._connected or not self._ws:
            raise RuntimeError("Not connected to server")
        
        # Abandon any existing save
        if self._in_game:
            self.quit_game()
        
        gid = game_id or self._game_ids[0]
        startup_msgs = self._ws.start_game(gid, species_key, background_key, weapon_key)
        
        # Check if we resumed a save instead of creating new character
        had_newgame = any(m.get("msg") == "ui-state" and m.get("type") == "newgame-choice"
                         for m in startup_msgs)
        if not had_newgame:
            # Stale save — abandon it and retry
            logger.info("Stale save detected, abandoning...")
            self._in_game = True
            self.quit_game()
            time.sleep(0.5)
            self._ws.recv_messages(timeout=1.0)  # drain lobby messages
            startup_msgs = self._ws.start_game(gid, species_key, background_key, weapon_key)
        
        # Process all startup messages
        for msg in startup_msgs:
            self._process_msg(msg)
        
        self._in_game = True
        self._is_dead = False
        self._messages.clear()
        
        # Drain ALL late startup messages — keep reading until no more arrive
        # The server sends multiple input_mode=1 during startup (welcome, "Press ?", etc.)
        for _ in range(5):
            msgs = self._ws.recv_messages(timeout=1.0)
            for msg in msgs:
                self._process_msg(msg)
            if not msgs:
                break
        
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
    
    # --- Properties (free) ---
    
    @property
    def hp(self) -> int: return self._hp
    @property
    def max_hp(self) -> int: return self._max_hp
    @property
    def mp(self) -> int: return self._mp
    @property
    def max_mp(self) -> int: return self._max_mp
    @property
    def ac(self) -> int: return self._ac
    @property
    def ev(self) -> int: return self._ev
    @property
    def sh(self) -> int: return self._sh
    @property
    def strength(self) -> int: return self._str
    @property
    def intelligence(self) -> int: return self._int
    @property
    def dexterity(self) -> int: return self._dex
    @property
    def xl(self) -> int: return self._xl
    @property
    def place(self) -> str: return self._place
    @property
    def depth(self) -> int: return self._depth
    @property
    def god(self) -> str: return self._god
    @property
    def gold(self) -> int: return self._gold
    @property
    def position(self) -> Tuple[int, int]: return self._position
    @property
    def is_dead(self) -> bool: return self._is_dead
    @property
    def turn(self) -> int: return self._turn
    
    # --- State queries (free) ---
    
    def get_messages(self, n: int = 10) -> List[str]:
        """Get last n game messages."""
        return self._messages[-n:] if self._messages else []
    
    def get_inventory(self) -> List[Dict[str, Any]]:
        """Get inventory as list of {slot, name, quantity}."""
        items = []
        for slot, data in sorted(self._inventory.items()):
            name = data.get("name", "")
            if not name or name == "?":
                continue
            items.append({
                "slot": chr(ord('a') + slot) if slot < 26 else str(slot),
                "name": name,
                "quantity": data.get("quantity", 1),
            })
        return items
    
    def get_map(self, radius: int = 7) -> str:
        """Get ASCII map centered on player. @ is the player."""
        if not self._map_cells:
            return "No map data available"
        px, py = self._position
        lines = []
        for y in range(py - radius, py + radius + 1):
            line = ""
            for x in range(px - radius, px + radius + 1):
                if (x, y) == (px, py):
                    line += "@"
                elif (x, y) in self._map_cells:
                    line += self._map_cells[(x, y)]
                else:
                    line += " "
            lines.append(line)
        return "\n".join(lines)
    
    def get_nearby_enemies(self) -> List[Dict[str, Any]]:
        """Get visible enemies sorted by distance. Filters out plants/fungi."""
        IGNORE = {'plant', 'withered plant', 'fungus', 'toadstool', 'bush', 
                  'ballistomycete spore', 'briar patch', 'pillar of salt',
                  'block of ice', 'spectral weapon'}
        px, py = self._position
        enemies = []
        for (mx, my), mon in self._monsters.items():
            if not mon:
                continue
            name = mon.get("name", "unknown").lower()
            if name in IGNORE:
                continue
            dx, dy = mx - px, my - py
            direction = ""
            if dy < 0: direction += "n"
            elif dy > 0: direction += "s"
            if dx > 0: direction += "e"
            elif dx < 0: direction += "w"
            enemies.append({
                "name": mon.get("name", "unknown"),
                "x": dx, "y": dy,
                "direction": direction or "here",
                "distance": max(abs(dx), abs(dy)),
                "threat": mon.get("threat", 0),
            })
        enemies.sort(key=lambda e: e["distance"])
        return enemies
    
    def get_stats(self) -> str:
        char_info = f"{self._species} {self._title}".strip() if self._species else "Unknown"
        return (
            f"Character: {char_info} | "
            f"HP: {self._hp}/{self._max_hp} | MP: {self._mp}/{self._max_mp} | "
            f"AC: {self._ac} EV: {self._ev} SH: {self._sh} | "
            f"Str: {self._str} Int: {self._int} Dex: {self._dex} | "
            f"XL: {self._xl} | Gold: {self._gold} | "
            f"Place: {self._place}:{self._depth} | "
            f"God: {self._god or 'None'} | Turn: {self._turn}"
        )
    
    def get_state_text(self) -> str:
        """Full state dump for LLM consumption."""
        parts = [
            "=== DCSS State ===",
            self.get_stats(),
            "",
            "--- Messages ---",
        ]
        for msg in self.get_messages(5):
            parts.append(f"  {msg}")
        
        inv = self.get_inventory()
        if inv:
            parts.append("")
            parts.append("--- Inventory ---")
            for item in inv:
                parts.append(f"  {item['slot']}) {item['name']}")
        
        enemies = self.get_nearby_enemies()
        if enemies:
            parts.append("")
            parts.append("--- Enemies ---")
            for e in enemies:
                parts.append(f"  {e['name']} ({e['direction']}, dist {e['distance']}, threat {e['threat']})")
        
        parts.append("")
        parts.append("--- Map ---")
        parts.append(self.get_map())
        
        if self._is_dead:
            parts.append("\n*** GAME OVER — YOU ARE DEAD ***")
        
        return "\n".join(parts)
    
    # --- Actions (consume turns) ---
    
    def move(self, direction: str) -> List[str]:
        """Move in direction: n/s/e/w/ne/nw/se/sw. Moving into enemy = melee attack."""
        key_map = {
            "n": "key_dir_n", "s": "key_dir_s", "e": "key_dir_e", "w": "key_dir_w",
            "ne": "key_dir_ne", "nw": "key_dir_nw", "se": "key_dir_se", "sw": "key_dir_sw",
        }
        d = direction.lower()
        if d not in key_map:
            return [f"Invalid direction: {direction}. Use n/s/e/w/ne/nw/se/sw"]
        return self._act(key_map[d])
    
    def attack(self, direction: str) -> List[str]:
        """Melee attack by moving into enemy. Use when auto_fight is blocked."""
        return self.move(direction)
    
    def auto_explore(self) -> List[str]:
        """Auto-explore (o). Stops on enemies, items, or fully explored."""
        return self._act("o")
    
    def auto_fight(self) -> List[str]:
        """Auto-fight nearest (Tab). Blocked at low HP as Berserker."""
        return self._act("key_tab")
    
    def rest(self) -> List[str]:
        """Long rest until healed (5). Won't work with enemies nearby."""
        return self._act("5")
    
    def wait_turn(self) -> List[str]:
        """Wait one turn (.)."""
        return self._act(".")
    
    def go_upstairs(self) -> List[str]:
        return self._act("<")
    
    def go_downstairs(self) -> List[str]:
        return self._act(">")
    
    def pickup(self) -> List[str]:
        # ',' auto-grabs single item or opens selection menu for multiple
        # If menu opens, ',' again selects all, then Enter confirms
        msgs = self._act(",")
        self._act(",")  # select all in menu (no-op if no menu)
        self._act("key_enter")  # confirm (no-op if no menu)
        return msgs
    
    def use_ability(self, key: str) -> List[str]:
        """Use ability: a=Berserk, b=Trog's Hand, c=Brothers in Arms."""
        return self._act("a", key)
    
    def cast_spell(self, key: str, direction: str = "") -> List[str]:
        keys = ["z", key]
        if direction:
            keys.append(self._dir_key(direction))
        return self._act(*keys)
    
    def _dir_key(self, direction: str) -> str:
        """Convert direction string to DCSS key."""
        key_map = {"n":"key_dir_n","s":"key_dir_s","e":"key_dir_e","w":"key_dir_w",
                   "ne":"key_dir_ne","nw":"key_dir_nw","se":"key_dir_se","sw":"key_dir_sw"}
        return key_map.get(direction.lower(), direction)
    
    def quaff(self, key: str) -> List[str]:
        return self._act("q", key)
    
    def read_scroll(self, key: str) -> List[str]:
        return self._act("r", key)
    
    def wield(self, key: str) -> List[str]:
        return self._act("w", key)
    
    def wear(self, key: str) -> List[str]:
        return self._act("W", key)
    
    def drop(self, key: str) -> List[str]:
        return self._act("d", key)
    
    def pray(self) -> List[str]:
        return self._act("p")
    
    def confirm(self) -> List[str]:
        return self._act("Y")
    
    def deny(self) -> List[str]:
        return self._act("N")
    
    def escape(self) -> List[str]:
        return self._act("key_esc")
    
    def send_keys(self, keys: str) -> List[str]:
        """Raw key escape hatch."""
        return self._act(*list(keys))
    
    def zap_wand(self, slot: str, direction: str = "") -> List[str]:
        """Evoke/zap a wand from inventory by slot letter, optionally in a direction."""
        keys = ["V", slot]
        if direction:
            keys.append(self._dir_key(direction))
        return self._act(*keys)
    
    def evoke(self, slot: str) -> List[str]:
        """Evoke a miscellaneous evocable item by slot letter."""
        return self._act("v", slot)
    
    def throw_item(self, slot: str, direction: str) -> List[str]:
        """Throw/fire an item in a direction."""
        return self._act("F", slot, self._dir_key(direction))
    
    def put_on_jewelry(self, slot: str) -> List[str]:
        """Put on a ring or amulet by slot letter."""
        return self._act("P", slot)
    
    def remove_jewelry(self, slot: str = "") -> List[str]:
        """Remove a ring or amulet. Slot letter optional if only one worn."""
        if slot:
            return self._act("R", slot)
        return self._act("R")
    
    def take_off_armour(self, slot: str) -> List[str]:
        """Take off worn armour by slot letter."""
        return self._act("T", slot)
    
    def examine(self, slot: str) -> List[str]:
        """Examine/describe an inventory item by slot letter."""
        # Open inventory, select item to see description, then dismiss
        msgs = self._act("i", slot)
        self._act("key_esc")  # close description screen
        return msgs

    # --- Overlay / Stats ---

    def _load_persistent_stats(self):
        """Load attempt/win/death counts from overlay stats file."""
        try:
            with open(self._stats_path) as f:
                data = json.load(f)
                self._attempt = data.get("attempt", 0)
                self._wins = data.get("wins", 0)
                self._deaths = data.get("deaths", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def update_overlay(self, thought: str = ""):
        """Write current game state + thought to the stream overlay stats file.
        
        Call this after significant events: each action, level changes, death, win.
        The overlay HTML polls this file every 2 seconds.
        """
        character = f"{self._species} {self._title}".strip() if self._species else "—"
        data = {
            "attempt": self._attempt,
            "wins": self._wins,
            "deaths": self._deaths,
            "character": character,
            "xl": self._xl,
            "place": f"{self._place}:{self._depth}" if self._place else "—",
            "turn": self._turn,
            "thought": thought,
            "status": "Dead" if self._is_dead else "Playing",
        }
        try:
            os.makedirs(os.path.dirname(self._stats_path), exist_ok=True)
            with open(self._stats_path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def new_attempt(self):
        """Call when starting a new game. Increments attempt counter."""
        self._attempt += 1
        self.update_overlay("Starting new game...")

    def record_death(self, cause: str = ""):
        """Call when the character dies. Increments death counter."""
        self._deaths += 1
        self.update_overlay(f"Died: {cause}" if cause else "Died.")

    def record_win(self):
        """Call when the character wins. Increments win counter."""
        self._wins += 1
        self.update_overlay("WON! 🎉")

    # --- Internals ---
    
    def _act(self, *keys: str, timeout: float = 5.0) -> List[str]:
        """Send keys, wait for input_mode, return new messages."""
        if not self._ws or not self._in_game:
            return ["Not in game"]
        
        msg_start = len(self._messages)
        
        # Drain any leftover messages before sending keys
        leftover = self._ws.recv_messages(timeout=0.05)
        for msg in leftover:
            self._process_msg(msg)
        
        for key in keys:
            self._ws.send_key(key)
        
        # Poll until input_mode=1, handling blocking states inline
        deadline = time.time() + timeout
        got_input = False
        got_player = False
        
        while time.time() < deadline and not self._is_dead:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            msgs = self._ws.recv_messages(timeout=min(0.5, remaining))
            
            for msg in msgs:
                self._process_msg(msg)
                mt = msg.get("msg")
                if mt == "input_mode":
                    mode = msg.get("mode")
                    if mode == 1:
                        got_input = True
                    elif mode == 5:
                        # "More" prompt — press space to continue
                        self._ws.send_key(" ")
                    elif mode == 7:
                        # Text input prompt (e.g. "Really quit?", "Call which ally?")
                        # Escape out of it — the AI shouldn't be in text input during _act
                        self._ws.send_key("key_esc")
                    elif mode == 0:
                        # Travelling/auto-explore in progress — wait for it
                        pass
                    else:
                        # Unknown menu/mode (spell list, inventory view, etc.) — escape out
                        logger.debug(f"Auto-escaping unknown input_mode={mode}")
                        self._ws.send_key("key_esc")
                elif mt == "player":
                    got_player = True
                elif mt == "close":
                    self._is_dead = True
                    self._in_game = False
            
            # Exit once we have both input_mode=1 AND a player update
            # (or just input_mode=1 if player came in same batch)
            if got_input and got_player:
                break
            if got_input:
                # Got input but no player yet — do one more quick read
                extra = self._ws.recv_messages(timeout=0.1)
                for msg in extra:
                    self._process_msg(msg)
                break
        
        return self._messages[msg_start:]
    
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
    
    def _update_map(self, msg: Dict[str, Any]):
        cells = msg.get("cells", [])
        cur_x, cur_y = None, None
        for cell in cells:
            if "x" in cell: cur_x = cell["x"]
            if "y" in cell: cur_y = cell["y"]
            if cur_x is not None and cur_y is not None:
                if "g" in cell:
                    self._map_cells[(cur_x, cur_y)] = cell["g"]
                if "mon" in cell:
                    if cell["mon"]:
                        self._monsters[(cur_x, cur_y)] = cell["mon"]
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
    def _strip_html(text: str) -> str:
        return re.sub(r'<[^>]+>', '', text)


class Direction:
    N = "n"; S = "s"; E = "e"; W = "w"
    NE = "ne"; NW = "nw"; SE = "se"; SW = "sw"
