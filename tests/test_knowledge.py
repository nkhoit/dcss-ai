"""Tests for knowledge base and death analyzer."""

import json
import tempfile
from pathlib import Path
from dcss_ai.knowledge import KnowledgeBase
from dcss_ai.analyzer import DeathAnalyzer


class TestKnowledgeBase:
    """Test KnowledgeBase class operations."""

    def test_init_creates_directory(self):
        """Test that KnowledgeBase creates directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = Path(tmpdir) / "knowledge"
            kb = KnowledgeBase(kb_dir)
            assert kb_dir.exists()
            assert kb_dir.is_dir()

    def test_record_death(self):
        """Test recording deaths to deaths.jsonl."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            death_data = {
                "timestamp": "2024-02-15T12:00:00",
                "place": "D:3",
                "xl": 3,
                "turn": 1234,
                "cause": "orc warrior",
                "hp_max": 30,
                "species": "Minotaur",
                "background": "Berserker",
                "god": "Trog",
                "inventory_summary": ["hand axe", "leather armour"],
                "nearby_enemies": ["orc warrior", "orc priest"],
                "last_messages": ["The orc warrior hits you!", "You die..."]
            }
            
            kb.record_death(death_data)
            
            # Verify file exists and contains data
            assert kb.games_path.exists()
            with open(kb.games_path) as f:
                line = f.readline()
                loaded = json.loads(line)
                assert loaded["place"] == "D:3"
                assert loaded["xl"] == 3

    def test_get_deaths(self):
        """Test retrieving deaths from deaths.jsonl."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            # Record multiple deaths
            for i in range(5):
                death_data = {
                    "timestamp": f"2024-02-15T12:00:{i:02d}",
                    "place": f"D:{i+1}",
                    "xl": i + 1,
                    "turn": 100 * (i + 1),
                    "cause": "test",
                    "hp_max": 20,
                    "species": "Test",
                    "background": "Test",
                    "god": "none",
                    "inventory_summary": [],
                    "nearby_enemies": [],
                    "last_messages": []
                }
                kb.record_death(death_data)
            
            # Get all deaths
            deaths = kb.get_deaths()
            assert len(deaths) == 5
            assert deaths[-1]["place"] == "D:5"
            
            # Get limited deaths
            deaths = kb.get_deaths(limit=3)
            assert len(deaths) == 3
            assert deaths[-1]["place"] == "D:5"

    def test_get_deaths_empty(self):
        """Test get_deaths on empty knowledge base."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            deaths = kb.get_deaths()
            assert deaths == []

    def test_get_meta_empty(self):
        """Test get_meta on empty knowledge base."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            meta = kb.get_meta()
            assert meta["total_games"] == 0
            assert meta["total_deaths"] == 0
            assert meta["best_floor"] == "D:1"

    def test_update_meta(self):
        """Test updating meta.json with death data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            death_data = {
                "timestamp": "2024-02-15T12:00:00",
                "place": "D:5",
                "xl": 5,
                "turn": 2000,
                "cause": "test",
                "hp_max": 50,
                "species": "Minotaur",
                "background": "Berserker",
                "god": "Trog",
                "inventory_summary": [],
                "nearby_enemies": [],
                "last_messages": []
            }
            
            kb.update_meta(death_data)
            
            meta = kb.get_meta()
            assert meta["total_games"] == 1
            assert meta["total_deaths"] == 1
            assert meta["best_floor"] == "D:5"
            assert meta["best_xl"] == 5
            assert meta["avg_xl_at_death"] == 5
            assert meta["avg_turns_at_death"] == 2000
            assert "D:5" in meta["floors_reached"]

    def test_update_meta_multiple_deaths(self):
        """Test meta statistics over multiple deaths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            # Record 3 deaths
            for i in range(3):
                death_data = {
                    "timestamp": f"2024-02-15T12:00:{i:02d}",
                    "place": f"D:{i+3}",
                    "xl": (i + 1) * 2,
                    "turn": 1000 * (i + 1),
                    "cause": "test",
                    "hp_max": 30,
                    "species": "Test",
                    "background": "Test",
                    "god": "none",
                    "inventory_summary": [],
                    "nearby_enemies": [],
                    "last_messages": []
                }
                kb.update_meta(death_data)
            
            meta = kb.get_meta()
            assert meta["total_games"] == 3
            assert meta["total_deaths"] == 3
            assert meta["best_floor"] == "D:5"
            assert meta["best_xl"] == 6
            assert meta["avg_xl_at_death"] == (2 + 4 + 6) / 3
            assert meta["avg_turns_at_death"] == (1000 + 2000 + 3000) / 3

    def test_get_knowledge(self):
        """Test reading knowledge files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            # Create a tactics file
            tactics = {
                "test_rule": {
                    "rule": "Test rule",
                    "confidence": 0.8
                }
            }
            with open(kb.tactics_path, 'w') as f:
                json.dump(tactics, f)
            
            # Read it back
            loaded = kb.get_knowledge("tactics")
            assert "test_rule" in loaded
            assert loaded["test_rule"]["rule"] == "Test rule"

    def test_get_knowledge_empty(self):
        """Test reading non-existent knowledge file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            loaded = kb.get_knowledge("tactics")
            assert loaded == {}

    def test_update_knowledge(self):
        """Test updating knowledge entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            # Add a monster
            kb.update_knowledge("monsters", "goblin", {
                "threat": "low",
                "strategy": "Easy to kill",
                "confidence": 0.5
            })
            
            # Verify it was saved
            monsters = kb.get_knowledge("monsters")
            assert "goblin" in monsters
            assert monsters["goblin"]["threat"] == "low"
            
            # Update it
            kb.update_knowledge("monsters", "goblin", {
                "deaths_caused": 1
            })
            
            # Verify merge
            monsters = kb.get_knowledge("monsters")
            assert monsters["goblin"]["threat"] == "low"  # old data preserved
            assert monsters["goblin"]["deaths_caused"] == 1  # new data added

    def test_get_knowledge_for_context(self):
        """Test filtered knowledge retrieval for context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            
            # Create some test data
            tactics = {
                "rule1": {"rule": "Test rule 1", "confidence": 0.9},
                "rule2": {"rule": "Test rule 2", "confidence": 0.5}
            }
            with open(kb.tactics_path, 'w') as f:
                json.dump(tactics, f)
            
            monsters = {
                "goblin": {
                    "threat": "low",
                    "strategy": "Easy",
                    "min_xl": 1,
                    "confidence": 0.8
                }
            }
            with open(kb.monsters_path, 'w') as f:
                json.dump(monsters, f)
            
            # Get context
            context = kb.get_knowledge_for_context(place="D:1", xl=1)
            
            # Should include high-confidence tactics
            assert "Test rule 1" in context
            # Should include relevant monsters
            assert "goblin" in context


class TestDeathAnalyzer:
    """Test DeathAnalyzer class."""

    def test_analyze_rules(self):
        """Test rule-based death analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            analyzer = DeathAnalyzer(kb)
            
            death_data = {
                "timestamp": "2024-02-15T12:00:00",
                "place": "D:3",
                "xl": 3,
                "turn": 1234,
                "cause": "orc warrior hit you",
                "hp_max": 30,
                "species": "Minotaur",
                "background": "Berserker",
                "god": "Trog",
                "inventory_summary": ["hand axe"],
                "nearby_enemies": ["orc warrior", "orc priest"],
                "last_messages": ["The orc warrior hits you!"]
            }
            
            suggestions = analyzer.analyze_rules(death_data)
            
            # Should suggest updates for nearby enemies
            assert "monsters/orc_warrior" in suggestions
            assert "monsters/orc_priest" in suggestions
            assert suggestions["monsters/orc_warrior"]["deaths_caused"] == 1

    def test_apply_rules(self):
        """Test applying rule-based analysis to knowledge base."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            analyzer = DeathAnalyzer(kb)
            
            death_data = {
                "timestamp": "2024-02-15T12:00:00",
                "place": "D:3",
                "xl": 3,
                "turn": 1234,
                "cause": "orc warrior",
                "hp_max": 30,
                "species": "Minotaur",
                "background": "Berserker",
                "god": "Trog",
                "inventory_summary": [],
                "nearby_enemies": ["orc warrior"],
                "last_messages": []
            }
            
            # Test rule-based path directly (no provider = no LLM call)
            analyzer._apply_rules(death_data)
            
            # Verify knowledge was updated
            monsters = kb.get_knowledge("monsters")
            assert "orc_warrior" in monsters
            assert monsters["orc_warrior"]["deaths_caused"] == 1
            assert monsters["orc_warrior"]["last_death_xl"] == 3
            assert monsters["orc_warrior"]["last_death_place"] == "D:3"

    def test_apply_increments_death_count(self):
        """Test that multiple deaths increment the count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(Path(tmpdir))
            analyzer = DeathAnalyzer(kb)
            
            # Seed with existing data
            kb.update_knowledge("monsters", "goblin", {
                "threat": "low",
                "deaths_caused": 2
            })
            
            death_data = {
                "timestamp": "2024-02-15T12:00:00",
                "place": "D:1",
                "xl": 1,
                "turn": 100,
                "cause": "goblin",
                "hp_max": 20,
                "species": "Human",
                "background": "Fighter",
                "god": "none",
                "inventory_summary": [],
                "nearby_enemies": ["goblin"],
                "last_messages": []
            }
            
            analyzer._apply_rules(death_data)
            
            # Verify count incremented
            monsters = kb.get_knowledge("monsters")
            assert monsters["goblin"]["deaths_caused"] == 3
            assert monsters["goblin"]["threat"] == "low"  # preserved
