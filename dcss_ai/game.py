"""DCSS Game API wrapper for LLM-controlled gameplay."""
import json
import re
import time
from typing import Optional, List, Dict, Tuple, Any
from dcss_ai.webtiles import WebTilesConnection


class DCSSGame:
    """High-level API for controlling DCSS via webtiles WebSocket.
    
    All state is updated incrementally from WebSocket messages.
    Properties are free (no turn cost). Actions consume turns.
    """
    
    def __init__(self):
        self._ws: Optional[WebTilesConnection] = None
        self._connected = False
        self._in_game = False
        self._game_ids: List[str] = []
        
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
        
        # Inventory
        self._inventory: Dict[int, Dict[str, Any]] = {}
        
        # Message history and map state
        self._messages: List[str] = []
        self._map_cells: Dict[Tuple[int, int], str] = {}
        self._monsters: Dict[Tuple[int, int], Dict[str, Any]] = {}
    
    # --- Connection/lifecycle ---
    
    def connect(self, url: str, username: str, password: str) -> bool:
        """Connect to DCSS webtiles server and login."""
        try:
            self._ws = WebTilesConnection(url)
            self._ws.recv_messages(timeout=0.5)  # drain initial ping
            
            # Register (ignore if exists)
            try:
                self._ws.register(username, password)
                self._ws.disconnect()
                self._ws = WebTilesConnection(url)
                self._ws.recv_messages(timeout=0.5)
            except Exception:
                pass
            
            # Login
            self._game_ids = self._ws.login(username, password)
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"Connection failed: {e}")
    
    def start_game(self, species_key: str, background_key: str, weapon_key: str = "", game_id: str = "") -> str:
        """Start a new game. Returns initial state."""
        if not self._connected or not self._ws:
            raise RuntimeError("Not connected to server")
        
        gid = game_id or self._game_ids[0]
        startup_msgs = self._ws.start_game(gid, species_key, background_key, weapon_key)
        
        # Process all startup messages
        for msg in startup_msgs:
            self._process_msg(msg)
        
        self._in_game = True
        self._is_dead = False
        self._messages.clear()
        
        # Warmup — send a wait to populate map and get input_mode
        self._act(".")
        
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
        """Get visible enemies sorted by distance."""
        px, py = self._position
        enemies = []
        for (mx, my), mon in self._monsters.items():
            if not mon:
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
        return (
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
        return self._act("g")
    
    def use_ability(self, key: str) -> List[str]:
        """Use ability: a=Berserk, b=Trog's Hand, c=Brothers in Arms."""
        return self._act("a", key)
    
    def cast_spell(self, key: str, direction: str = "") -> List[str]:
        keys = ["z", key]
        if direction:
            key_map = {"n":"key_dir_n","s":"key_dir_s","e":"key_dir_e","w":"key_dir_w",
                       "ne":"key_dir_ne","nw":"key_dir_nw","se":"key_dir_se","sw":"key_dir_sw"}
            if direction.lower() in key_map:
                keys.append(key_map[direction.lower()])
        return self._act(*keys)
    
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
    
    # --- Internals ---
    
    def _act(self, *keys: str, timeout: float = 30.0) -> List[str]:
        """Send keys, wait for input_mode, return new messages.
        
        Timeout prevents hangs. For long actions (explore big floor),
        30s is generous but won't block forever.
        """
        if not self._ws or not self._in_game:
            return ["Not in game"]
        
        msg_start = len(self._messages)
        
        for key in keys:
            self._ws.send_key(key)
        
        # Wait for input_mode with mode=1 (normal input ready)
        found, all_msgs = self._ws.wait_for("input_mode", "mode", 1, timeout=timeout)
        
        # Process all received messages
        for msg in all_msgs:
            self._process_msg(msg)
        
        # Handle blocking states (More prompts, death, menus)
        if not found and not self._is_dead:
            # Check if we're in a blocking state
            for msg in all_msgs:
                mt = msg.get("msg")
                if mt == "input_mode":
                    mode = msg.get("mode")
                    if mode == 5:  # More prompt
                        return self._act(" ")  # Press space
                    elif mode == 7:  # Died
                        self._is_dead = True
                        self._in_game = False
            
            # Try escape to clear any stuck state
            self._ws.send_key("key_esc")
            found2, more_msgs = self._ws.wait_for("input_mode", "mode", 1, timeout=3.0)
            for msg in more_msgs:
                self._process_msg(msg)
        
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
