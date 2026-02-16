#!/usr/bin/env python3
"""Post-death analysis for DCSS AI.

Uses an LLM to analyze deaths and extract learnings for the knowledge base.
Falls back to rule-based analysis if LLM is unavailable.
"""

import json
import logging
from typing import Dict, List, Optional

from dcss_ai.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)

ANALYZER_SYSTEM_PROMPT = """\
You are an autonomous DCSS death analyzer. You receive a death report and output \
a JSON analysis. You are NOT in a conversation — do NOT ask questions, do NOT \
offer options, do NOT wait for input. Just analyze and output JSON.

Given:
- Death data (where, when, how, what was nearby)
- Recent game messages (the last actions before death)
- The player's notepad (what they were thinking/planning)
- Existing learnings (so you don't duplicate)

Respond with ONLY a JSON object (no markdown fences, no commentary):
{
  "summary": "One-sentence summary of what happened",
  "what_went_wrong": "2-3 sentences explaining the root cause",
  "learnings": [
    {
      "tier": "hard_rule" | "heuristic" | "note",
      "category": "monsters" | "tactics" | "builds" | "items" | "branches",
      "key": "snake_case_identifier",
      "text": "The learning itself — concise, actionable",
      "situation_tags": ["optional", "context", "tags"]
    }
  ]
}

Rules:
- Extract 1-3 learnings per death. Quality over quantity.
- "hard_rule" = absolute (e.g. "Never fight hydras without a non-edged weapon")
- "heuristic" = strong guideline with exceptions (e.g. "Retreat from orc priests when below 50% HP")
- "note" = observation that needs more data (e.g. "Centaurs seem dangerous on D:4")
- Don't duplicate existing learnings. If one exists, you can upgrade its tier or refine it.
- Be specific: name the monster, the floor, the situation. Vague advice is useless.
- Focus on what the player could have done differently, not bad luck.
- Output ONLY the JSON object. Nothing else. No questions. No commentary.\
"""


def _format_death_context(
    death_data: dict,
    recent_messages: List[str],
    notepad: str,
    existing_learnings: str,
) -> str:
    """Format death context into a prompt for the analyzer LLM."""
    parts = []

    parts.append("## Death Report")
    parts.append(f"- Place: {death_data.get('place', 'unknown')}")
    parts.append(f"- XL: {death_data.get('xl', '?')}")
    parts.append(f"- Turn: {death_data.get('turn', '?')}")
    parts.append(f"- HP Max: {death_data.get('hp_max', '?')}")
    parts.append(f"- Species/Background: {death_data.get('species', '?')} {death_data.get('background', '?')}")
    parts.append(f"- God: {death_data.get('god', 'none')}")
    parts.append(f"- Cause: {death_data.get('cause', 'unknown')}")

    enemies = death_data.get("nearby_enemies", [])
    if enemies:
        parts.append(f"- Nearby enemies: {', '.join(enemies)}")

    inv = death_data.get("inventory_summary", [])
    if inv:
        parts.append(f"- Key inventory: {', '.join(inv[:10])}")

    if recent_messages:
        parts.append("\n## Last Game Messages")
        for msg in recent_messages[-50:]:
            parts.append(f"  {msg}")

    if notepad:
        parts.append(f"\n## Player's Notepad\n{notepad}")

    if existing_learnings:
        parts.append(f"\n## Existing Learnings (don't duplicate)\n{existing_learnings}")

    parts.append("""
Respond with ONLY this JSON structure (no markdown, no commentary, no questions):
{"summary": "one sentence", "what_went_wrong": "2-3 sentences", "learnings": [{"tier": "hard_rule|heuristic|note", "category": "monsters|tactics|builds|items|branches", "key": "snake_case_id", "text": "concise actionable learning"}]}""")

    return "\n".join(parts)


def _parse_analyzer_response(response: str) -> Optional[dict]:
    """Parse the analyzer LLM response into structured data."""
    text = response.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object from mixed content
    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse analyzer response as JSON: {text[:200]}")
    return None


class DeathAnalyzer:
    """Analyzes deaths and updates knowledge base.

    Uses LLM for analysis when a provider is available, falls back to
    rule-based analysis otherwise.
    """

    def __init__(self, kb: KnowledgeBase, provider=None, model: str = "claude-sonnet-4.5"):
        """Initialize analyzer.

        Args:
            kb: KnowledgeBase instance
            provider: LLMProvider instance (optional, enables LLM analysis)
            model: Model to use for analysis (default: claude-haiku-4.5)
        """
        self.kb = kb
        self.provider = provider
        self.model = model

    async def analyze_with_llm(
        self,
        death_data: dict,
        recent_messages: Optional[List[str]] = None,
        notepad: str = "",
    ) -> Optional[dict]:
        """Run LLM-based death analysis.

        Args:
            death_data: Death data from capture_death_data
            recent_messages: Last 30-50 game messages before death
            notepad: Current notepad contents

        Returns:
            Parsed analysis dict or None if LLM unavailable/failed
        """
        if not self.provider:
            return None

        # Get existing learnings to avoid duplication
        existing = self.kb.get_knowledge_for_context(
            place=death_data.get("place"),
            xl=death_data.get("xl"),
        )

        context = _format_death_context(
            death_data,
            recent_messages or death_data.get("last_messages", []),
            notepad,
            existing,
        )

        try:
            # Create a one-shot session with no tools
            session = await self.provider.create_session(
                ANALYZER_SYSTEM_PROMPT, [], self.model
            )
            result = await session.send(context, timeout=30)

            if result.text:
                return _parse_analyzer_response(result.text)
            else:
                logger.warning("Analyzer LLM returned no text")
                return None
        except Exception as e:
            logger.warning(f"LLM death analysis failed: {e}")
            return None

    def analyze_rules(self, death_data: dict) -> Dict[str, dict]:
        """Rule-based analysis (fallback).

        Args:
            death_data: Death data from capture_death_data

        Returns:
            Dict mapping "category/key" to update data
        """
        suggestions = {}

        cause = death_data.get("cause", "")
        enemies = death_data.get("nearby_enemies", [])
        xl = death_data.get("xl", 0)
        place = death_data.get("place", "unknown")

        for enemy in enemies:
            enemy_key = enemy.lower().replace(" ", "_")
            existing = self.kb.get_knowledge("monsters").get(enemy_key, {})
            deaths = existing.get("deaths_caused", 0) + 1

            suggestions[f"monsters/{enemy_key}"] = {
                "deaths_caused": deaths,
                "last_death_xl": xl,
                "last_death_place": place,
            }

            if not existing:
                suggestions[f"monsters/{enemy_key}"]["threat"] = "medium"
                suggestions[f"monsters/{enemy_key}"]["strategy"] = "Unknown - needs analysis"
                suggestions[f"monsters/{enemy_key}"]["confidence"] = 0.3

        return suggestions

    def _apply_rules(self, death_data: dict) -> None:
        """Apply rule-based analysis to knowledge base."""
        suggestions = self.analyze_rules(death_data)
        for key, updates in suggestions.items():
            category, name = key.split("/", 1)
            existing = self.kb.get_knowledge(category).get(name, {})
            existing.update(updates)
            self.kb.update_knowledge(category, name, existing)

    def _apply_llm_learnings(self, analysis: dict) -> None:
        """Apply LLM-extracted learnings to knowledge base."""
        learnings = analysis.get("learnings", [])
        if not learnings:
            # Log what keys we got so we can debug schema mismatches
            logger.info(f"Analyzer response keys: {list(analysis.keys())} (no 'learnings' key found)")
            return
        for learning in learnings:
            category = learning.get("category", "tactics")
            key = learning.get("key", "unknown")
            tier = learning.get("tier", "note")
            text = learning.get("text", "")
            tags = learning.get("situation_tags", [])

            if not text:
                continue

            existing = self.kb.get_knowledge(category).get(key, {})
            existing.update({
                "text": text,
                "tier": tier,
                "situation_tags": tags,
                "confidence": {"hard_rule": 0.9, "heuristic": 0.6, "note": 0.3}.get(tier, 0.3),
            })
            self.kb.update_knowledge(category, key, existing)

        # Log the analysis summary
        summary = analysis.get("summary", "")
        what_went_wrong = analysis.get("what_went_wrong", "")
        if summary:
            logger.info(f"Death analysis: {summary}")
        if what_went_wrong:
            logger.info(f"Root cause: {what_went_wrong}")
        if learnings:
            logger.info(f"Extracted {len(learnings)} learnings: {[l.get('key') for l in learnings]}")

    async def apply(
        self,
        death_data: dict,
        recent_messages: Optional[List[str]] = None,
        notepad: str = "",
    ) -> None:
        """Analyze death and apply updates to knowledge base.

        Runs LLM analysis if provider is available, always runs rule-based
        analysis as well.

        Args:
            death_data: Death data from capture_death_data
            recent_messages: Last 30-50 game messages before death
            notepad: Current notepad contents
        """
        # Always run rule-based analysis
        self._apply_rules(death_data)

        # Run LLM analysis if available
        analysis = await self.analyze_with_llm(death_data, recent_messages, notepad)
        if analysis:
            self._apply_llm_learnings(analysis)
