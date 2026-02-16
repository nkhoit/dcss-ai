"""End-to-end driver tests using MockProvider.

Tests the full pipeline: driver → tools → game.py → webtiles
without any LLM API calls. The mock provider executes scripted
tool call sequences.

Requires a running DCSS webtiles server.
"""
import asyncio
import random
import string
import pytest
from dcss_ai.game import DCSSGame
from dcss_ai.tools import build_tools
from dcss_ai.providers.mock import MockProvider, MockSession


def random_username():
    suffix = ''.join(random.choices(string.ascii_lowercase, k=6))
    return f"mock{suffix}"


@pytest.fixture
def dcss():
    game = DCSSGame()
    name = random_username()
    game.connect("ws://localhost:8080/socket", name, name + "pw")
    yield game
    try:
        game.disconnect()
    except Exception:
        pass


class TestMockProvider:
    """Test that MockProvider + tools + game.py work end-to-end."""

    def test_scripted_game_lifecycle(self, dcss):
        """Full game: start → explore → check state → quit."""
        script = [
            {"name": "new_attempt", "args": {}},
            {"name": "start_game", "args": {
                "species_key": "b", "background_key": "f", "weapon_key": "b"
            }},
            {"stop": True},
            {"name": "auto_explore", "args": {}},
            {"stop": True},
            {"name": "record_death", "args": {"cause": "mock test"}},
            {"stop": True, "text": "GAME_OVER"},
        ]

        tools = build_tools(dcss)
        provider = MockProvider(script=script)

        async def run():
            await provider.start()
            session = await provider.create_session("test prompt", tools, "mock")

            # First send: new_attempt → start_game → stop
            r1 = await session.send("Start a game")
            assert not r1.completed
            assert len(session.results) == 2
            assert session.results[0]["name"] == "new_attempt"
            assert session.results[1]["name"] == "start_game"

            # Verify game is actually running
            assert dcss._in_game is True
            assert dcss.hp > 0

            # Second send: explore → stop
            r2 = await session.send("Keep playing")
            assert not r2.completed
            assert dcss.turn > 0  # auto_explore advanced turns

            # Third send: record_death → stop (completed)
            dcss._is_dead = True  # simulate server death signal
            r3 = await session.send("Continue")
            assert r3.completed
            assert dcss._deaths >= 1

            await provider.stop()

        asyncio.run(run())

    def test_remaining_state_query_tools(self, dcss):
        """Verify remaining state query tools return without error."""
        script = [
            {"name": "new_attempt", "args": {}},
            {"name": "start_game", "args": {
                "species_key": "b", "background_key": "f", "weapon_key": "b"
            }},
            {"name": "get_landmarks", "args": {}},
            {"name": "read_notes", "args": {}},
            {"name": "write_note", "args": {"text": "test note"}},
            {"name": "read_notes", "args": {}},
            {"stop": True},
        ]

        tools = build_tools(dcss)
        provider = MockProvider(script=script)

        async def run():
            await provider.start()
            session = await provider.create_session("test", tools, "mock")
            r = await session.send("Go")
            # All 6 calls should have succeeded
            assert len(session.results) == 6
            for entry in session.results:
                assert isinstance(entry["result"], str), f"{entry['name']} returned non-string"
            await provider.stop()

        asyncio.run(run())

    def test_movement_tools(self, dcss):
        """Test movement and action tools."""
        script = [
            {"name": "new_attempt", "args": {}},
            {"name": "start_game", "args": {
                "species_key": "b", "background_key": "f", "weapon_key": "b"
            }},
            {"name": "wait_turn", "args": {}},
            {"name": "move", "args": {"direction": "n"}},
            {"name": "move", "args": {"direction": "s"}},
            {"name": "auto_explore", "args": {}},
            {"name": "rest", "args": {}},
            {"stop": True},
        ]

        tools = build_tools(dcss)
        provider = MockProvider(script=script)

        async def run():
            await provider.start()
            session = await provider.create_session("test", tools, "mock")
            r = await session.send("Go")
            assert len(session.results) == 7
            # Game should have advanced
            assert dcss.turn > 0
            await provider.stop()

        asyncio.run(run())

    def test_overlay_tools(self, dcss):
        """Test overlay/bookkeeping tools that don't need a running game."""
        script = [
            {"name": "new_attempt", "args": {}},
            {"name": "update_overlay", "args": {"thought": "Testing overlay"}},
            {"name": "new_attempt", "args": {}},
            {"stop": True},
        ]

        tools = build_tools(dcss)
        provider = MockProvider(script=script)

        async def run():
            await provider.start()
            session = await provider.create_session("test", tools, "mock")
            r = await session.send("Go")
            assert len(session.results) == 3
            assert dcss._attempt >= 2
            await provider.stop()

        asyncio.run(run())

    def test_unknown_tool_raises(self, dcss):
        """Script referencing a non-existent tool should raise."""
        script = [{"name": "fake_tool", "args": {}}]
        tools = build_tools(dcss)
        provider = MockProvider(script=script)

        async def run():
            await provider.start()
            session = await provider.create_session("test", tools, "mock")
            with pytest.raises(RuntimeError, match="unknown tool"):
                await session.send("Go")
            await provider.stop()

        asyncio.run(run())

    def test_menu_tools(self, dcss):
        """Test menu interaction through the mock provider."""
        script = [
            {"name": "new_attempt", "args": {}},
            {"name": "start_game", "args": {
                "species_key": "b", "background_key": "f", "weapon_key": "b"
            }},
            {"name": "read_ui", "args": {}},  # no menu open
            {"stop": True},
        ]

        tools = build_tools(dcss)
        provider = MockProvider(script=script)

        async def run():
            await provider.start()
            session = await provider.create_session("test", tools, "mock")
            r = await session.send("Go")
            # read_menu with no menu should return the "no menu" message
            assert "No menu" in session.results[2]["result"] or "No" in session.results[2]["result"]
            await provider.stop()

        asyncio.run(run())
