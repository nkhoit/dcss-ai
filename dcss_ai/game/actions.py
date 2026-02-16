"""GameActions mixin: all turn-consuming actions."""
import logging
from typing import List

logger = logging.getLogger(__name__)


class GameActions:
    """Mixin providing all game actions that consume turns."""

    def move(self, direction: str) -> List[str]:
        key_map = {"n": "key_dir_n", "s": "key_dir_s", "e": "key_dir_e", "w": "key_dir_w",
                   "ne": "key_dir_ne", "nw": "key_dir_nw", "se": "key_dir_se", "sw": "key_dir_sw"}
        d = direction.lower()
        if d not in key_map:
            return [f"Invalid direction: {direction}. Use n/s/e/w/ne/nw/se/sw"]
        turn_before = self._turn
        result = self._act(key_map[d])
        if self._turn == turn_before:
            self._consecutive_failed_moves += 1
            n = self._consecutive_failed_moves
            if n >= 5:
                result.append(f"[You've failed to move {n} times in a row. Something is clearly wrong with your approach. Stop and reconsider — what other tools do you have for navigation? If this is a recurring problem, write_learning() about it.]")
            elif n >= 3:
                result.append(f"[{n} consecutive failed moves. There's a wall or obstacle to the {direction}. Think about what other navigation tools are available.]")
            else:
                result.append(f"[Nothing happened — there's a wall or obstacle to the {direction}.]")
        else:
            self._consecutive_failed_moves = 0
        return result

    def attack(self, direction: str) -> List[str]:
        return self.move(direction)

    def auto_explore(self) -> List[str]:
        turn_before = self._turn
        result = self._act("o")
        if self._turn == turn_before:
            # Check if explore was interrupted by an enemy vs floor being done
            enemies = self.get_nearby_enemies()
            recent = " ".join(result).lower()
            if enemies or "is nearby" in recent or "comes into view" in recent:
                result.append("[Explore interrupted by enemy.]")
            else:
                result.append("[Floor fully explored. Call go_downstairs() to auto-travel to the nearest downstairs and descend.]")
        return result

    def auto_fight(self) -> List[str]:
        enemies = self.get_nearby_enemies()
        if not enemies:
            return ["No enemies in sight. Use auto_explore() to keep moving."]
        return self._act("key_tab")

    def rest(self) -> List[str]:
        # Check for visible enemies first
        enemies = self.get_nearby_enemies()
        if enemies:
            names = [e["name"] for e in enemies[:3]]
            return [f"Can't rest — enemies in sight: {', '.join(names)}. Kill or flee first."]
        return self._act("5")

    def wait_turn(self) -> List[str]:
        return self._act(".")

    def go_upstairs(self) -> List[str]:
        depth_before = self._depth
        place_before = self._place
        result = self._act("<")
        if self._depth >= depth_before and self._place == place_before:
            # Not on stairs — try interlevel travel (G then < at prompt)
            result2 = self._interlevel_travel("<")
            if result2 is not None:
                return result2
            result.append("[Not on stairs. Use get_landmarks() to find stairs, then move() toward them step by step.]")
        return result

    def go_downstairs(self) -> List[str]:
        depth_before = self._depth
        place_before = self._place
        result = self._act(">")
        if self._depth <= depth_before and self._place == place_before:
            # Not on stairs — try interlevel travel (G then > at prompt)
            result2 = self._interlevel_travel(">")
            if result2 is not None:
                return result2
            result.append("[Not on stairs. Use get_landmarks() to find stairs, then move() toward them step by step.]")
        return result

    def _interlevel_travel(self, destination: str) -> list:
        """Use G (interlevel travel) to auto-travel. Returns messages or None if failed."""
        import time
        self._ws.send_key("G")
        time.sleep(0.3)
        msgs = self._ws.recv_messages(timeout=1.0)
        got_prompt = False
        for msg in msgs:
            self._process_msg(msg)
            mt = msg.get("msg")
            mode = msg.get("mode")
            logger.debug(f"interlevel_travel: msg={mt}, mode={mode}")
            if mt == "input_mode" and mode in (7, 0):
                got_prompt = True
            elif mt == "menu":
                # WebTiles may use a menu for the travel prompt
                got_prompt = True
        if got_prompt:
            # Send destination (e.g. ">" for nearest downstairs)
            self._ws.send_key(destination)
            self._ws.send_key("key_enter")
            time.sleep(0.3)
            # Wait for travel to complete or be interrupted
            result = self._act(timeout=15.0)
            return result
        else:
            # No prompt appeared — escape anything leftover
            self._ws.send_key("key_esc")
            time.sleep(0.1)
            self._ws.recv_messages(timeout=0.2)
            return None

    def pickup(self) -> List[str]:
        # Check if there are items at current position
        px, py = self._position
        items_here = self._items.get((px, py), []) if hasattr(self, '_items') else []
        if not items_here:
            return ["Nothing to pick up here."]
        msgs = self._act(",")
        if self._current_menu:
            msgs.append("[A pickup menu opened \u2014 use read_ui() to see items, select_menu_item() to pick specific items, or dismiss() to cancel]")
        return msgs

    def use_ability(self, key: str) -> List[str]:
        return self._act("a", key)

    def cast_spell(self, key: str, direction: str = "") -> List[str]:
        # Stage 1: open spell menu and select spell
        self._ws.send_key("z")
        self._ws.send_key(key)
        import time
        time.sleep(0.15)
        msgs = self._ws.recv_messages(timeout=0.5)
        targeting = False
        for msg in msgs:
            self._process_msg(msg)
            if msg.get("msg") == "input_mode" and msg.get("mode") in (4, 7):
                targeting = True
        if targeting:
            # Stage 2: send direction or auto-target
            if direction:
                dir_key = self._dir_key(direction)
            else:
                dir_key = "."
            result = self._act(dir_key)
            # If spell didn't resolve (e.g. "can't see that place"),
            # we may still be in targeting mode — escape to clean up
            if any("can't see" in m.lower() or "can't reach" in m.lower() for m in result):
                self._ws.send_key("key_esc")
                time.sleep(0.1)
                self._ws.recv_messages(timeout=0.3)  # drain
                result.append("[Spell targeting cancelled — target not visible. Try without direction to auto-target nearest enemy.]")
            return result
        else:
            # Spell was instant or failed — drain remaining
            more_msgs = self._ws.recv_messages(timeout=0.3)
            for msg in more_msgs:
                self._process_msg(msg)
            msg_start = max(0, len(self._messages) - 5)
            return self._messages[msg_start:]

    def _dir_key(self, direction: str) -> str:
        key_map = {"n": "key_dir_n", "s": "key_dir_s", "e": "key_dir_e", "w": "key_dir_w",
                   "ne": "key_dir_ne", "nw": "key_dir_nw", "se": "key_dir_se", "sw": "key_dir_sw"}
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
        if not self._god or self._god.lower() in ("", "none", "no god"):
            return ["You don't worship a god. Find an altar and use it to join a religion."]
        return self._act("p")

    def choose_stat(self, stat: str) -> List[str]:
        stat = stat.upper()
        if stat not in ("S", "I", "D"):
            return ["[ERROR: Invalid stat. Use 'S' (Strength), 'I' (Intelligence), or 'D' (Dexterity).]"]
        if self._pending_prompt != "stat_increase":
            return ["[No stat increase prompt pending.]"]
        self._pending_prompt = None
        return self._act(stat, menu_ok=True)

    def respond(self, action: str) -> List[str]:
        key_map = {"yes": "Y", "no": "N", "escape": "key_esc"}
        key = key_map.get(action.lower(), "key_esc")
        return self._act(key, menu_ok=True)

    def escape(self) -> List[str]:
        return self._act("key_esc", menu_ok=True)

    def send_keys(self, keys: str) -> List[str]:
        return self._act(*list(keys))

    def zap_wand(self, slot: str, direction: str = "") -> List[str]:
        keys = ["V", slot]
        if direction:
            keys.append(self._dir_key(direction))
        return self._act(*keys)

    def evoke(self, slot: str) -> List[str]:
        return self._act("v", slot)

    def throw_item(self, slot: str, direction: str) -> List[str]:
        return self._act("F", slot, self._dir_key(direction))

    def put_on_jewelry(self, slot: str) -> List[str]:
        return self._act("P", slot)

    def remove_jewelry(self, slot: str = "") -> List[str]:
        if slot:
            return self._act("R", slot)
        return self._act("R")

    def take_off_armour(self, slot: str) -> List[str]:
        return self._act("T", slot)

    def examine(self, slot: str) -> List[str]:
        inv = self.get_inventory()
        for item in inv:
            if item.get("slot") == slot:
                return [f"{slot} - {item.get('name', 'unknown')} (qty: {item.get('quantity', 1)})"]
        return [f"No item in slot '{slot}'."]
