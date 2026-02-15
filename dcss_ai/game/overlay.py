"""OverlayStats mixin: stream overlay stat tracking."""
import json
import os
import logging

logger = logging.getLogger(__name__)


class OverlayStats:
    """Mixin providing stream overlay statistics."""

    def _load_persistent_stats(self):
        """Load attempt/win/death counts from overlay stats file."""
        try:
            with open(self._stats_path) as f:
                data = json.load(f)
                self._attempt = data.get("attempt", 0)
                self._wins = data.get("wins", 0)
                self._deaths = data.get("deaths", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def update_overlay(self, thought: str = ""):
        """Write current game state + thought to the stream overlay stats file."""
        character = f"{self._species} {self._title}".strip() if self._species else "—"
        data = {
            "attempt": self._attempt,
            "wins": self._wins,
            "deaths": self._deaths,
            "character": character,
            "xl": self._xl,
            "place": f"{self._place}:{self._depth}" if self._place else "—",
            "turn": self._turn,
            "thought": thought,
            "status": "Dead" if self._is_dead else "Playing",
        }
        try:
            os.makedirs(os.path.dirname(self._stats_path), exist_ok=True)
            with open(self._stats_path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def new_attempt(self):
        """Call when starting a new game. Increments attempt counter."""
        if self._session_ended:
            return "Session has ended. Say GAME_OVER to finish."
        self._attempt += 1
        self.update_overlay("Starting new game...")

    def record_death(self, cause: str = ""):
        """Call when the character dies. Increments death counter."""
        if not self._is_dead:
            return "You're not dead! HP: {}/{}. Keep playing.".format(self._hp, self._max_hp)
        self._deaths += 1
        self._session_ended = True
        self.update_overlay(f"Died: {cause}" if cause else "Died.")

    def record_win(self):
        """Call when the character wins. Increments win counter."""
        self._wins += 1
        self._session_ended = True
        self.update_overlay("WON! 🎉")
