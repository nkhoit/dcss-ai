"""DCSS Game API wrapper for MCP server."""
import json
import re
from typing import Optional, List, Dict, Tuple, Any
import dcss_api


class DCSSGame:
    """High-level API for controlling DCSS via dcss-api WebtilePy.
    
    All state is updated incrementally from WebSocket messages.
    Properties are free (no turn cost). Actions consume turns.
    """
    
    def __init__(self):
        self._client: Optional[dcss_api.WebtilePy] = None
        self._connected = False
        self._in_game = False
        self._game_ids: List[str] = []
        
        # Player stats (updated incrementally from "player" messages)
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
        
        # Inventory (updated from "player" messages, "inv" field)
        self._inventory: Dict[int, Dict[str, Any]] = {}
        
        # Message history and map state
        self._messages: List[str] = []
        self._map_cells: Dict[Tuple[int, int], str] = {}
    
    # --- Connection/lifecycle ---
    
    def connect(self, url: str, username: str, password: str) -> bool:
        """Connect to DCSS webtiles server and login."""
        try:
            self._client = dcss_api.WebtilePy(url, 100)
            self._drain()
            
            # Try to register (ignore if user exists)
            try:
                self._client.register_account(username, password, None)
            except Exception:
                pass
            self._drain()
            
            # Login
            self._game_ids = self._client.login_with_credentials(username, password)
            self._drain()
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"Connection failed: {e}")
    
    def start_game(self, species_key: str, background_key: str, weapon_key: str = "", game_id: str = "") -> str:
        """Start a new game. Returns initial state summary.
        
        Args:
            species_key: Single char for species selection (e.g. 'b' for Minotaur)
            background_key: Single char for background (e.g. 'f' for Berserker)  
            weapon_key: Single char for weapon choice (e.g. 'b' for mace)
            game_id: Which game mode (default: first available, usually 'dcss-web-trunk')
        """
        if not self._connected or not self._client:
            raise RuntimeError("Not connected to server")
        
        gid = game_id or self._game_ids[0]
        self._client.start_game(gid, species_key, background_key, weapon_key)
        self._drain()
        
        self._in_game = True
        self._is_dead = False
        self._messages.clear()
        self._map_cells.clear()
        
        return self.get_state_text()
    
    def quit_game(self):
        """Quit current game (same as dying)."""
        if self._in_game and self._client:
            self._client.quit_game()
            self._drain()
            self._in_game = False
    
    def disconnect(self):
        """Disconnect from server."""
        if self._client:
            try:
                if self._in_game:
                    self.quit_game()
                self._client.disconnect()
            except Exception:
                pass
        self._connected = False
        self._in_game = False
    
    # --- Properties (free, no turn cost) ---
    
    @property
    def hp(self) -> int:
        return self._hp
    
    @property
    def max_hp(self) -> int:
        return self._max_hp
    
    @property
    def mp(self) -> int:
        return self._mp
    
    @property
    def max_mp(self) -> int:
        return self._max_mp
    
    @property
    def ac(self) -> int:
        return self._ac
    
    @property
    def ev(self) -> int:
        return self._ev
    
    @property
    def sh(self) -> int:
        return self._sh
    
    @property
    def strength(self) -> int:
        return self._str
    
    @property
    def intelligence(self) -> int:
        return self._int
    
    @property
    def dexterity(self) -> int:
        return self._dex
    
    @property
    def xl(self) -> int:
        return self._xl
    
    @property
    def place(self) -> str:
        return self._place
    
    @property
    def depth(self) -> int:
        return self._depth
    
    @property
    def god(self) -> str:
        return self._god
    
    @property
    def gold(self) -> int:
        return self._gold
    
    @property
    def position(self) -> Tuple[int, int]:
        return self._position
    
    @property
    def is_dead(self) -> bool:
        return self._is_dead
    
    @property
    def turn(self) -> int:
        return self._turn
    
    # --- State queries (free) ---
    
    def get_messages(self, n: int = 10) -> List[str]:
        """Get last n game messages."""
        return self._messages[-n:] if self._messages else []
    
    def get_inventory(self) -> List[Dict[str, Any]]:
        """Get inventory as list of {slot, name, quantity}. Only real items."""
        items = []
        for slot, data in sorted(self._inventory.items()):
            name = data.get("name", "")
            # Skip empty/placeholder slots
            if not name or name == "?" or data.get("quantity", 0) == 0 and not name:
                continue
            items.append({
                "slot": chr(ord('a') + slot) if slot < 26 else str(slot),
                "name": name,
                "quantity": data.get("quantity", 1),
            })
        return items
    
    def get_map(self, radius: int = 7) -> str:
        """Get ASCII map centered on player position."""
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
    
    def get_stats(self) -> str:
        """Get formatted stats string."""
        return (
            f"HP: {self._hp}/{self._max_hp} | MP: {self._mp}/{self._max_mp} | "
            f"AC: {self._ac} EV: {self._ev} SH: {self._sh} | "
            f"Str: {self._str} Int: {self._int} Dex: {self._dex} | "
            f"XL: {self._xl} | Gold: {self._gold} | "
            f"Place: {self._place}:{self._depth} | "
            f"God: {self._god or 'None'} | Turn: {self._turn}"
        )
    
    def get_state_text(self) -> str:
        """Get full state as formatted text for LLM consumption."""
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
        
        parts.append("")
        parts.append("--- Map ---")
        parts.append(self.get_map())
        
        if self._is_dead:
            parts.append("\n*** GAME OVER — YOU ARE DEAD ***")
        
        return "\n".join(parts)
    
    # --- Actions (consume turns) ---
    
    def move(self, direction: str) -> List[str]:
        """Move in direction: n/s/e/w/ne/nw/se/sw"""
        key_map = {
            "n": "key_dir_n", "s": "key_dir_s", "e": "key_dir_e", "w": "key_dir_w",
            "ne": "key_dir_ne", "nw": "key_dir_nw", "se": "key_dir_se", "sw": "key_dir_sw",
        }
        d = direction.lower()
        if d not in key_map:
            return [f"Invalid direction: {direction}. Use n/s/e/w/ne/nw/se/sw"]
        return self._act(key_map[d])
    
    def auto_explore(self) -> List[str]:
        """Auto-explore (o key)."""
        return self._act("o")
    
    def auto_fight(self) -> List[str]:
        """Auto-fight nearest enemy (Tab key)."""
        return self._act("key_tab")
    
    def rest(self) -> List[str]:
        """Rest/wait for long rest (5 key)."""
        return self._act("5")
    
    def wait_turn(self) -> List[str]:
        """Wait one turn (. key)."""
        return self._act(".")
    
    def go_upstairs(self) -> List[str]:
        return self._act("<")
    
    def go_downstairs(self) -> List[str]:
        return self._act(">")
    
    def pickup(self) -> List[str]:
        """Pick up items on ground."""
        return self._act("g")
    
    def use_ability(self, key: str) -> List[str]:
        """Use ability menu then select."""
        return self._act("a", key)
    
    def cast_spell(self, key: str, direction: str = "") -> List[str]:
        """Cast spell, optionally with direction."""
        keys = ["z", key]
        if direction:
            key_map = {
                "n": "key_dir_n", "s": "key_dir_s", "e": "key_dir_e", "w": "key_dir_w",
                "ne": "key_dir_ne", "nw": "key_dir_nw", "se": "key_dir_se", "sw": "key_dir_sw",
            }
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
    
    def _act(self, *keys: str) -> List[str]:
        """Send keys, wait for input mode, return new messages."""
        if not self._client or not self._in_game:
            return ["Not in game"]
        
        msg_start = len(self._messages)
        
        for key in keys:
            self._client.write_key(key)
        
        # Wait for game to be ready for input
        try:
            self._client.read_until("input_mode", "mode", 1)
        except dcss_api.BlockingErr as e:
            self._handle_blocking(e)
        except dcss_api.APIErr:
            pass  # Timeout or other API error
        
        self._drain()
        return self._messages[msg_start:]
    
    def _handle_blocking(self, e: dcss_api.BlockingErr):
        """Handle blocking states from read_until."""
        err_str = str(e.args[0]) if e.args else str(e)
        
        if err_str == "More":
            # More prompt — press space to continue
            self._client.write_key(" ")
            try:
                self._client.read_until("input_mode", "mode", 1)
            except dcss_api.BlockingErr as e2:
                self._handle_blocking(e2)
        elif err_str == "Died":
            self._is_dead = True
            self._in_game = False
        elif err_str in ("TextInput", "Pickup", "Acquirement", "Identify",
                         "EnchantWeapon", "EnchantItem", "BrandWeapon"):
            # Menu/prompt — escape out for now
            self._client.write_key("key_esc")
        
        self._drain()
    
    def _drain(self):
        """Drain all pending messages and update state."""
        if not self._client:
            return
        while True:
            msg_str = self._client.get_message()
            if msg_str is None:
                break
            try:
                msg = json.loads(msg_str)
            except (json.JSONDecodeError, TypeError):
                continue
            
            msg_type = msg.get("msg")
            if msg_type == "player":
                self._update_player(msg)
            elif msg_type == "map":
                self._update_map(msg)
            elif msg_type == "msgs":
                self._update_messages(msg)
            # Ignore: ping, lobby_*, input_mode, ui-*, version, options, layout, etc.
    
    def _update_player(self, msg: Dict[str, Any]):
        """Incrementally update player stats."""
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
        
        # Position
        if "pos" in msg:
            pos = msg["pos"]
            if isinstance(pos, dict):
                self._position = (pos.get("x", 0), pos.get("y", 0))
        
        # Inventory (incremental)
        if "inv" in msg:
            for slot_str, item_data in msg["inv"].items():
                slot = int(slot_str)
                if item_data:
                    self._inventory[slot] = item_data
                else:
                    self._inventory.pop(slot, None)
    
    def _update_map(self, msg: Dict[str, Any]):
        """Incrementally update map cells."""
        cells = msg.get("cells", [])
        # Cells use relative positioning — track current x/y across the array
        cur_x = None
        cur_y = None
        for cell in cells:
            if "x" in cell:
                cur_x = cell["x"]
            if "y" in cell:
                cur_y = cell["y"]
            if cur_x is not None and cur_y is not None:
                if "g" in cell:
                    self._map_cells[(cur_x, cur_y)] = cell["g"]
                # Advance x for next cell in row
                cur_x += 1
    
    def _update_messages(self, msg: Dict[str, Any]):
        """Parse game messages from msgs payload."""
        messages = msg.get("messages", [])
        for m in messages:
            text = m.get("text", "")
            if text:
                clean = self._strip_html(text)
                if clean.strip():
                    self._messages.append(clean.strip())
        
        # Cap message history
        if len(self._messages) > 200:
            self._messages = self._messages[-100:]
    
    @staticmethod
    def _strip_html(text: str) -> str:
        """Strip DCSS HTML-like tags from message text."""
        return re.sub(r'<[^>]+>', '', text)


class Direction:
    """Direction constants for convenience in sandbox."""
    N = "n"
    S = "s"
    E = "e"
    W = "w"
    NE = "ne"
    NW = "nw"
    SE = "se"
    SW = "sw"
