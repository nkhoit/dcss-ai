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
            result.append("[Floor fully explored. Call go_downstairs() to auto-travel to the nearest downstairs and descend.]")
        return result

    def auto_fight(self) -> List[str]:
        return self._act("key_tab")

    def rest(self) -> List[str]:
        return self._act("5")

    def wait_turn(self) -> List[str]:
        return self._act(".")

    def go_upstairs(self) -> List[str]:
        return self._act("<")

    def go_downstairs(self) -> List[str]:
        return self._act(">")

    def pickup(self) -> List[str]:
        msgs = self._act(",")
        if self._current_menu:
            msgs.append("[A pickup menu opened \u2014 use read_ui() to see items, select_menu_item() to pick specific items, or dismiss() to cancel]")
        return msgs

    def use_ability(self, key: str) -> List[str]:
        return self._act("a", key)

    def cast_spell(self, key: str, direction: str = "") -> List[str]:
        # Stage 1: open spell menu and select spell
        # This will trigger a targeting prompt (mode 7) for targeted spells
        self._ws.send_key("z")
        self._ws.send_key(key)
        # Brief wait for the server to process
        import time
        time.sleep(0.15)
        # Drain messages to see what happened
        msgs = self._ws.recv_messages(timeout=0.5)
        targeting = False
        for msg in msgs:
            self._process_msg(msg)
            if msg.get("msg") == "input_mode" and msg.get("mode") in (4, 7):
                targeting = True
        if targeting:
            # Stage 2: send direction or confirm
            if direction:
                return self._act(self._dir_key(direction))
            else:
                return self._act(".")
        else:
            # Spell was instant (self-target) or failed - drain remaining
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
