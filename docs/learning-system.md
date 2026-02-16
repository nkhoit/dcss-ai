# Learning System

How dcss-ai improves across games. The core principle: **play during games, learn between them.**

## Architecture

```
Game Run → Death → Structured Capture → Analyzer → Knowledge Base → Next Game
```

The model never writes learnings mid-game. It plays. Learning is a separate process that happens after death, analyzing structured data and updating knowledge files.

## Knowledge Base

All knowledge lives in `knowledge/` as structured JSON files:

| File | Purpose | Example |
|------|---------|---------|
| `tactics.json` | Combat rules and heuristics | "HP below 50% = retreat" |
| `monsters.json` | Per-monster threat data | sigmund: flee if XL<5, has hexes |
| `items.json` | Item usage priorities | heal wounds: use below 30% HP |
| `branches.json` | Branch strategies and threats by depth | D:1-5 threats: adder, gnoll, sigmund |
| `builds.json` | Species/background strategies | MiBe: tab-fight, berserk with escape route |
| `deaths.jsonl` | Append-only structured death log | one JSON object per line |
| `meta.json` | Run statistics and progress tracking | best floor, avg XL, trend |

### Why JSON, not markdown?

- **Queryable**: filter monsters by threat level, items by priority
- **Mergeable**: update a single monster entry without rewriting the file
- **Measurable**: confidence scores, death counts, trends
- **Phase-filterable**: only inject knowledge relevant to current depth

## Knowledge Entry Schema

### Tactics
```json
{
  "corridor_fighting": {
    "rule": "Retreat to corridors when facing 2+ enemies — fight 1v1",
    "confidence": 0.9,
    "deaths_validated": 4
  }
}
```

### Monsters
```json
{
  "sigmund": {
    "threat": "high",
    "strategy": "Flee if XL<5. Has hexes and scythe. Come back later.",
    "weaknesses": [],
    "min_xl": 5,
    "confidence": 0.9,
    "deaths_caused": 2
  }
}
```

### Items
```json
{
  "scroll_of_teleportation": {
    "priority": "high",
    "when": "About to die, surrounded, no escape. Use BEFORE critically low.",
    "keep_minimum": 2,
    "confidence": 0.8
  }
}
```

Confidence scores (0.0–1.0) reflect how validated a piece of knowledge is. More deaths validating a rule = higher confidence. Entries below 0.3 are excluded from injection.

## Death Capture

On death, the driver automatically captures:

```json
{
  "timestamp": "2026-02-15T23:45:00",
  "place": "D:3",
  "xl": 4,
  "turn": 312,
  "hp_max": 28,
  "species": "Minotaur",
  "background": "Berserker",
  "god": "Trog",
  "cause": "Killed by a gnoll",
  "inventory_summary": ["hand axe", "leather armour", "potion of heal wounds"],
  "nearby_enemies": ["gnoll", "gnoll"],
  "last_messages": ["The gnoll hits you!", "You die..."]
}
```

This is appended to `deaths.jsonl` (one line per death, never modified). Meta stats are updated in `meta.json`.

## Post-Death Analyzer

Currently rule-based (`dcss_ai/analyzer.py`). After each death:

1. Identifies the killer from death data
2. Updates monster knowledge (death count, last death XL/place)
3. Updates meta statistics (avg XL, best floor, trend)

### Future: LLM-Powered Analysis

The next evolution is a post-game LLM pass:

```
Death Data + Game Log → Cheap Model (Haiku/Flash) → Knowledge Updates
```

The analyzer would:
- Review the last N actions before death
- Identify the tactical mistake (fought in open? ignored HP? no potions?)
- Write or refine tactics/monster entries with specific reasoning
- Detect patterns across multiple deaths ("died to gnolls 3 times on D:2-3 — need ranged option by then")
- Resolve contradictions in existing knowledge

This is intentionally deferred — the structured data capture is the prerequisite.

## Dynamic Knowledge Injection

Knowledge is injected into the system prompt, but **filtered by game phase**:

- **Place-based**: D:1-5 doesn't get Lair monster knowledge
- **XL-based**: low XL games don't get late-game tactics
- **Confidence-based**: only entries above threshold are injected
- **Priority-based**: high-threat monsters and critical items first

The injected knowledge looks like:

```
## Combat Rules
- HP below 50% = retreat immediately
- Corridor fight when 2+ enemies
- Don't berserk when surrounded

## Known Threats (D:1-5)
- sigmund: FLEE if XL<5, has hexes+scythe
- adder: poison, kill fast

## Key Items
- heal wounds potion: use below 30% HP
- teleport scroll: use before critically low
```

Compact, actionable, relevant. Not a wall of text about every monster in the game.

## Progress Tracking

`meta.json` tracks:
- Total games and deaths
- Best floor and XL reached
- Average XL and turns at death
- Floor distribution (how often we reach each floor)
- Recent trend (last 10 games vs prior 10 — are we improving?)

## What the Model Sees vs What It Doesn't

| Model sees | Model doesn't see |
|---|---|
| Filtered knowledge for current phase | Raw JSON files |
| Tactical rules and monster threats | Death log history |
| Item priorities | Meta statistics |
| Current game state (auto-injected) | Other games' details |

The model's job is to play well using the knowledge provided. It doesn't manage, curate, or even know about the learning system.

## Tools

The model has **no learning tools**. Previously it had `write_learning`, `record_death`, and `record_death_journal` — these are all removed. The notepad tools (`write_note`, `read_notes`, `rip_page`) remain for in-game tactical planning, but that's ephemeral per-game state, not persistent knowledge.
