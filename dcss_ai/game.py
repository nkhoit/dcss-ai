"""DCSS Game API wrapper for LLM-controlled gameplay."""
import json
import logging
import os
import re
import time
from typing import Optional, List, Dict, Tuple, Any
from dcss_ai.webtiles import WebTilesConnection
from dcss_ai.overlay import send_stats, send_thought, send_reset

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
        self._actions_since_narrate = 0  # track actions between narrate() calls
        self._session_ended = False  # set on death/win — blocks new games
        self._species = ""
        self._title = ""
        
        # Inventory
        self._inventory: Dict[int, Dict[str, Any]] = {}
        
        # Message history and map state
        self._messages: List[str] = []
        self._map_cells: Dict[Tuple[int, int], str] = {}
        self._monsters: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._monster_names: Dict[int, str] = {}  # id -> name cache
        
        # Menu state
        self._current_menu: Optional[Dict[str, Any]] = None
        self._menu_items: List[Dict[str, Any]] = []
        
        # UI popup state
        self._current_popup: Optional[Dict[str, Any]] = None
        
        # Pending text prompt (e.g. stat increase)
        self._pending_prompt: Optional[str] = None
        
        # Notepad — survives SDK compaction (lives on this object, not in chat history)
        # Keyed by page name (e.g. "D:1", "D:2", "general")
        self._notepad: Dict[str, List[str]] = {}
    
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
        if self._session_ended:
            return "Session has ended (death/win recorded). Say GAME_OVER to finish."
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
            # Bump attempt to trigger overlay iframe reload
            self._attempt += 1
            self.update_overlay("Clearing stale save, restarting...")
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
    
    def get_landmarks(self) -> str:
        """Find notable features on the explored map: stairs, shops, altars, portals."""
        LANDMARKS = {
            '>': 'downstairs',
            '<': 'upstairs',
            '_': 'altar',
            '+': 'door',
        }
        # Also match shop tiles (could be various chars)
        px, py = self._position
        found = []
        for (x, y), glyph in self._map_cells.items():
            if glyph in LANDMARKS:
                dx, dy = x - px, y - py
                dist = max(abs(dx), abs(dy))
                direction = ""
                if dy < 0: direction += "N"
                elif dy > 0: direction += "S"
                if dx > 0: direction += "E"
                elif dx < 0: direction += "W"
                found.append({
                    "type": LANDMARKS[glyph],
                    "glyph": glyph,
                    "direction": direction or "here",
                    "distance": dist,
                    "x": dx, "y": dy,
                })
        # Sort by type priority then distance
        type_order = {'downstairs': 0, 'upstairs': 1, 'altar': 2, 'door': 3}
        found.sort(key=lambda f: (type_order.get(f['type'], 9), f['distance']))
        
        if not found:
            return "No landmarks discovered yet."
        
        # Filter out doors (too noisy) unless very few landmarks
        non_doors = [f for f in found if f['type'] != 'door']
        results = non_doors if non_doors else found[:10]
        
        lines = []
        for f in results:
            lines.append(f"{f['type']} ({f['glyph']}) — {f['direction']}, {f['distance']} tiles away (dx={f['x']}, dy={f['y']})")
        return "\n".join(lines)

    def write_note(self, text: str, page: str = "") -> str:
        """Write a note to a notepad page. Default page = current floor."""
        if not page:
            page = f"{self._place}:{self._depth}" if self._place else "general"
        if page not in self._notepad:
            self._notepad[page] = []
        self._notepad[page].append(text)
        total = sum(len(v) for v in self._notepad.values())
        return f"Note saved to [{page}] ({len(self._notepad[page])} notes on this page, {total} total)."
    
    def read_notes(self, page: str = "") -> str:
        """Read notepad. If page specified, show that page. Otherwise show all pages."""
        if not self._notepad:
            return "Notepad is empty."
        if page:
            notes = self._notepad.get(page, [])
            if not notes:
                return f"No notes on page [{page}]."
            return f"[{page}]\n" + "\n".join(f"- {n}" for n in notes)
        lines = []
        for p, notes in self._notepad.items():
            lines.append(f"[{p}]")
            for n in notes:
                lines.append(f"  - {n}")
        return "\n".join(lines)
    
    def rip_page(self, page: str) -> str:
        """Remove a page from the notepad."""
        if page in self._notepad:
            count = len(self._notepad.pop(page))
            return f"Ripped out [{page}] ({count} notes removed)."
        return f"No page [{page}] to rip out."

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
            dx, dy = mx - px, my - py
            dist = max(abs(dx), abs(dy))
            if dist > 8:  # LOS radius is 7, +1 buffer
                continue
            name = mon.get("name", "unknown").lower()
            if name in IGNORE:
                continue
            direction = ""
            if dy < 0: direction += "n"
            elif dy > 0: direction += "s"
            if dx > 0: direction += "e"
            elif dx < 0: direction += "w"
            enemies.append({
                "name": mon.get("name", "unknown"),
                "x": dx, "y": dy,
                "direction": direction or "here",
                "distance": dist,
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
        pos_before = self._position
        turn_before = self._turn
        result = self._act(key_map[d])
        if self._turn == turn_before:
            result.append(f"[Nothing happened — there's a wall or obstacle to the {direction}. Use auto_explore() or go_downstairs() to navigate.]")
        return result
    
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
        """Pick up items at current position. Uses comma to auto-grab all."""
        msgs = self._act(",")
        if self._current_menu:
            msgs.append("[A pickup menu opened — use read_ui() to see items, select_menu_item() to pick specific items, or dismiss() to cancel]")
        return msgs
    
    def use_ability(self, key: str) -> List[str]:
        """Use ability: a=Berserk, b=Trog's Hand, c=Brothers in Arms."""
        return self._act("a", key)
    
    def cast_spell(self, key: str, direction: str = "") -> List[str]:
        """Cast a spell. Direction is optional — some spells auto-target or are self-targeted.
        If the spell needs targeting, DCSS will prompt; if no direction given, confirms with '.'"""
        if direction:
            return self._act("z", key, self._dir_key(direction))
        else:
            # Self-targeted or auto-targeted: confirm with '.'
            return self._act("z", key, ".")
    
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
    
    def choose_stat(self, stat: str) -> List[str]:
        """Choose a stat to increase on level up: s=Strength, i=Intelligence, d=Dexterity."""
        stat = stat.upper()
        if stat not in ("S", "I", "D"):
            return ["[ERROR: Invalid stat. Use 'S' (Strength), 'I' (Intelligence), or 'D' (Dexterity).]"]
        if self._pending_prompt != "stat_increase":
            return ["[No stat increase prompt pending.]"]
        self._pending_prompt = None
        return self._act(stat, menu_ok=True)

    def respond(self, action: str) -> List[str]:
        """Respond to a prompt: yes (Y), no (N), or escape."""
        key_map = {"yes": "Y", "no": "N", "escape": "key_esc"}
        key = key_map.get(action.lower(), "key_esc")
        return self._act(key, menu_ok=True)

    def escape(self) -> List[str]:
        return self._act("key_esc", menu_ok=True)
    
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
        # Return what we know from cached inventory data
        inv = self.get_inventory()
        for item in inv:
            if item.get("slot") == slot:
                return [f"{slot} - {item.get('name', 'unknown')} (qty: {item.get('quantity', 1)})"]
        return [f"No item in slot '{slot}'."]

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

    def read_ui(self) -> str:
        """Read whatever UI element is currently open (menu or popup).
        
        Returns the content of the active menu or popup, whichever is open.
        """
        if self._current_menu:
            return self.read_menu()
        if self._current_popup:
            return self.read_popup()
        return "No menu or popup is currently open."

    def dismiss(self) -> str:
        """Dismiss the current UI element (menu or popup) by pressing Escape."""
        if self._current_menu:
            return self.close_menu()
        if self._current_popup:
            return self.dismiss_popup()
        # Still send escape in case something is open we don't track
        self._ws.send_key("key_esc")
        return "Escape pressed."

    # --- Menu interaction ---

    def read_menu(self) -> str:
        """Read the currently open menu. Returns title, tag, and all items with hotkeys.
        
        Works for any DCSS menu: shops, spell lists, ability menus, item selection, etc.
        If no menu is open, returns a message saying so.
        """
        if not self._current_menu:
            return "No menu is currently open."
        
        m = self._current_menu
        lines = []
        tag = m.get("tag", "unknown")
        
        # Title
        title = m.get("title", {})
        if isinstance(title, dict):
            title_text = title.get("text", "Menu")
        elif isinstance(title, str):
            title_text = title
        else:
            title_text = "Menu"
        # Strip formatting codes
        title_text = self._strip_formatting(title_text)
        lines.append(f"=== {title_text} (type: {tag}) ===")
        
        # More text (usually shows gold for shops, or page info)
        more = m.get("more", "")
        if isinstance(more, dict):
            more = more.get("text", "")
        more = self._strip_formatting(more)
        if more:
            lines.append(more)
        
        # Items
        for item in self._menu_items:
            text = item.get("text", "")
            text = self._strip_formatting(text)
            if not text.strip():
                continue
            level = item.get("level", 2)
            hotkeys = item.get("hotkeys", [])
            
            if level < 2:
                # Header/category
                lines.append(f"\n  {text}")
            elif hotkeys:
                key = chr(hotkeys[0]) if isinstance(hotkeys[0], int) else hotkeys[0]
                lines.append(f"  [{key}] {text}")
            else:
                lines.append(f"      {text}")
        
        return "\n".join(lines)

    def select_menu_item(self, key: str) -> str:
        """Select an item in the current menu by pressing its hotkey letter.
        
        For shops: press the letter to toggle item selection, then Enter/! to buy.
        For other menus: press the letter to select/use the item.
        """
        if not self._current_menu:
            return "No menu is currently open."
        
        self._ws.send_key(key)
        # Read response — menu may update or close
        import time
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        
        menu_closed = False
        for msg in msgs:
            self._process_msg(msg)
            mt = msg.get("msg")
            if mt == "close_menu":
                menu_closed = True
                self._current_menu = None
                self._menu_items = []
            elif mt in ("menu", "update_menu", "update_menu_items"):
                self._handle_menu_msg(msg)
        
        if menu_closed:
            return f"Menu closed after pressing '{key}'."
        elif self._current_menu:
            return f"Pressed '{key}'. Menu still open. Use read_menu() to see updated state."
        return f"Pressed '{key}'."

    def close_menu(self) -> str:
        """Close the currently open menu by pressing Escape."""
        if not self._current_menu:
            return "No menu is currently open."
        
        self._ws.send_key("key_esc")
        import time
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        for msg in msgs:
            self._process_msg(msg)
            if msg.get("msg") == "close_menu":
                self._current_menu = None
                self._menu_items = []
        
        self._current_menu = None
        self._menu_items = []
        return "Menu closed."

    def _handle_menu_msg(self, msg: dict):
        """Process a menu/update_menu message and cache its data."""
        mt = msg.get("msg")
        if mt == "menu":
            self._current_menu = msg
            self._menu_items = msg.get("items", [])
        elif mt == "update_menu":
            if self._current_menu:
                # Merge updates
                for k, v in msg.items():
                    if k != "msg":
                        self._current_menu[k] = v
                if "items" in msg:
                    self._menu_items = msg["items"]
        elif mt == "update_menu_items":
            # Partial item update
            chunk_start = msg.get("chunk_start", 0)
            new_items = msg.get("items", [])
            for i, item in enumerate(new_items):
                idx = chunk_start + i
                if idx < len(self._menu_items):
                    self._menu_items[idx] = item
                else:
                    self._menu_items.append(item)

    # --- UI popup interaction ---

    def _handle_ui_msg(self, msg: dict):
        """Process a ui-push/ui-state message and cache it."""
        mt = msg.get("msg")
        if mt == "ui-push":
            self._current_popup = msg
        elif mt == "ui-state" and self._current_popup:
            # Update existing popup
            for k, v in msg.items():
                if k != "msg":
                    self._current_popup[k] = v

    def read_popup(self) -> str:
        """Read the currently open UI popup (description, god screen, etc.).
        
        Returns the popup type and readable text content.
        If no popup is open, returns a message saying so.
        """
        if not self._current_popup:
            return "No popup is currently open."
        
        p = self._current_popup
        ui_type = p.get("type", "unknown")
        lines = [f"=== Popup: {ui_type} ==="]
        
        # Extract text from various popup formats
        # formatted-scroller: has "body" with formatted text
        body = p.get("body", "")
        if body:
            if isinstance(body, str):
                lines.append(self._strip_formatting(body))
            elif isinstance(body, dict):
                lines.append(self._strip_formatting(body.get("text", str(body))))
        
        # Title
        title = p.get("title", "")
        if title:
            if isinstance(title, str):
                lines.insert(1, self._strip_formatting(title))
            elif isinstance(title, dict):
                lines.insert(1, self._strip_formatting(title.get("text", "")))
        
        # Some popups have "prompt"
        prompt = p.get("prompt", "")
        if prompt:
            lines.append(self._strip_formatting(prompt if isinstance(prompt, str) else str(prompt)))
        
        # Describe-item/monster/god specific fields
        for field in ("description", "quote", "spells_description", "stats"):
            val = p.get(field, "")
            if val:
                text = val if isinstance(val, str) else str(val)
                lines.append(self._strip_formatting(text))
        
        # If we got nothing useful, dump available keys
        if len(lines) == 1:
            data_keys = [k for k in p.keys() if k not in ("msg", "type", "generation_id")]
            lines.append(f"Data keys: {', '.join(data_keys)}")
        
        return "\n".join(lines)

    def dismiss_popup(self) -> str:
        """Dismiss the currently open UI popup by pressing Escape."""
        if not self._current_popup:
            return "No popup is currently open."
        
        self._ws.send_key("key_esc")
        import time
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        for msg in msgs:
            self._process_msg(msg)
            if msg.get("msg") == "ui-pop":
                self._current_popup = None
        
        self._current_popup = None
        return "Popup dismissed."

    @staticmethod
    def _strip_formatting(text: str) -> str:
        """Strip DCSS formatting codes from text (e.g. color tags)."""
        import re
        # Remove <color> tags and similar formatting
        text = re.sub(r'<[^>]+>', '', text)
        # Remove § color codes
        text = re.sub(r'§.', '', text)
        return text.strip()

    def update_overlay(self, thought: str = ""):
        """Push current game state to connected overlays via SSE.
        
        Also writes to stats file as fallback.
        Call this after significant events: each action, level changes, death, win.
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
        send_stats(data)
        if thought:
            send_thought(thought)
        # Fallback: write stats file
        try:
            os.makedirs(os.path.dirname(self._stats_path), exist_ok=True)
            with open(self._stats_path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def new_attempt(self):
        """Call when starting a new game. Increments attempt counter."""
        if self._session_ended:
            return "Session has ended. Say GAME_OVER to finish."
        self._attempt += 1
        self.update_overlay("Starting new game...")

    def record_death(self, cause: str = ""):
        """Call when the character dies. Increments death counter."""
        if not self._is_dead:
            return "You're not dead! HP: {}/{}. Keep playing.".format(self._hp, self._max_hp)
        self._deaths += 1
        self._session_ended = True
        self.update_overlay(f"Died: {cause}" if cause else "Died.")

    def record_win(self):
        """Call when the character wins. Increments win counter."""
        self._wins += 1
        self._session_ended = True
        self.update_overlay("WON! 🎉")

    # --- Internals ---
    
    def _act(self, *keys: str, timeout: float = 5.0, menu_ok: bool = False) -> List[str]:
        """Send keys, wait for input_mode, return new messages."""
        if not self._ws or not self._in_game:
            return ["Not in game"]
        
        # Enforce narration — block actions if overdue (set DCSS_NARRATE_INTERVAL=0 to disable)
        NARRATE_INTERVAL = int(os.environ.get("DCSS_NARRATE_INTERVAL", "5"))
        if NARRATE_INTERVAL > 0 and not menu_ok and self._actions_since_narrate >= NARRATE_INTERVAL:
            return [f"[ERROR: You must call narrate() before continuing. You've taken {self._actions_since_narrate} actions without narrating for stream viewers.]"]
        if not menu_ok:
            self._actions_since_narrate += 1
        
        # Block game actions while a prompt is pending
        if not menu_ok and self._pending_prompt:
            if self._pending_prompt == "stat_increase":
                return ["[ERROR: Stat increase prompt is waiting! Call choose_stat('s'), choose_stat('i'), or choose_stat('d') to pick Strength, Intelligence, or Dexterity.]"]
            return [f"[ERROR: A prompt is pending: {self._pending_prompt}]"]
        
        # Block game actions while a menu/popup is open
        if not menu_ok and self._current_menu:
            title = self._current_menu.get("title", "a menu")
            return [f"[ERROR: {title} is still open. Use read_ui() to see it, select_menu_item() to interact, or dismiss() to close it first.]"]
        if not menu_ok and self._current_popup:
            return ["[ERROR: A popup is still open. Use read_ui() to see it or dismiss() to close it first.]"]
        
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
                        # "More" prompt — press space to continue
                        self._ws.send_key(" ")
                    elif mode == 7:
                        # Text input prompt — check if it's a stat increase
                        recent = self._messages[-5:] if self._messages else []
                        stat_prompt = any("(S)trength" in m for m in recent)
                        if stat_prompt:
                            self._pending_prompt = "stat_increase"
                            logger.info(f"Stat increase prompt detected (keys={keys})")
                            got_input = True  # return to AI so it can choose
                        else:
                            logger.info(f"Text input prompt during _act, escaping (keys={keys})")
                            self._ws.send_key("key_esc")
                    elif mode == 0:
                        # Travelling/auto-explore in progress — wait for it
                        pass
                    else:
                        logger.info(f"Unknown input_mode={mode}, escaping (keys={keys})")
                        self._ws.send_key("key_esc")
                elif mt == "player":
                    got_player = True
                elif mt == "close":
                    logger.info(f"Game closed (death). keys={keys}")
                    self._is_dead = True
                    self._in_game = False
                elif mt in ("ui-push", "ui-state"):
                    # UI popup (description, god screen, etc.) — cache for read_popup()
                    ui_type = msg.get("type", "unknown")
                    logger.info(f"UI popup ({mt}) type={ui_type} during _act (keys={keys})")
                    self._handle_ui_msg(msg)
                    got_input = True
                elif mt == "ui-pop":
                    self._current_popup = None
                elif mt in ("menu", "update_menu", "update_menu_items"):
                    # Menu opened/updated — cache it for read_menu() tool
                    logger.info(f"Menu message ({mt}) tag={msg.get('tag', '?')} during _act (keys={keys})")
                    self._handle_menu_msg(msg)
                    # Don't auto-escape — let the AI interact with it
                    got_input = True  # treat menu as actionable state
                elif mt in ("close_menu", "close_all_menus"):
                    self._current_menu = None
                    self._menu_items = []
            
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
        
        if not got_input and not self._is_dead:
            logger.warning(f"_act finished without input_mode=1! keys={keys}, timeout={timeout}")
        
        new_msgs = self._messages[msg_start:]
        
        # Flag unknown commands so AI can learn
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
        if not cells:
            return
        # Remove monsters at any cell position included in this update
        # (DCSS sends updated cells — if a monster died/moved, its cell
        # will be in the update without a "mon" entry)
        updated_positions = set()
        cur_x, cur_y = None, None
        for cell in cells:
            if "x" in cell: cur_x = cell["x"]
            if "y" in cell: cur_y = cell["y"]
            if cur_x is not None and cur_y is not None:
                updated_positions.add((cur_x, cur_y))
        for pos in updated_positions:
            self._monsters.pop(pos, None)
        cur_x, cur_y = None, None
        for cell in cells:
            if "x" in cell: cur_x = cell["x"]
            if "y" in cell: cur_y = cell["y"]
            if cur_x is not None and cur_y is not None:
                if "g" in cell:
                    self._map_cells[(cur_x, cur_y)] = cell["g"]
                if "mon" in cell:
                    if cell["mon"]:
                        mon_data = cell["mon"]
                        mon_id = mon_data.get("id")
                        # Cache name when we first see it
                        if "name" in mon_data and mon_id is not None:
                            self._monster_names[mon_id] = mon_data["name"]
                        # Merge with existing + inject cached name
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
    def _strip_html(text: str) -> str:
        return re.sub(r'<[^>]+>', '', text)


class Direction:
    N = "n"; S = "s"; E = "e"; W = "w"
    NE = "ne"; NW = "nw"; SE = "se"; SW = "sw"
