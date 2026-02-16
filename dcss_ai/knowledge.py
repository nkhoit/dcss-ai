#!/usr/bin/env python3
"""Knowledge base management for DCSS AI.

Structured knowledge storage and retrieval system that replaces flat learnings.md.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any


class KnowledgeBase:
    """Manages structured knowledge files for the DCSS AI.
    
    Stores knowledge in JSON files organized by category:
    - tactics.json: combat patterns and rules
    - monsters.json: per-monster knowledge
    - items.json: item usage priorities
    - branches.json: branch-specific strategies
    - builds.json: species/background strategies
    - deaths.jsonl: structured death log (append-only)
    - meta.json: run statistics
    """
    
    def __init__(self, knowledge_dir: Path):
        """Initialize knowledge base.
        
        Args:
            knowledge_dir: Path to knowledge directory (created if doesn't exist)
        """
        self.dir = Path(knowledge_dir)
        self.dir.mkdir(exist_ok=True)
        
        # Knowledge file paths
        self.tactics_path = self.dir / "tactics.json"
        self.monsters_path = self.dir / "monsters.json"
        self.items_path = self.dir / "items.json"
        self.branches_path = self.dir / "branches.json"
        self.builds_path = self.dir / "builds.json"
        self.deaths_path = self.dir / "deaths.jsonl"
        self.meta_path = self.dir / "meta.json"
    
    def record_death(self, death_data: dict) -> None:
        """Append structured death to deaths.jsonl.
        
        Args:
            death_data: Death information with keys:
                - timestamp: ISO format timestamp
                - place: location (e.g. "D:3")
                - xl: experience level
                - turn: turn count
                - cause: cause of death
                - hp_max: maximum HP
                - species: character species
                - background: character background
                - god: god worshipped
                - inventory_summary: list of item names
                - nearby_enemies: list of enemy names
                - last_messages: list of recent game messages
        """
        with open(self.deaths_path, 'a') as f:
            f.write(json.dumps(death_data) + '\n')
    
    def get_deaths(self, limit: int = 50) -> List[dict]:
        """Read recent deaths from deaths.jsonl.
        
        Args:
            limit: Maximum number of deaths to return (most recent)
            
        Returns:
            List of death data dicts, newest first
        """
        if not self.deaths_path.exists():
            return []
        
        deaths = []
        with open(self.deaths_path, 'r') as f:
            for line in f:
                if line.strip():
                    deaths.append(json.loads(line))
        
        return deaths[-limit:] if limit else deaths
    
    def get_meta(self) -> dict:
        """Get run statistics.
        
        Returns:
            Dict with keys:
                - total_games: total games played
                - total_deaths: total deaths
                - best_floor: deepest floor reached (e.g. "D:8")
                - best_xl: highest XL reached
                - avg_xl_at_death: average XL at death
                - avg_turns_at_death: average turns at death
                - floors_reached: dict of floor -> count
                - recent_results: list of recent game outcomes
        """
        if not self.meta_path.exists():
            return {
                "total_games": 0,
                "total_deaths": 0,
                "best_floor": "D:1",
                "best_xl": 1,
                "avg_xl_at_death": 0,
                "avg_turns_at_death": 0,
                "floors_reached": {},
                "recent_results": []
            }
        
        with open(self.meta_path, 'r') as f:
            return json.load(f)
    
    def update_meta(self, death_data: dict) -> None:
        """Update meta.json after a death.
        
        Args:
            death_data: Death data from record_death
        """
        meta = self.get_meta()
        
        # Update counts
        meta["total_games"] += 1
        meta["total_deaths"] += 1
        
        # Update best stats
        xl = death_data.get("xl", 0)
        place = death_data.get("place", "D:1")
        
        if xl > meta["best_xl"]:
            meta["best_xl"] = xl
        
        # Parse floor depth for comparison
        def floor_depth(place_str):
            """Convert place string to numeric depth for comparison."""
            try:
                if ':' in place_str:
                    branch, depth = place_str.split(':')
                    return int(depth)
                return 0
            except:
                return 0
        
        if floor_depth(place) > floor_depth(meta["best_floor"]):
            meta["best_floor"] = place
        
        # Update averages
        turns = death_data.get("turn", 0)
        total_xl = meta["avg_xl_at_death"] * (meta["total_deaths"] - 1)
        total_turns = meta["avg_turns_at_death"] * (meta["total_deaths"] - 1)
        
        meta["avg_xl_at_death"] = (total_xl + xl) / meta["total_deaths"]
        meta["avg_turns_at_death"] = (total_turns + turns) / meta["total_deaths"]
        
        # Track floors reached
        if place not in meta["floors_reached"]:
            meta["floors_reached"][place] = 0
        meta["floors_reached"][place] += 1
        
        # Add to recent results (keep last 20)
        result = {
            "place": place,
            "xl": xl,
            "turn": turns,
            "timestamp": death_data.get("timestamp")
        }
        meta["recent_results"].append(result)
        meta["recent_results"] = meta["recent_results"][-20:]
        
        # Save
        with open(self.meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
    
    def get_knowledge_for_context(self, place: str = None, xl: int = None) -> str:
        """Load relevant knowledge as text for system prompt injection.
        
        Filters by current game phase (place/xl) and prioritizes high-confidence entries.
        
        Args:
            place: Current location (e.g. "D:3")
            xl: Current experience level
            
        Returns:
            Compact text suitable for system prompt
        """
        lines = ["## Knowledge from Previous Games\n"]
        
        # Load tactics (high confidence first)
        tactics = self.get_knowledge("tactics")
        if tactics:
            lines.append("### Combat Rules")
            sorted_tactics = sorted(tactics.items(), 
                                   key=lambda x: x[1].get("confidence", 0), 
                                   reverse=True)
            for key, data in sorted_tactics[:8]:  # Top 8 rules
                rule = data.get("rule", "")
                confidence = data.get("confidence", 0)
                if confidence >= 0.7:  # Only show confident rules
                    lines.append(f"- {rule}")
            lines.append("")
        
        # Load relevant monsters based on current depth
        monsters = self.get_knowledge("monsters")
        if monsters and place:
            lines.append("### Known Threats")
            
            # Filter by relevance to current place
            relevant = []
            for name, data in monsters.items():
                min_xl = data.get("min_xl", 0)
                threat = data.get("threat", "medium")
                
                # Show if we're near the expected level
                if xl is None or min_xl <= xl + 3:
                    relevant.append((name, data, threat))
            
            # Sort by threat level
            threat_order = {"high": 0, "medium": 1, "low": 2}
            relevant.sort(key=lambda x: threat_order.get(x[2], 1))
            
            for name, data, threat in relevant[:10]:  # Top 10 threats
                strategy = data.get("strategy", "")
                lines.append(f"- {name}: {strategy}")
            lines.append("")
        
        # Load items (key items only)
        items = self.get_knowledge("items")
        if items:
            lines.append("### Key Items")
            sorted_items = sorted(items.items(),
                                key=lambda x: {"critical": 0, "high": 1, "medium": 2}.get(
                                    x[1].get("priority", "medium"), 2))
            for key, data in sorted_items[:6]:  # Top 6 items
                when = data.get("when", "")
                lines.append(f"- {key}: {when}")
            lines.append("")
        
        # Load branch info if relevant
        branches = self.get_knowledge("branches")
        if branches and place:
            branch_name = place.split(':')[0] if ':' in place else place
            if branch_name in branches:
                lines.append(f"### Current Branch: {branch_name}")
                branch = branches[branch_name]
                notes = branch.get("notes", "")
                lines.append(f"{notes}")
                
                # Show relevant threats for current depth
                threats = branch.get("key_threats_by_depth", {})
                if place and ':' in place:
                    depth = int(place.split(':')[1])
                    for depth_range, threat_list in threats.items():
                        if '-' in depth_range:
                            low, high = map(int, depth_range.split('-'))
                            if low <= depth <= high:
                                lines.append(f"Threats at this depth: {', '.join(threat_list)}")
                                break
                lines.append("")
        
        # Load build info if in early game
        if xl is None or xl < 10:
            builds = self.get_knowledge("builds")
            if builds:
                lines.append("### Build Strategies")
                for build, data in builds.items():
                    strategy = data.get("strategy", "")
                    lines.append(f"- {build}: {strategy}")
                lines.append("")
        
        return "\n".join(lines)
    
    def update_knowledge(self, category: str, key: str, data: dict) -> None:
        """Update a knowledge entry.
        
        Merges with existing data (useful for incrementing counters).
        
        Args:
            category: One of "monsters", "tactics", "items", "branches", "builds"
            key: Knowledge entry key
            data: Data to merge
        """
        category_map = {
            "monsters": self.monsters_path,
            "tactics": self.tactics_path,
            "items": self.items_path,
            "branches": self.branches_path,
            "builds": self.builds_path,
        }
        
        if category not in category_map:
            raise ValueError(f"Unknown category: {category}")
        
        path = category_map[category]
        
        # Load existing
        existing = {}
        if path.exists():
            with open(path, 'r') as f:
                existing = json.load(f)
        
        # Merge
        if key in existing:
            existing[key].update(data)
        else:
            existing[key] = data
        
        # Save
        with open(path, 'w') as f:
            json.dump(existing, f, indent=2)
    
    def get_knowledge(self, category: str) -> dict:
        """Read a knowledge file.
        
        Args:
            category: One of "monsters", "tactics", "items", "branches", "builds"
            
        Returns:
            Dict of knowledge entries, empty dict if file doesn't exist
        """
        category_map = {
            "monsters": self.monsters_path,
            "tactics": self.tactics_path,
            "items": self.items_path,
            "branches": self.branches_path,
            "builds": self.builds_path,
        }
        
        if category not in category_map:
            raise ValueError(f"Unknown category: {category}")
        
        path = category_map[category]
        
        if not path.exists():
            return {}
        
        with open(path, 'r') as f:
            return json.load(f)
