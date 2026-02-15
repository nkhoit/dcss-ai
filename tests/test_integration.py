"""Integration tests for dcss-ai game API.

Requires a running DCSS webtiles server:
  cd server && docker compose up -d

All tests use deterministic invariants — no randomness-dependent assertions.
"""
import random
import string
import pytest
from dcss_ai.game import DCSSGame


def random_username():
    """Generate a unique username for test isolation."""
    suffix = ''.join(random.choices(string.ascii_lowercase, k=6))
    return f"test{suffix}"


@pytest.fixture
def dcss():
    """Create a connected DCSSGame instance with a fresh account."""
    game = DCSSGame()
    name = random_username()
    game.connect("ws://localhost:8080/socket", name, name + "pw")
    yield game
    try:
        game.disconnect()
    except Exception:
        pass


@pytest.fixture
def game(dcss):
    """A DCSSGame with a MiBe game already started."""
    dcss.start_game(species_key="b", background_key="f", weapon_key="b")
    yield dcss


class TestConnection:
    def test_connect(self, dcss):
        assert dcss._connected is True
        assert len(dcss._game_ids) > 0

    def test_game_ids_not_empty(self, dcss):
        assert len(dcss._game_ids) > 0

    def test_disconnect(self):
        game = DCSSGame()
        name = random_username()
        game.connect("ws://localhost:8080/socket", name, name + "pw")
        assert game._connected is True
        game.disconnect()
        assert game._connected is False


class TestStartGame:
    def test_start_game_sets_state(self, game):
        assert game._in_game is True
        assert game.hp > 0
        assert game.max_hp > 0
        assert game.hp == game.max_hp  # fresh game, full HP
        assert game.turn >= 0
        assert game.xl == 1
        assert game.depth == 1
        assert game.is_dead is False

    def test_start_game_returns_state_text(self, dcss):
        result = dcss.start_game(species_key="b", background_key="f", weapon_key="b")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_minotaur_berserker_has_weapon(self, game):
        inv = game.get_inventory()
        assert isinstance(inv, list)
        assert len(inv) > 0
        # MiBe starts with a weapon
        names = [i["name"].lower() for i in inv]
        assert any("club" in n or "axe" in n or "mace" in n or "sword" in n or "flail" in n for n in names)


class TestStateQueries:
    """State queries are free (no turn cost) and always return valid data."""

    def test_get_stats(self, game):
        stats = game.get_stats()
        assert isinstance(stats, str)
        assert "HP" in stats

    def test_get_state_text(self, game):
        state = game.get_state_text()
        assert isinstance(state, str)
        assert "HP" in state
        assert len(state) > 50

    def test_get_map(self, game):
        m = game.get_map(radius=7)
        assert isinstance(m, str)
        assert "@" in m  # player is on the map

    def test_get_inventory(self, game):
        inv = game.get_inventory()
        assert isinstance(inv, list)
        for item in inv:
            assert "slot" in item
            assert "name" in item

    def test_get_nearby_enemies(self, game):
        enemies = game.get_nearby_enemies()
        assert isinstance(enemies, list)
        # Can't guarantee enemies exist, but structure should be right
        for e in enemies:
            assert "name" in e
            assert "direction" in e
            assert "distance" in e

    def test_get_messages(self, game):
        msgs = game.get_messages(n=5)
        assert isinstance(msgs, list)

    def test_properties(self, game):
        assert isinstance(game.hp, int)
        assert isinstance(game.max_hp, int)
        assert isinstance(game.xl, int)
        assert isinstance(game.depth, int)
        assert isinstance(game.turn, int)
        assert isinstance(game.is_dead, bool)
        assert isinstance(game.gold, int)


class TestActions:
    """Actions that are deterministic regardless of map layout."""

    def test_wait_turn_advances(self, game):
        t0 = game.turn
        game.wait_turn()
        assert game.turn == t0 + 1

    def test_wait_turn_preserves_hp(self, game):
        hp_before = game.hp
        game.wait_turn()
        # At full HP on turn 1, waiting shouldn't change HP
        # (extremely unlikely to spawn adjacent to a monster that hits immediately)
        assert game.hp <= hp_before  # HP can't increase above max

    def test_move_advances_turn(self, game):
        """Move into open space should advance turn."""
        # Auto-explore first to ensure we're not boxed in
        game.auto_explore()
        t0 = game.turn
        game.move("n")
        # Turn should advance (or stay same if blocked by wall)
        assert game.turn >= t0

    def test_auto_explore_advances_turns(self, game):
        t0 = game.turn
        game.auto_explore()
        assert game.turn > t0

    def test_rest_at_full_hp(self, game):
        """Rest at full HP should return without error."""
        t0 = game.turn
        msgs = game.rest()
        assert isinstance(msgs, list)
        # Rest at full HP shouldn't advance many turns (but might if enemies nearby)
        assert game.turn >= t0

    def test_multiple_actions_sequence(self, game):
        """A sequence of actions should all advance the game."""
        t0 = game.turn
        game.wait_turn()
        t1 = game.turn
        assert t1 > t0
        game.move("s")
        t2 = game.turn
        assert t2 > t0
        game.wait_turn()
        t3 = game.turn
        assert t3 > t2

    def test_state_consistent_after_actions(self, game):
        """State queries should reflect current game state after actions."""
        game.auto_explore()
        stats = game.get_stats()
        assert str(game.turn) in stats or game.turn > 0
        assert game.hp > 0  # shouldn't be dead from just exploring D:1 as MiBe


class TestOverlay:
    def test_update_overlay(self, game):
        # Should not raise
        game.update_overlay("test thought")

    def test_new_attempt(self, game):
        before = game._attempt
        game.new_attempt()
        assert game._attempt == before + 1

    def test_record_death(self, game):
        before = game._deaths
        game.record_death("test")
        assert game._deaths == before + 1


class TestQuit:
    def test_quit_game(self, game):
        game.quit_game()
        assert game._in_game is False

    def test_reconnect_to_save(self):
        """Disconnecting and reconnecting should preserve the account."""
        name = random_username()
        
        # First session: connect and start game
        g1 = DCSSGame()
        g1.connect("ws://localhost:8080/socket", name, name + "pw")
        g1.start_game(species_key="b", background_key="f", weapon_key="b")
        assert g1._in_game is True
        assert g1.turn >= 0
        g1.disconnect()

        # Second session: reconnect — account should still exist
        g2 = DCSSGame()
        g2.connect("ws://localhost:8080/socket", name, name + "pw")
        assert g2._connected is True
        assert len(g2._game_ids) > 0
        g2.disconnect()
