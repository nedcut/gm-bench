"""The 2.1 league: one record per season, and the playoff odds kept for scoring.

Contract source for 2.1 (fingerprinted by ``gm_bench.v21.contract``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from gm_bench.models import SeasonSummary, Team
from gm_bench.simulator import League

# Logistic scale of a playoff game in ``League._simulate_playoffs``. The two
# must agree or the recorded odds are not the odds the simulator used.
PLAYOFF_LOGIT_SCALE = 6.0


def bracket_odds(teams: list[Team], ratings: dict[int, float]) -> dict[int, tuple[float, float]]:
    """Exact (expected rounds won, title probability) for every playoff team.

    Mirrors ``League._simulate_playoffs``: slot ``i`` hosts slot ``-i-1`` for
    even ``i``, winners keep that order, one game per tie. Slots never share a
    team, so each slot is an independent distribution over its occupant.
    """
    slots: list[dict[int, float]] = [{team.id: 1.0} for team in teams]
    rounds_won = {team.id: 0.0 for team in teams}
    while len(slots) > 1:
        next_slots = []
        for index in range(0, len(slots), 2):
            home, away = slots[index], slots[-index - 1]
            winner: dict[int, float] = {}
            for home_id, home_p in home.items():
                for away_id, away_p in away.items():
                    p_home = 1.0 / (1.0 + math.exp(-(ratings[home_id] - ratings[away_id]) / PLAYOFF_LOGIT_SCALE))
                    winner[home_id] = winner.get(home_id, 0.0) + home_p * away_p * p_home
                    winner[away_id] = winner.get(away_id, 0.0) + home_p * away_p * (1.0 - p_home)
            for team_id, p in winner.items():
                rounds_won[team_id] += p
            next_slots.append(winner)
        slots = next_slots
    return {team_id: (rounds_won[team_id], slots[0].get(team_id, 0.0)) for team_id in rounds_won}


@dataclass
class League21(League):
    """``League`` with the two 2.1 rule changes; every other rule is 1.0's.

    - Records reset when a season opens (``docs/bench_v2_1_queue.md`` item
      15). Every episode plays the midseason leg, which opens the season, so
      the reset goes there; ``simulate_season`` already resets when it opens
      a season itself. Standings, playoff seeding, the lottery order and the
      free-agent win signal then read the season's own record, and each
      season summary carries that season's wins.
    - The playoff bracket's exact odds are recorded per season and team
      before the games are played, with the same ratings, so score-v2 can
      score expected rather than realized playoff results (item 16). The
      games themselves, and every random draw, are unchanged.
    - Opponents keep every draft slot behind the user's window (item 18).
      1.0 found the window's position again after the user drafted, from
      the user's earliest *unexercised* slot, so a second pick the user left
      unused moved it back and every opponent slot in between was skipped:
      ``pick-trader`` episodes lost about 12 opponent draftees each.
    """

    expected_playoffs: dict[int, dict[int, tuple[float, float]]] = field(default_factory=dict)
    _pending_summary_score: float | None = None
    # Slot index where the user's draft window opened this season (None: no slot then).
    _draft_window_slot: int | None = None

    def run_opponent_draft(self, before_user: bool) -> None:
        self.run_draft_lottery()
        slots = self._draft_slots()
        if before_user:
            user_slots = [index for index, (_, owner_id) in enumerate(slots) if owner_id == self.user_team_id]
            self._draft_window_slot = user_slots[0] if user_slots else None
            picking = [] if self._draft_window_slot is None else slots[: self._draft_window_slot]
        else:
            picking = slots if self._draft_window_slot is None else slots[self._draft_window_slot + 1 :]
            self._draft_window_slot = None
        for origin_id, owner_id in picking:
            # Skip the user's own slots (used or forfeited) and exercised ones.
            if owner_id is None or owner_id == self.user_team_id:
                continue
            self._opponent_draft_pick(self.teams[owner_id], origin_id)

    def simulate_partial_season(self, fraction: float) -> None:
        for team in self.teams.values():
            team.wins = 0
            team.losses = 0
        super().simulate_partial_season(fraction)

    def _simulate_playoffs(self, teams: list[Team], ratings: dict[int, float], rng) -> Team:  # type: ignore[override]
        # The odds read only the bracket and the ratings, which the games do
        # not change; record them after the games so nothing a parent class
        # writes to the same attribute can replace them.
        odds = bracket_odds(teams, ratings)
        champion = super()._simulate_playoffs(teams, ratings, rng)
        self.expected_playoffs = {**getattr(self, "expected_playoffs", {}), self.season: odds}
        return champion

    def _expiry_market_scramble(self, expired_player_ids, rng) -> None:  # type: ignore[override]
        super()._expiry_market_scramble(expired_player_ids, rng)
        # The last state change before ``simulate_season`` builds the summary:
        # score here so ``score_after_season`` is score-v2 on exactly the state
        # 1.0 scores at that point. Unlike 1.0, the season just played counts.
        from gm_bench.v21.scoring import score_team

        score = score_team(self, self.user_team_id, open_season_wins=self.user_team.wins)
        self._pending_summary_score = round(score, 3)

    def simulate_season(self) -> SeasonSummary:
        summary = super().simulate_season()
        if self._pending_summary_score is not None:
            summary.score_after_season = self._pending_summary_score
            self._pending_summary_score = None
        return summary
