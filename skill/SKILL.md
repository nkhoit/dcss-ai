# DCSS AI — Skill Reference

You are playing Dungeon Crawl Stone Soup (DCSS) via MCP tools. Your goal is to retrieve the Orb of Zot from the deepest level of the dungeon and escape alive.

## Tools

You have 3 tools:

### `dcss_start_game(species, background, weapon)`
Start a new game. Returns initial state.

### `dcss_state()`
Get current game state: stats, map, messages, inventory.

### `dcss_execute(code)`
Execute Python code against the `dcss` game API. This is your primary tool — write Python to control the game.

## Game API Reference

Available as `dcss` in execute_code:

### Properties (free, no turn cost)
```python
dcss.hp, dcss.max_hp      # Hit points
dcss.mp, dcss.max_mp      # Magic points
dcss.ac, dcss.ev, dcss.sh # Armour class, evasion, shield
dcss.strength, dcss.intelligence, dcss.dexterity
dcss.xl                   # Experience level
dcss.place, dcss.depth    # Current branch and depth
dcss.god                  # Worshipped god (or "")
dcss.gold                 # Gold pieces
dcss.position             # (x, y) tuple
dcss.turn                 # Game turn number
dcss.is_dead              # True if dead
```

### State Queries (free)
```python
dcss.get_messages(n=10)   # Last n game messages (HTML stripped)
dcss.get_inventory()      # [{slot, name, quantity}, ...]
dcss.get_map(radius=7)    # ASCII map centered on player (@)
dcss.get_stats()          # Formatted stats string
dcss.get_state_text()     # Full state dump (stats + messages + map + inventory)
```

### Actions (consume game turns)
```python
# Movement
dcss.move("n")            # Move: n/s/e/w/ne/nw/se/sw
dcss.auto_explore()       # Auto-explore (o key)
dcss.go_upstairs()        # Ascend stairs (<)
dcss.go_downstairs()      # Descend stairs (>)

# Combat
dcss.auto_fight()         # Tab — fight nearest enemy
dcss.wait_turn()          # Wait one turn (.)

# Rest
dcss.rest()               # Long rest until healed (5 key)

# Items
dcss.pickup()             # Pick up items (g)
dcss.wield("a")           # Wield weapon by slot
dcss.wear("b")            # Wear armour by slot
dcss.quaff("a")           # Drink potion by slot
dcss.read_scroll("a")     # Read scroll by slot
dcss.drop("a")            # Drop item by slot

# Magic
dcss.cast_spell("a", "n") # Cast spell with direction
dcss.use_ability("a")     # Use god/species ability

# Other
dcss.pray()               # Pray to god
dcss.confirm()            # Send Y
dcss.deny()               # Send N
dcss.escape()             # Send Escape
dcss.send_keys("abc")     # Raw keystrokes (escape hatch)
```

### Direction Constants
```python
Direction.N, Direction.S, Direction.E, Direction.W
Direction.NE, Direction.NW, Direction.SE, Direction.SW
```

## Strategy Guide

### Core Loop
Your gameplay loop should be:
1. **Explore** the current floor with `dcss.auto_explore()`
2. **Fight** enemies when encountered (auto_fight for weak ones, tactical play for dangerous ones)
3. **Manage resources** — rest when safe, use consumables wisely
4. **Descend** when the floor is cleared

### Character Selection
Strong starting combos for AI play:
- **Minotaur Berserker** (species='b', bg='f', weapon='b') — simple melee, Trog provides rage + allies
- **Gargoyle Fighter** (species='l', bg='a') — tanky, innate resistances
- **Vine Stalker Enchanter** — stealth + hexes, good for careful play

Start with Minotaur Berserker. It's the most forgiving.

### Combat Priorities
1. **Run from dangerous enemies** when HP < 50% — `dcss.move()` away, use corridors
2. **Use Berserk** (Trog ability 'a') for tough fights when HP is healthy
3. **Tab-fight** (auto_fight) for trivial enemies
4. **Never fight multiple enemies in open space** — retreat to corridors for 1v1

### Resource Management
- **Rest after every fight** if safe: `dcss.rest()`
- **Pick up potions and scrolls** — they're crucial for emergencies
- **Quaff heal wounds** when HP is critically low in combat
- **Read teleportation** to escape unwinnable fights
- **Identify by use** — quaff/read unknown consumables on safe floors

### When to Descend
- Floor is fully explored
- HP and MP are full
- No more useful items to find
- You're not significantly underleveled

### Dangerous Situations
- **Hydras**: Don't melee with edged weapons (they grow heads). Use Berserk or wands.
- **Sigmund**: Early unique, hits hard. Berserk him or skip.
- **Orc packs**: Retreat to corridors, fight 1v1.
- **Uniques with ! mark**: Named enemies, usually dangerous. Check messages for who they are.
- **Low HP in open space**: Retreat, don't stand and fight.

### Code Patterns

**Basic exploration loop:**
```python
# Explore, handle what comes up
msgs = dcss.auto_explore()
for msg in msgs:
    print(msg)
if dcss.hp < dcss.max_hp:
    dcss.rest()
```

**Combat with HP check:**
```python
if dcss.hp > dcss.max_hp * 0.5:
    dcss.auto_fight()
else:
    # Retreat south
    dcss.move("s")
    dcss.move("s")
```

**Pickup and equip:**
```python
dcss.pickup()
inv = dcss.get_inventory()
for item in inv:
    print(f"{item['slot']}: {item['name']}")
```

**Use Berserk (Trog ability):**
```python
dcss.use_ability("a")  # Berserk
dcss.auto_fight()
```

### Important Notes
- After each `dcss_execute` call, you'll see updated stats and any game messages
- The map shows `@` as your position
- Game messages tell you what happened — read them carefully
- If you die, the game is over. Start a new one with `dcss_start_game`
- DCSS is hard. Dying is normal. Learn from each death.
- **When in doubt, run.** A living coward beats a dead hero.
