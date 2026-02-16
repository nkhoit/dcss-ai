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
        time.sleep(0.5)
        msgs = self._ws.recv_messages(timeout=1.0)
        got_text_prompt = False
        got_menu = False
        for msg in msgs:
            self._process_msg(msg)
            mt = msg.get("msg")
            mode = msg.get("mode")
            text = msg.get("text", "")
            logger.debug(f"interlevel_travel: msg={mt}, mode={mode}, text={text[:80] if text else ''}")
            if mt == "input_mode" and mode == 7:
                got_text_prompt = True
            elif mt == "menu":
                got_menu = True
        
        if got_text_prompt:
            # Text input prompt — send destination character
            logger.debug(f"interlevel_travel: sending destination '{destination}' to text prompt")
            self._ws.send_key(destination)
            self._ws.send_key("key_enter")
            time.sleep(0.5)
            result = self._act(timeout=15.0)
            recent = " ".join(result).lower()
            if "can't go down" in recent or "can't go up" in recent:
                return [f"[Interlevel travel failed — no reachable stairs. Use get_landmarks() to find stairs and move() toward them.]"]
            return result
        elif got_menu:
            # Menu-based travel — try selecting nearest stairs
            logger.debug(f"interlevel_travel: got menu, sending destination '{destination}'")
            self._ws.send_key(destination)
            time.sleep(0.3)
            # Check if menu is still open (might need enter)
            msgs2 = self._ws.recv_messages(timeout=0.5)
            still_menu = False
            for msg in msgs2:
                self._process_msg(msg)
                if msg.get("msg") == "menu":
                    still_menu = True
            if still_menu:
                self._ws.send_key("key_enter")
                time.sleep(0.3)
            result = self._act(timeout=15.0)
            recent = " ".join(result).lower()
            if "can't go down" in recent or "can't go up" in recent:
                return [f"[Interlevel travel failed — no reachable stairs. Use get_landmarks() to find stairs and move() toward them.]"]
            return result
        else:
            # No prompt appeared — escape anything leftover
            logger.debug("interlevel_travel: no prompt detected, escaping")
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

    def auto_play(self, hp_threshold: int = 50, max_actions: int = 50,
                  stop_on_items: bool = True, stop_on_altars: bool = True,
                  auto_descend: bool = False, max_enemies: int = 3) -> str:
        max_actions = min(max_actions, 100)  # Hard cap
        hp_threshold = max(hp_threshold, 30)  # Don't let model set suicidal thresholds
        max_enemies = max(max_enemies, 2)  # At least stop at 2 non-trivial
        """Autonomous play loop: explore, fight trivial enemies, rest, repeat.
        
        Returns a structured report of what happened plus the stop reason.
        Fine-grained tools remain available for complex decisions.
        """
        import time as _time
        
        # Dismiss any open menus/popups first
        if self._current_menu or self._current_popup:
            self.dismiss()
        
        actions = 0
        xl_start = self._xl
        floor_logs = {}  # place -> list of events
        current_floor = f"{self._place}:{self._depth}" if self._place else "unknown"
        floor_logs[current_floor] = []
        kills = []
        pickups = []
        stop_reason = "action limit reached"
        fight_actions_without_kill = 0
        no_progress_count = 0
        
        def log(event: str):
            floor = f"{self._place}:{self._depth}" if self._place else "unknown"
            if floor not in floor_logs:
                floor_logs[floor] = []
            floor_logs[floor].append(event)
        
        def check_hp() -> bool:
            """Returns True if HP is below threshold."""
            if self._max_hp <= 0:
                return False
            return (self._hp / self._max_hp * 100) < hp_threshold
        
        def check_dangerous_enemies() -> list:
            """Returns list of dangerous+ enemies if any."""
            enemies = self.get_nearby_enemies()
            dangerous = []
            for e in enemies:
                threat = e.get("threat", "trivial")
                if threat in ("dangerous", "extremely dangerous"):
                    dangerous.append(e)
            return dangerous
        
        def check_status_effects() -> list:
            """Returns list of bad status effects."""
            BAD_STATUSES = {"Conf", "Para", "Petr", "Slow", "Berserk", "Mesm"}
            if not hasattr(self, '_status') or not self._status:
                return []
            return [s for s in self._status if s in BAD_STATUSES]
        
        def check_messages_for_events(msgs: list) -> str | None:
            """Scan messages for notable events. Returns stop reason or None."""
            text = " ".join(msgs).lower()
            
            # Altar detection
            if stop_on_altars and "altar of" in text:
                altar = ""
                for m in msgs:
                    if "altar of" in m.lower():
                        altar = m.strip()
                        break
                return f"found altar: {altar}"
            
            # Equipment item pickup (weapons, armour, jewellery, staves)
            if stop_on_items:
                EQUIPMENT_WORDS = {"sword", "axe", "mace", "whip", "staff", "dagger",
                                   "scythe", "halberd", "glaive", "bardiche", "bow",
                                   "crossbow", "sling", "mail", "robe", "armour", "armor",
                                   "shield", "buckler", "helmet", "hat", "cloak", "gloves",
                                   "boots", "barding", "ring", "amulet", "artefact",
                                   "artifact", "branded", "runed", "glowing", "enchanted"}
                for m in msgs:
                    ml = m.lower()
                    if any(w in ml for w in EQUIPMENT_WORDS):
                        # Check it's a pickup, not combat
                        if any(p in ml for p in (" - ", "you now have", "pick up")):
                            return f"picked up equipment: {m.strip()}"
            
            return None
        
        while actions < max_actions:
            # --- Pre-action checks ---
            turn_at_loop_start = self._turn
            
            # Check for no-progress loops (e.g. unreachable enemies)
            if actions > 0 and self._turn == getattr(self, '_last_auto_play_turn', -1):
                no_progress_count += 1
                if no_progress_count >= 5:
                    stop_reason = "no progress (turn not advancing)"
                    break
            else:
                no_progress_count = 0
            self._last_auto_play_turn = self._turn
            
            # Check for dangerous enemies
            dangerous = check_dangerous_enemies()
            if dangerous:
                names = [f"{e['name']} ({e['direction']}, dist {e['distance']})" for e in dangerous]
                stop_reason = f"dangerous enemy spotted: {', '.join(names)}"
                break
            
            # Check HP
            if check_hp():
                hp_pct = int(self._hp / self._max_hp * 100) if self._max_hp > 0 else 0
                stop_reason = f"HP low ({self._hp}/{self._max_hp}, {hp_pct}%)"
                break
            
            # Check status effects
            bad_status = check_status_effects()
            if bad_status:
                stop_reason = f"status effect: {', '.join(bad_status)}"
                break
            
            # Check for level up
            if self._xl > xl_start:
                log(f"Leveled up: XL {xl_start} → {self._xl}")
                stop_reason = f"leveled up to XL {self._xl}"
                break
            
            # --- Try to explore ---
            enemies = self.get_nearby_enemies()
            
            if enemies:
                # Enemies present — fight if trivial/easy, otherwise stop
                for e in enemies:
                    threat = e.get("threat", "trivial")
                    if threat in ("dangerous", "extremely dangerous"):
                        stop_reason = f"dangerous enemy: {e['name']} ({e['direction']}, dist {e['distance']})"
                        break
                else:
                    # All enemies are trivial/easy — auto fight
                    turn_before_fight = self._turn
                    result = self.auto_fight()
                    actions += 1
                    
                    # If turn didn't advance, enemy is unreachable (behind wall etc)
                    if self._turn == turn_before_fight:
                        # Skip fighting, try exploring instead
                        fight_actions_without_kill = 0
                        turn_before = self._turn
                        result = self.auto_explore()
                        actions += 1
                        if "Explore interrupted" in " ".join(result):
                            continue
                        if "Floor fully explored" in " ".join(result) or turn_before == self._turn:
                            stop_reason = "floor explored (unreachable enemies remain)"
                            break
                        continue
                    
                    fight_actions_without_kill += 1
                    text = " ".join(result)
                    
                    # Check for kills in the messages
                    got_kill = False
                    for m in result:
                        if "you kill" in m.lower() or "you destroy" in m.lower():
                            got_kill = True
                            # Extract monster name
                            for part in m.split("!"):
                                pl = part.lower().strip()
                                if pl.startswith("you kill ") or pl.startswith("you destroy "):
                                    name = pl.split("the ", 1)[-1].rstrip(".!") if "the " in pl else pl.split(" ", 2)[-1].rstrip(".!")
                                    kills.append(name)
                                    log(f"Killed {name}")
                    
                    if got_kill:
                        fight_actions_without_kill = 0
                    elif fight_actions_without_kill >= 10:
                        enemies_now = self.get_nearby_enemies()
                        non_trivial = [e for e in enemies_now if e.get("threat") not in ("trivial", "easy")]
                        if non_trivial:
                            names = [e['name'] for e in enemies_now[:3]]
                            stop_reason = f"prolonged fight without kills ({fight_actions_without_kill} actions): {', '.join(names)}"
                            break
                        # Trivial enemies — keep going, reset counter
                        fight_actions_without_kill = 0
                    
                    # Check if we died
                    if self._is_dead:
                        stop_reason = "you died"
                        break
                    
                    # Check if HP dropped below threshold during fight
                    if check_hp():
                        hp_pct = int(self._hp / self._max_hp * 100) if self._max_hp > 0 else 0
                        stop_reason = f"HP low after combat ({self._hp}/{self._max_hp}, {hp_pct}%)"
                        break
                    
                    # Check for multiple enemies — only stop if any are non-trivial
                    remaining = self.get_nearby_enemies()
                    non_trivial = [e for e in remaining if e.get("threat") not in ("trivial", "easy")]
                    if len(remaining) >= max_enemies and non_trivial:
                        names = [e['name'] for e in remaining[:5]]
                        stop_reason = f"multiple enemies ({len(remaining)}): {', '.join(names)}"
                        break
                    
                    continue
                
                # If we broke out of the for-else (dangerous enemy), break outer loop
                if "dangerous" in stop_reason:
                    break
            
            else:
                # No enemies — try exploring
                fight_actions_without_kill = 0
                turn_before = self._turn
                result = self.auto_explore()
                actions += 1
                text = " ".join(result)
                
                # Check for pickups in messages
                for m in result:
                    ml = m.lower()
                    if " - " in m and any(c.isalpha() for c in m[:3]):
                        # Likely an item pickup (e.g. "d - a potion of heal wounds")
                        pickups.append(m.strip())
                    elif "gold piece" in ml:
                        pickups.append(m.strip())
                
                # Check for notable events in messages
                event = check_messages_for_events(result)
                if event:
                    log(event)
                    stop_reason = event
                    break
                
                # Check if we died
                if self._is_dead:
                    stop_reason = "you died"
                    break
                
                # Explore interrupted by enemy — loop will handle on next iteration
                if "Explore interrupted" in text:
                    continue
                
                # Floor fully explored
                if "Floor fully explored" in text:
                    if auto_descend:
                        # Try to descend
                        log("Floor fully explored, descending")
                        depth_before = self._depth
                        place_before = self._place
                        desc_result = self.go_downstairs()
                        actions += 1
                        desc_text = " ".join(desc_result)
                        
                        if self._depth > depth_before or self._place != place_before:
                            new_floor = f"{self._place}:{self._depth}"
                            log(f"Descended to {new_floor}")
                            current_floor = new_floor
                            
                            # Rest to full before exploring new floor
                            if self._hp < self._max_hp:
                                rest_result = self.rest()
                                actions += 1
                            continue
                        else:
                            stop_reason = "floor explored but couldn't reach stairs"
                            break
                    else:
                        stop_reason = "floor fully explored"
                        break
                
                # Explore didn't advance turn — might be stuck (menu open, etc)
                if turn_before == self._turn:
                    no_progress_count += 1
                    # Will be caught by the no_progress check at top of loop
                    continue
                
                # Rest if HP not full and no enemies
                if self._hp < self._max_hp and not self.get_nearby_enemies():
                    rest_result = self.rest()
                    actions += 1
                    if self._is_dead:
                        stop_reason = "you died"
                        break
        
        # --- Build report ---
        report_lines = []
        
        # Header
        floors_visited = list(floor_logs.keys())
        if len(floors_visited) > 1:
            report_lines.append(f"=== Auto-Play Report ({actions} actions, {floors_visited[0]} → {floors_visited[-1]}) ===")
        else:
            report_lines.append(f"=== Auto-Play Report ({actions} actions, {floors_visited[0]}) ===")
        report_lines.append("")
        
        # Per-floor breakdown
        for floor, events in floor_logs.items():
            if events:
                report_lines.append(f"{floor}:")
                for event in events:
                    report_lines.append(f"  {event}")
                report_lines.append("")
        
        # Summary
        if kills:
            # Deduplicate with counts
            from collections import Counter
            kill_counts = Counter(kills)
            kill_strs = []
            for name, count in kill_counts.most_common():
                kill_strs.append(f"{count}x {name}" if count > 1 else name)
            report_lines.append(f"Kills: {', '.join(kill_strs)}")
        
        if pickups:
            # Limit to 10 most recent
            shown = pickups[-10:]
            report_lines.append(f"Picked up: {'; '.join(shown)}")
        
        if self._xl > xl_start:
            report_lines.append(f"Leveled: XL {xl_start} → {self._xl}")
        
        report_lines.append("")
        report_lines.append(f"Stopped: {stop_reason}")
        
        return "\n".join(report_lines)
