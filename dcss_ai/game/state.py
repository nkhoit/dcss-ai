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

    @property
    def status_effects(self) -> list: return self._status_effects
    @property
    def poison_survival(self) -> int: return self._poison_survival
    @property
    def piety_rank(self) -> int: return self._piety_rank
    @property
    def penance(self) -> bool: return self._penance
    @property
    def contamination(self) -> int: return self._contam
    @property
    def noise(self) -> int: return self._adjusted_noise
    @property
    def quiver_desc(self) -> str: return self._quiver_desc
    @property
    def xl_progress(self) -> int: return self._xl_progress

    def get_messages(self, n: int = 10) -> List[str]:
        return self._messages[-n:] if self._messages else []

    def get_cell_overlays_at(self, pos: tuple = None) -> Dict[str, Any]:
        """Get environmental overlays at a position (default: player position)."""
        if pos is None:
            pos = self._position
        return self._cell_overlays.get(pos, {})

    def get_inventory(self) -> List[Dict[str, Any]]:
        items = []
        for slot, data in sorted(self._inventory.items()):
            name = data.get("name", "")
            if not name or name == "?":
                continue
            item = {
                "slot": chr(ord('a') + slot) if slot < 26 else chr(ord('A') + slot - 26) if slot < 52 else str(slot),
                "name": name,
                "quantity": data.get("quantity", 1),
            }
            # Mark equipped items
            if slot == self._weapon_index:
                item["equipped"] = "weapon"
            elif slot == self._offhand_index:
                item["equipped"] = "offhand"
            if data.get("useless"):
                item["useless"] = True
            if data.get("inscription"):
                item["inscription"] = data["inscription"]
            items.append(item)
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
            # Threat level: use server value, but override for known dangerous monsters
            KNOWN_DANGEROUS = {
                'sigmund', 'jessica', 'edmund', 'eustachio', 'natasha',
                'robin, the goblin', 'ijyb', 'terence',
                'ogre', 'centaur', 'gnoll sergeant', 'orc priest', 'orc wizard',
            }
            raw_threat = mon.get("threat", 0)
            if name in KNOWN_DANGEROUS and raw_threat < 2:
                raw_threat = 2  # at least "dangerous"
            
            threat_labels = {0: "trivial", 1: "easy", 2: "dangerous", 3: "extremely dangerous"}
            threat_label = threat_labels.get(raw_threat, f"unknown({raw_threat})")
            
            enemies.append({"name": mon.get("name", "unknown"), "x": dx, "y": dy, "direction": direction or "here", "distance": dist, "threat": threat_label, "status": status})
        enemies.sort(key=lambda e: e["distance"])
        return enemies

    # Form names from transformation.h (index = enum value, skipping TAG_MAJOR_VERSION == 34 entries)
    _FORM_NAMES = {
        0: "", 1: "Spider", 2: "Blade Hands", 3: "Statue", 4: "Serpent",
        5: "Dragon", 6: "Death", 7: "Bat", 8: "Pig", 9: "Tree",
        10: "Wisp", 11: "Jelly", 12: "Fungus", 13: "Storm", 14: "Quill",
        15: "Maw", 16: "Flux", 17: "Slaughter", 18: "Vampire",
    }

    def _get_status_text(self) -> str:
        """Format active status effects into a readable string."""
        if not self._status_effects:
            return ""
        lights = [s.get("light", s.get("text", "")) for s in self._status_effects if s.get("light") or s.get("text")]
        return ", ".join(lights) if lights else ""

    def get_stats(self) -> str:
        char_info = f"{self._species} {self._title}".strip() if self._species else "Unknown"
        # Form
        form_name = self._FORM_NAMES.get(self._form, "")
        if form_name:
            char_info += f" ({form_name} Form)"
        hp_str = f"HP: {self._hp}/{self._max_hp}"
        if self._poison_survival and self._poison_survival < self._hp:
            hp_str += f" (→{self._poison_survival} after poison)"
        mp_str = f"MP: {self._mp}/{self._max_mp}"
        # AC/EV/SH with temp modifiers
        def _stat_mod(base, mod, name):
            if mod > 0: return f"{name}: {base} (+{mod})"
            elif mod < 0: return f"{name}: {base} ({mod})"
            return f"{name}: {base}"
        defenses = f"{_stat_mod(self._ac, self._ac_mod, 'AC')} {_stat_mod(self._ev, self._ev_mod, 'EV')} {_stat_mod(self._sh, self._sh_mod, 'SH')}"
        god_str = self._god or "None"
        if self._god:
            piety_stars = "★" * self._piety_rank + "☆" * (6 - self._piety_rank) if self._piety_rank else ""
            if piety_stars:
                god_str += f" [{piety_stars}]"
            if self._penance:
                god_str += " (PENANCE!)"
        contam_str = ""
        if self._contam > 0:
            contam_levels = ["", "glow", "glow+", "GLOW!", "GLOW!!"]
            contam_str = f" | Contam: {contam_levels[min(self._contam, 4)]}"
        noise_str = ""
        if self._adjusted_noise >= 0:
            noise_str = f" | Noise: {self._adjusted_noise}"
        status = self._get_status_text()
        status_str = f" | Status: {status}" if status else ""
        doom_str = f" | Doom: {self._doom}" if self._doom else ""
        lives_str = f" | Lives: {self._lives}" if self._lives else ""
        return (f"Character: {char_info} | {hp_str} | {mp_str} | "
                f"{defenses} | Str: {self._str} Int: {self._int} Dex: {self._dex} | "
                f"XL: {self._xl} ({self._xl_progress}%) | Gold: {self._gold} | Place: {self._place}:{self._depth} | "
                f"God: {god_str}{contam_str}{noise_str}{doom_str}{lives_str}{status_str} | Turn: {self._turn}")

    def get_tactical_readout(self) -> str:
        """Compact tactical readout to replace the large ASCII map."""
        px, py = self._position
        if not self._map_cells:
            return "No map data available"
        
        parts = []
        
        # Position info
        current_cell = self._map_cells.get((px, py), ".")
        terrain_name = {"#": "wall", ".": "floor", "+": "door", "'": "open door", 
                       ">": "downstairs", "<": "upstairs", "~": "water", "≈": "deep water"}.get(current_cell, "unknown")
        parts.append(f"Position: {self._place or 'Unknown'}:{self._depth or '?'} ({terrain_name})")
        
        # Adjacent tiles (8 neighbors)
        adj_tiles = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = px + dx, py + dy
                cell = self._map_cells.get((nx, ny), " ")
                direction = ""
                if dy < 0: direction += "N"
                elif dy > 0: direction += "S"
                if dx > 0: direction += "E"
                elif dx < 0: direction += "W"
                if cell == "#":
                    adj_tiles.append(f"{direction}:wall")
                elif cell == "+":
                    adj_tiles.append(f"{direction}:door")
                elif cell == ">":
                    adj_tiles.append(f"{direction}:down")
                elif cell == "<":
                    adj_tiles.append(f"{direction}:up")
                elif cell == ".":
                    adj_tiles.append(f"{direction}:floor")
                elif cell == " ":
                    adj_tiles.append(f"{direction}:unseen")
        
        parts.append(f"Adjacent: {', '.join(adj_tiles)}")
        
        # Nearby items on ground (within 3 tiles)
        nearby_items = []
        if hasattr(self, '_items'):
            for (ix, iy), item_list in self._items.items():
                if not item_list:
                    continue
                dx, dy = ix - px, iy - py
                dist = max(abs(dx), abs(dy))
                if dist <= 3:
                    direction = ""
                    if dy < 0: direction += "N"
                    elif dy > 0: direction += "S"
                    if dx > 0: direction += "E"
                    elif dx < 0: direction += "W"
                    for item in item_list[:2]:  # Max 2 items per location
                        item_name = item.get("name", "item")
                        nearby_items.append(f"{item_name} ({direction or 'here'}, {dist})")
        
        if nearby_items:
            parts.append(f"Items: {', '.join(nearby_items[:5])}")  # Max 5 items total
        
        # Retreat options (nearest upstairs)
        nearest_up = None
        for (x, y), glyph in self._map_cells.items():
            if glyph == "<":
                dx, dy = x - px, y - py
                dist = max(abs(dx), abs(dy))
                if nearest_up is None or dist < nearest_up[3]:
                    direction = ""
                    if dy < 0: direction += "N"
                    elif dy > 0: direction += "S"
                    if dx > 0: direction += "E"
                    elif dx < 0: direction += "W"
                    nearest_up = (x, y, direction or "here", dist)
        
        if nearest_up:
            parts.append(f"Nearest upstairs: {nearest_up[2]}, {nearest_up[3]} tiles")
        else:
            parts.append("Nearest upstairs: none visible")
        
        return " | ".join(parts)

    def get_state_text(self) -> str:
        parts = ["=== DCSS State ===", self.get_stats(), "", "--- Messages ---"]
        for msg in self.get_messages(5):
            parts.append(f"  {msg}")
        inv = self.get_inventory()
        if inv:
            parts.append("")
            parts.append("--- Inventory ---")
            for item in inv:
                equip_tag = f" (wielded)" if item.get("equipped") == "weapon" else f" (offhand)" if item.get("equipped") == "offhand" else ""
                useless_tag = " [useless]" if item.get("useless") else ""
                inscr_tag = f" {{{item['inscription']}}}" if item.get("inscription") else ""
                parts.append(f"  {item['slot']}) {item['name']}{equip_tag}{useless_tag}{inscr_tag}")
        enemies = self.get_nearby_enemies()
        if enemies:
            parts.append("")
            parts.append("--- Enemies ---")
            for e in enemies:
                status_str = f", {e['status']}" if e.get('status') else ""
                parts.append(f"  {e['name']} ({e['direction']}, dist {e['distance']}, threat {e['threat']}{status_str})")
        # Environmental effects at player position
        overlays = self.get_cell_overlays_at()
        if overlays:
            env_effects = []
            if overlays.get("silenced"): env_effects.append("SILENCED (no spells!)")
            if overlays.get("sanctuary"): env_effects.append("Sanctuary (no combat)")
            if overlays.get("halo"): env_effects.append("Halo")
            if overlays.get("liquefied"): env_effects.append("Liquefied ground")
            if overlays.get("orb_glow"): env_effects.append(f"Orb glow ({overlays['orb_glow']})")
            if overlays.get("disjunct"): env_effects.append("Disjunction")
            if env_effects:
                parts.append("")
                parts.append(f"--- Environment: {', '.join(env_effects)} ---")
        parts.append("")
        parts.append("--- Tactical ---")
        parts.append(self.get_tactical_readout())
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
