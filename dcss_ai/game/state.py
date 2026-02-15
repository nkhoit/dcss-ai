"""GameState mixin: property accessors and state query methods."""
from typing import List, Dict, Tuple, Any

from .utils import _strip_formatting


class GameState:
    """Mixin providing read-only state accessors and query methods."""

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

    def get_messages(self, n: int = 10) -> List[str]:
        return self._messages[-n:] if self._messages else []

    def get_inventory(self) -> List[Dict[str, Any]]:
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
        LANDMARKS = {'>': 'downstairs', '<': 'upstairs', '_': 'altar', '+': 'door'}
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
                found.append({"type": LANDMARKS[glyph], "glyph": glyph, "direction": direction or "here", "distance": dist, "x": dx, "y": dy})
        type_order = {'downstairs': 0, 'upstairs': 1, 'altar': 2, 'door': 3}
        found.sort(key=lambda f: (type_order.get(f['type'], 9), f['distance']))
        if not found:
            return "No landmarks discovered yet."
        non_doors = [f for f in found if f['type'] != 'door']
        results = non_doors if non_doors else found[:10]
        lines = []
        for f in results:
            lines.append(f"{f['type']} ({f['glyph']}) \u2014 {f['direction']}, {f['distance']} tiles away (dx={f['x']}, dy={f['y']})")
        return "\n".join(lines)

    # Tile flag constants for monster behavior/status (from tile-flags.h)
    _BEH_MASK     = 0x00700000
    _STAB         = 0x00100000
    _MAY_STAB     = 0x00200000
    _FLEEING      = 0x00300000
    _PARALYSED    = 0x00400000
    _MDAM_MASK    = 0x1C0000000
    _MDAM_LIGHT   = 0x040000000
    _MDAM_MOD     = 0x080000000
    _MDAM_HEAVY   = 0x0C0000000
    _MDAM_SEV     = 0x100000000
    _MDAM_ADEAD   = 0x1C0000000

    def _decode_monster_status(self, pos: tuple) -> str:
        """Decode behavior and damage flags from tile fg value."""
        fg = self._tile_fg.get(pos, 0)
        parts = []
        beh = fg & self._BEH_MASK
        if beh == self._STAB:
            parts.append("sleeping")
        elif beh == self._MAY_STAB:
            parts.append("unaware")
        elif beh == self._FLEEING:
            parts.append("fleeing")
        elif beh == self._PARALYSED:
            parts.append("paralysed")
        mdam = fg & self._MDAM_MASK
        if mdam == self._MDAM_LIGHT:
            parts.append("lightly wounded")
        elif mdam == self._MDAM_MOD:
            parts.append("moderately wounded")
        elif mdam == self._MDAM_HEAVY:
            parts.append("heavily wounded")
        elif mdam == self._MDAM_SEV:
            parts.append("severely wounded")
        elif mdam == self._MDAM_ADEAD:
            parts.append("almost dead")
        return ", ".join(parts) if parts else ""

    def get_nearby_enemies(self) -> List[Dict[str, Any]]:
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
            if dist > 8:
                continue
            name = mon.get("name", "unknown").lower()
            if name in IGNORE:
                continue
            direction = ""
            if dy < 0: direction += "n"
            elif dy > 0: direction += "s"
            if dx > 0: direction += "e"
            elif dx < 0: direction += "w"
            status = self._decode_monster_status((mx, my))
            enemies.append({"name": mon.get("name", "unknown"), "x": dx, "y": dy, "direction": direction or "here", "distance": dist, "threat": mon.get("threat", 0), "status": status})
        enemies.sort(key=lambda e: e["distance"])
        return enemies

    def get_stats(self) -> str:
        char_info = f"{self._species} {self._title}".strip() if self._species else "Unknown"
        return (f"Character: {char_info} | HP: {self._hp}/{self._max_hp} | MP: {self._mp}/{self._max_mp} | "
                f"AC: {self._ac} EV: {self._ev} SH: {self._sh} | Str: {self._str} Int: {self._int} Dex: {self._dex} | "
                f"XL: {self._xl} | Gold: {self._gold} | Place: {self._place}:{self._depth} | God: {self._god or 'None'} | Turn: {self._turn}")

    def get_state_text(self) -> str:
        parts = ["=== DCSS State ===", self.get_stats(), "", "--- Messages ---"]
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
                status_str = f", {e['status']}" if e.get('status') else ""
                parts.append(f"  {e['name']} ({e['direction']}, dist {e['distance']}, threat {e['threat']}{status_str})")
        parts.append("")
        parts.append("--- Map ---")
        parts.append(self.get_map())
        if self._is_dead:
            parts.append("\n*** GAME OVER \u2014 YOU ARE DEAD ***")
        return "\n".join(parts)

    def write_note(self, text: str, page: str = "") -> str:
        if not page:
            page = f"{self._place}:{self._depth}" if self._place else "general"
        if page not in self._notepad:
            self._notepad[page] = []
        self._notepad[page].append(text)
        total = sum(len(v) for v in self._notepad.values())
        return f"Note saved to [{page}] ({len(self._notepad[page])} notes on this page, {total} total)."

    def read_notes(self, page: str = "") -> str:
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
        if page in self._notepad:
            count = len(self._notepad.pop(page))
            return f"Ripped out [{page}] ({count} notes removed)."
        return f"No page [{page}] to rip out."
