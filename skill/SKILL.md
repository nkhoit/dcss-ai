# DCSS AI — Skill Reference

You are playing Dungeon Crawl Stone Soup (DCSS) via Python commands in a long-running REPL. Your goal is to retrieve the Orb of Zot from the deepest level of the dungeon and escape alive.

## Memory System

**DCSS is a long game. You will be compacted. Your context will be lost. Write things down.**

### `game_state.md` — Active Game Lifeboat
Update this file every 5-10 turns or after anything significant. Keep it under 30 lines.

Contents:
- Character: species, background, god, XL, key resistances
- Current objective: what you're doing right now
- Floor status: which floors are cleared, where you are
- Threats: known dangerous enemies nearby
- Key inventory: weapon, armour, important consumables
- Open decisions: "should I take stairs or clear rest of floor?"

**After compaction or restart:** Read this file FIRST, then reconnect to the game and call `dcss.get_state_text()` to reorient.

### `learnings.md` — Persistent Knowledge Base
This file has two sections. Keep the whole file under ~100 lines.

**Structure:**
```markdown
# DCSS Learnings

## Core Rules
- [Distilled wisdom — one line per rule, max ~40 lines]

## Recent Deaths
### Death #N — [Character] XL:X — [Cause] on [Floor]
- What happened
- What I should have done
```

**After each death:** Append a new entry to Recent Deaths.

**Every 10 deaths (or when file exceeds ~100 lines):** Synthesize.
1. Read all Recent Deaths entries
2. Extract patterns and promote them to Core Rules (merge with existing, deduplicate)
3. Keep only the last 5 Recent Deaths entries, delete older ones
4. Core Rules should be tight — one line per rule, no fluff

**Core Rules examples:**
- Never melee hydras with bladed weapons — use clubs, spells, or wands
- Don't berserk when surrounded — post-exhaustion = death
- Sigmund below XL:5 = run. Come back later.
- Always carry 2+ teleport scrolls after D:5
- Retreat to corridors when facing 2+ enemies — fight 1v1
- Rest after every fight before exploring further

**Before starting a new game:** Read this file. Core Rules are your accumulated wisdom — follow them.

### File Locations
All memory files go in the skill directory alongside this file:
- `game_state.md` — current game (overwrite each update)
- `learnings.md` — permanent (append only)

---

## Connection & Gameplay

You play through a long-running Python REPL (`exec` with PTY). The REPL holds the WebSocket connection to the DCSS server.

### Starting the REPL
```bash
cd ~/code/dcss-ai && source .venv/bin/activate && python3 -i -c "
from dcss_ai.game import DCSSGame, Direction
dcss = DCSSGame()
dcss.connect('ws://localhost:8080/socket', 'kurobot', 'kurobot123')
print('Connected. Game IDs:', dcss._game_ids)
"
```

### Starting a New Game
```python
dcss.start_game(species_key='b', background_key='f', weapon_key='b')  # MiBe
```

### Reconnecting After Interruption
The DCSS server saves your game. Start a new REPL, connect, and the game loads from the save automatically.

---

## Game API Reference

### Properties (free, no turn cost)
```python
dcss.hp, dcss.max_hp      # Hit points
dcss.mp, dcss.max_mp      # Magic points
dcss.ac, dcss.ev, dcss.sh # Armour class, evasion, shield
dcss.strength, dcss.intelligence, dcss.dexterity
dcss.xl                   # Experience level
dcss.place, dcss.depth    # Current branch and depth
dcss.god                  # Worshipped god (or "")
dcss.gold, dcss.position, dcss.turn, dcss.is_dead
```

### State Queries (free)
```python
dcss.get_messages(n=10)   # Last n game messages
dcss.get_inventory()      # [{slot, name, quantity}, ...]
dcss.get_map(radius=7)    # ASCII map centered on @ (you)
dcss.get_stats()          # One-line stats summary
dcss.get_state_text()     # Full dump: stats + messages + inventory + map
```

### Actions (consume game turns)
```python
# Movement
dcss.move("n")            # n/s/e/w/ne/nw/se/sw
dcss.auto_explore()       # Explore until interrupted
dcss.go_upstairs()        # <
dcss.go_downstairs()      # >

# Combat
dcss.auto_fight()         # Tab — fight nearest
dcss.wait_turn()          # Wait one turn

# Rest
dcss.rest()               # Rest until healed

# Items
dcss.pickup()             # Pick up items
dcss.wield("a")           # Wield weapon by inventory slot
dcss.wear("b")            # Wear armour
dcss.quaff("a")           # Drink potion
dcss.read_scroll("a")     # Read scroll
dcss.drop("a")            # Drop item

# Magic & Abilities
dcss.cast_spell("a", "n") # Cast spell + direction
dcss.use_ability("a")     # God/species ability

# Other
dcss.pray()
dcss.confirm()            # Y
dcss.deny()               # N
dcss.escape()             # Esc
dcss.send_keys("abc")     # Raw keystrokes
```

### Direction Constants
```python
Direction.N, Direction.S, Direction.E, Direction.W
Direction.NE, Direction.NW, Direction.SE, Direction.SW
```

---

## Strategy Guide

### Core Loop
1. `auto_explore()` the current floor
2. Fight enemies — `auto_fight()` for weak ones, tactical play for threats
3. `rest()` after fights when safe
4. Pick up consumables and upgrades
5. Descend when floor is cleared and you're healthy
6. **Update `game_state.md` every 5-10 turns**

### Character Selection
Start with **Minotaur Berserker** (species='b', bg='f', weapon='b'). It's the most forgiving:
- High HP, strong melee, headbutt attacks
- Trog provides Berserk (huge damage burst) and Brother in Arms (summon allies)
- Simple gameplan: hit things, don't die

### Combat Rules
1. **HP < 50%: retreat.** Move to a corridor, rest, come back.
2. **Never fight multiple enemies in open space.** Lure to corridors for 1v1.
3. **Berserk** (`dcss.use_ability("a")`) for tough single enemies when HP is high.
4. **Don't berserk when surrounded** — post-berserk exhaustion = slow + weak.
5. **Tab-fight** only trivial enemies (rats, bats, worms).
6. **Read messages carefully** — they tell you what's hitting you and how hard.

### Resource Management
- Rest after every fight if safe
- Always carry: 2+ heal wounds potions, 2+ teleport scrolls (after D:5)
- Quaff heal wounds at HP < 30% in combat
- Read teleport when fight is unwinnable
- Identify consumables by using them on safe, cleared floors

### When to Descend
- Floor fully explored
- HP/MP full
- No valuable items left
- Not significantly underleveled for the depth

### Known Threats
- **Hydras**: Don't melee with bladed weapons. Use clubs, spells, or wands.
- **Sigmund**: Dangerous early unique. Berserk or skip until XL 5+.
- **Orc packs**: Retreat to corridor. Never fight in the open.
- **Uniques** (named enemies): Check messages, assess before engaging.
- **Jellies/Oozes**: Can corrode equipment. Don't fight in melee if avoidable.
- **Any enemy with !**: Usually dangerous. Caution.

### Dungeon Branches (order to tackle)
1. Dungeon D:1–D:11
2. Lair (enter around D:8–D:11)
3. Dungeon D:12–D:15
4. Orc Mines (2 floors, from around D:9–D:12)
5. Lair branches: Swamp/Snake/Shoals/Spider (pick 2 of 4 for runes)
6. Vaults:1–4
7. Depths:1–5
8. Zot:1–5 (get the Orb, escape)

### Code Patterns

**Standard exploration turn:**
```python
msgs = dcss.auto_explore()
for m in msgs:
    print(m)
if dcss.hp < dcss.max_hp:
    dcss.rest()
print(dcss.get_stats())
```

**Combat with retreat:**
```python
if dcss.hp > dcss.max_hp * 0.5:
    dcss.auto_fight()
else:
    dcss.move("s")  # retreat
    dcss.rest()
```

**Emergency heal:**
```python
inv = dcss.get_inventory()
for item in inv:
    if "curing" in item["name"] or "heal wounds" in item["name"]:
        dcss.quaff(item["slot"])
        break
```

**Check surroundings:**
```python
print(dcss.get_map())
print(dcss.get_stats())
for m in dcss.get_messages(5):
    print(m)
```

---

## Important Notes

- **Write things down.** Every 5-10 turns, update `game_state.md`. After every death, update `learnings.md`. Your memory does not survive compaction — these files do.
- **The game server saves automatically.** If the REPL dies, just reconnect. Your game is safe.
- **Read `learnings.md` before every new game.** Past deaths are your best teacher.
- **DCSS is hard.** Average human winrate is ~1%. Dying is expected. Learn from it.
- **When in doubt, run.** A living coward beats a dead hero.
