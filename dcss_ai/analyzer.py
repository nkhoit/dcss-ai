#!/usr/bin/env python3
"""Post-death analysis for DCSS AI.

Analyzes deaths and updates knowledge base automatically.
"""

from typing import Dict, List
from dcss_ai.knowledge import KnowledgeBase


class DeathAnalyzer:
    """Analyzes deaths and updates knowledge base.
    
    Currently uses simple rule-based analysis. Future versions may use LLM.
    """
    
    def __init__(self, kb: KnowledgeBase):
        """Initialize analyzer with knowledge base.
        
        Args:
            kb: KnowledgeBase instance
        """
        self.kb = kb
    
    def analyze(self, death_data: dict) -> Dict[str, dict]:
        """Analyze a death and return suggested knowledge updates.
        
        Args:
            death_data: Death data from capture_death_data
            
        Returns:
            Dict mapping "category/key" to update data
        """
        suggestions = {}
        
        # Track monsters that killed us
        cause = death_data.get("cause", "")
        enemies = death_data.get("nearby_enemies", [])
        xl = death_data.get("xl", 0)
        place = death_data.get("place", "unknown")
        
        # Update monster knowledge for nearby enemies
        for enemy in enemies:
            enemy_key = enemy.lower().replace(" ", "_")
            
            # Get existing monster data
            existing = self.kb.get_knowledge("monsters").get(enemy_key, {})
            
            # Increment death count
            deaths = existing.get("deaths_caused", 0) + 1
            
            # Update last death info
            suggestions[f"monsters/{enemy_key}"] = {
                "deaths_caused": deaths,
                "last_death_xl": xl,
                "last_death_place": place,
            }
            
            # If this monster isn't documented yet, add basic info
            if not existing:
                suggestions[f"monsters/{enemy_key}"]["threat"] = "medium"
                suggestions[f"monsters/{enemy_key}"]["strategy"] = "Unknown - needs analysis"
                suggestions[f"monsters/{enemy_key}"]["confidence"] = 0.3
        
        return suggestions
    
    def apply(self, death_data: dict) -> None:
        """Analyze and apply updates to knowledge base.
        
        Args:
            death_data: Death data from capture_death_data
        """
        suggestions = self.analyze(death_data)
        
        for key, updates in suggestions.items():
            category, name = key.split("/", 1)
            
            # Get existing data and merge
            existing = self.kb.get_knowledge(category).get(name, {})
            existing.update(updates)
            
            # Save merged data
            self.kb.update_knowledge(category, name, existing)
