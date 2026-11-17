"""Estimate how much score headroom GM-Bench leaves above the scripted baselines.

Two diagnostics, neither an official baseline nor a valid submission:

``hindsight``
    Beam search with a perfect simulator. Every candidate move is played on a
    cloned league with the real seed, so the search sees the dice (game results,
    injuries, development, reservation prices) before it commits. The result is
    a lower bound on the per-seed clairvoyant optimum: it says how much of the
    spread is luck plus hidden information, not what a fair agent can reach.
    With ``--luck-neutral`` the search optimizes, and reports, the score with
    playoff results replaced by their expectation (see below), so it cannot
    steer single-game playoff coin flips.

``fair``
    Determinized rollout planning (one-step policy improvement over a base
    policy). Before evaluating candidates, each sampled world replaces
    everything a GM cannot observe: the RNG seed (future dice, reservation
    prices, partner valuation bias, scout noise, future draft classes), every
    player's latent ``true_potential`` (redrawn from a posterior on public
    information), and current injuries. Candidates are scored on the same
    sampled worlds and the winner is then played on the real league. It uses
    only public information, so it is a legitimate (if expensive) agent and a
    lower bound on the fair expected-value ceiling.

Both choose, at each of the 20 decision windows, among *macro moves*: one
decision window played by a scripted policy, or by ``pick-trader`` with one
action family suppressed. With ``--generated`` (fair mode) the menu also gets
*single moves* built from the public observation: one signing, trade, offer
acceptance, waiver claim or release, played first, after which ``pick-trader``
plays the rest of the window on the updated observation. Rollouts after the
move are played by ``pick-trader``.

Luck-neutral score: the playoffs are single-elimination single games, so
``playoff_rounds`` and ``championships`` (up to 81 + 175 points) are mostly
dice. Every league here records, at each season's playoffs, the user team's
exact expected rounds won and title probability given the playoff ratings the
simulator used. The luck-neutral score swaps the realized playoff terms for
those expectations. Its expectation equals the real score's, so the fair
planner also uses it as a lower-variance rollout objective.

Contracts: the default, ``--contract 1.0``, plays the 1.0 simulator and
scores score-v1 (the 2026-10-14 diagnostics). ``--contract 2.1`` plays
``League21`` (records reset each season, the opponent-draft fix) and scores
score-v2 (``gm_bench.v21``), the contract the 2.1 lane's rows are scored
under. score-v2 already scores the expected playoff terms, with the same
bracket odds, weights and season windows as the luck-neutral score above, so
under 2.1 it is both the search objective and the reported score, and
``--luck-neutral`` is not needed. Rows also report the score with realized
playoff results put back, to show how much of a lift the playoff dice add.

Planner options (2026-10-26, ``scripts/ceiling_planner.py``; every default
reproduces the earlier runs): ``--menu`` adds the win-now policies
(``policies``), generated contract extensions (``extensions``), or both plus
generated buys of other teams' players (``extended``). ``--commit`` lets a
candidate switch the continuation: ``plan:X`` plays X now, and X then plays
every later window of the rollouts and of the real episode, until another
``plan:`` move wins. ``--one-goalie`` keeps the win-now policies from
dressing a second goalie on purpose (the +2.5 bonus is not published). The
``policy`` mode plays one scripted or win-now policy, for reference rows.

    python scripts/ceiling_search.py hindsight --seeds 101-108 --beam 4
    python scripts/ceiling_search.py hindsight --seeds 101-108 --beam 4 --luck-neutral
    python scripts/ceiling_search.py fair --seeds 101-108 --worlds 6 --generated
    python scripts/ceiling_search.py fair --contract 2.1 --seeds 101-108 --worlds 6 --generated
    python scripts/ceiling_search.py fair --contract 2.1 --seeds 101-108 --worlds 6 --generated --menu extended --commit
    python scripts/ceiling_search.py policy --contract 2.1 --seeds 101-108 --policy contend
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import statistics
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# The win-now policies and extension/buy moves live in a sibling module.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import ceiling_planner as planner  # noqa: E402

from gm_bench.agents import AGENTS, Agent  # noqa: E402
from gm_bench.oracle import OracleAgent  # noqa: E402
from gm_bench.protocol import PHASES, EpisodeConfig  # noqa: E402
from gm_bench.runner import run_decision_point  # noqa: E402
from gm_bench.scoring import ACTIVE_SCORE_SCALE, score_components, score_team  # noqa: E402
from gm_bench.simulator import HARD_CAP_BUFFER, INJURY_GAMES_DEFAULT, SCOUT_REPORT_NOISE, League, Team  # noqa: E402
from gm_bench.v21 import scoring as scoring_v2  # noqa: E402
from gm_bench.v21.rules import League21  # noqa: E402

CONFIG = EpisodeConfig()
SEASONS = 5
STEPS: list[tuple[int, str]] = [(season, phase) for season in range(1, SEASONS + 1) for phase in PHASES]
BASE_POLICY = "pick-trader"
CONTRACTS = ("1.0", "2.1")

# Public-information scripted policies. `random` is excluded because it seeds
# itself from the observation's seed, which a fair planner may not read.
PUBLIC_POLICIES = ("value", "shrewd", "strategic", "pick-trader", "win-now", "rebuild", "conservative", "exploit")
DROPPABLE = (
    "trade",
    "sign_free_agent",
    "release",
    "extend_contract",
    "accept_trade_offer",
    "claim_waiver",
    "set_lineup",
)
# Phases where a generated single move is tried. The draft window is left to
# the scripted policies: strategic scouting spends the window's query rounds.
GENERATED_PHASES = ("preseason", "midseason", "trade_deadline")
# --menu: "base" is the 2026-10-14 menu. "policies" adds the win-now
# policies (macro moves and, with --commit, plans); "extensions" adds
# generated contract extensions; "extended" adds both plus generated buys.
MENUS = ("base", "policies", "extensions", "extended")
MENUS_WITH_POLICIES = ("policies", "extended")
MENUS_WITH_EXTENSIONS = ("extensions", "extended")
# A --commit candidate "plan:X" plays X now and hands every later window to X.
COMMIT_PREFIX = "plan:"
PLANNER_OPTIONS = ("menu", "commit", "two_goalies")

# Latent-potential population priors, pooled from gm_bench/generator.py
# (initial rosters N(62, 9) seen with sd 5.5, free agents N(56.5, 7) / 6.5,
# draft prospects N(63, 11) / 8). One pooled prior keeps the sampler from
# reading population membership the GM can't see.
POTENTIAL_PRIOR_MEAN = 61.0
POTENTIAL_PRIOR_SD = 10.0
POTENTIAL_OBS_SD = 6.5

# Logistic scale of a playoff game in League._simulate_playoffs.
PLAYOFF_LOGIT_SCALE = 6.0


# --------------------------------------------------------------------------
# Luck-neutral playoff accounting
# --------------------------------------------------------------------------


def bracket_odds(teams: list[Team], ratings: dict[int, float]) -> dict[int, tuple[float, float]]:
    """Exact (expected rounds won, title probability) for every playoff team.

    Mirrors League._simulate_playoffs: slot ``i`` hosts slot ``-i-1`` for even
    ``i``, winners keep that order, one game per tie.  Slots never share a
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


class TrackedLeague(League):
    """A League that also records the user's expected playoff outcome.

    The simulation itself is untouched: the override only reads the bracket
    and ratings, then defers to League._simulate_playoffs with the same RNG.
    """

    def _simulate_playoffs(self, teams, ratings, rng):  # type: ignore[override]
        odds = bracket_odds(teams, ratings).get(self.user_team_id, (0.0, 0.0))
        expected = dict(getattr(self, "expected_playoffs", {}))
        expected[self.season] = odds
        self.expected_playoffs = expected
        return super()._simulate_playoffs(teams, ratings, rng)


def new_league(seed: int, contract: str = "1.0") -> League:
    """A fresh league under ``contract``'s rules; both record expected playoffs."""
    if contract == "2.1":
        return League21.new(seed=seed)
    if contract != "1.0":
        raise ValueError(f"unknown contract {contract!r}; expected one of {CONTRACTS}")
    return TrackedLeague.new(seed=seed)


def user_expected_playoffs(league: League) -> dict[int, tuple[float, float]]:
    """Season -> the user's (expected rounds won, title probability).

    ``TrackedLeague`` keeps the user's odds only; ``League21`` keeps every
    playoff team's, keyed by season and then team.
    """
    if isinstance(league, League21):
        user = league.user_team_id
        return {season: odds.get(user, (0.0, 0.0)) for season, odds in league.expected_playoffs.items()}
    return getattr(league, "expected_playoffs", {})


def contract_score(league: League) -> float:
    """The score the league's contract publishes: score-v1 on 1.0, score-v2 on 2.1."""
    if isinstance(league, League21):
        return scoring_v2.score_team(league, league.user_team_id)
    return score_team(league, league.user_team_id)


def realized_playoff_score(league: League21) -> float:
    """score-v2 with the expected playoff terms swapped back for the realized ones.

    The 2.1 counterpart of the 1.0 "real" score: it shows how much of a lift
    is playoff dice. Same windows as score-v2: rounds over the last three
    seasons, titles over all of them.
    """
    scale = scoring_v2.SCALE
    components = scoring_v2.score_components(league, league.user_team_id)
    recent = league.summaries[-scoring_v2.RECENT_PLAYOFF_SEASONS :]
    realized = (
        sum(summary.playoff_rounds for summary in recent) * scale.playoff_round
        + league.user_team.championships * scale.championship
    )
    expected = components["expected_playoff_rounds_contribution"] + components["expected_championships_contribution"]
    return contract_score(league) - expected + realized


def luck_neutral_score(league: League) -> float:
    """The real score with realized playoff terms swapped for their expectation."""
    scale = ACTIVE_SCORE_SCALE
    expected: dict[int, tuple[float, float]] = getattr(league, "expected_playoffs", {})
    recent = league.summaries[-3:]
    realized = (
        sum(summary.playoff_rounds for summary in recent) * scale.playoff_round
        + league.user_team.championships * scale.championship
    )
    neutral = (
        sum(expected.get(summary.season, (0.0, 0.0))[0] for summary in recent) * scale.playoff_round
        + sum(title for _rounds, title in expected.values()) * scale.championship
    )
    return score_team(league, league.user_team_id) - realized + neutral


def objective(league: League, luck_neutral: bool) -> float:
    if isinstance(league, League21):
        # score-v2 already scores expected playoffs; `luck_neutral` is moot.
        return contract_score(league)
    return luck_neutral_score(league) if luck_neutral else score_team(league, league.user_team_id)


# --------------------------------------------------------------------------
# Moves
# --------------------------------------------------------------------------


class DropActions(Agent):
    """Play a scripted policy but suppress one family of actions."""

    def __init__(self, base: type[Agent], drop: str) -> None:
        self.base = base()
        self.drop = drop
        # Keep the base name so the runner grants the same observation tier.
        self.name = self.base.name

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return [action for action in self.base.act(observation) if action.get("type") != self.drop]


class OneMoveThenBase(Agent):
    """Play one chosen action, then let the base policy finish the window.

    Round 0 sends the move plus a harmless query, which keeps the decision
    window open; the base policy then acts on the refreshed observation (as
    if it were its own first round), so its lineup and cap math see the move.
    """

    def __init__(self, move: dict[str, Any] | list[dict[str, Any]], base: str = BASE_POLICY) -> None:
        self.move = move
        self.base = planner.policy_factory(base)()
        self.name = self.base.name
        self.played = False

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.played:
            self.played = True
            moves = self.move if isinstance(self.move, list) else [self.move]
            return [*moves, {"type": "inspect_team", "team_id": observation["team"]["id"]}]
        return self.base.act({**observation, "interaction_round": 0})


def candidate_moves(*, hindsight: bool, menu: str = "base", two_goalies: bool = True) -> dict[str, Callable[[], Agent]]:
    moves: dict[str, Callable[[], Agent]] = {name: AGENTS[name] for name in PUBLIC_POLICIES}
    for drop in DROPPABLE:
        moves[f"{BASE_POLICY}-no-{drop}"] = lambda drop=drop: DropActions(AGENTS[BASE_POLICY], drop)
    if hindsight:
        # The oracle reads the seed; that is only acceptable when the search
        # is already clairvoyant.
        moves["oracle"] = OracleAgent
    if menu in MENUS_WITH_POLICIES:
        moves.update(planner.win_now_policies(two_goalies=two_goalies))
    return moves


def plan_names(menu: str = "base", two_goalies: bool = True) -> tuple[str, ...]:
    """Policies a ``--commit`` search may switch its continuation to."""
    if menu in MENUS_WITH_POLICIES:
        return (*PUBLIC_POLICIES, *planner.win_now_policies(two_goalies=two_goalies))
    return PUBLIC_POLICIES


def continuation_of(name: str, plan: str) -> str:
    """The policy that plays every later window after candidate ``name``."""
    return name.removeprefix(COMMIT_PREFIX) if name.startswith(COMMIT_PREFIX) else plan


def with_commitments(
    moves: dict[str, Callable[[], Agent]], plan: str, menu: str, two_goalies: bool
) -> dict[str, Callable[[], Agent]]:
    """Add one ``plan:X`` candidate per other plan: play X now and in every later window."""
    for name in plan_names(menu, two_goalies):
        if name != plan:
            moves[f"{COMMIT_PREFIX}{name}"] = moves[name]
    return moves


def generated_moves(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Single actions worth trying, built only from the public observation."""
    phase = observation["phase"]
    if phase not in GENERATED_PHASES:
        return {}
    season = int(observation["season"])
    team = observation["team"]
    rules = observation["rules"]
    roster = team["roster"]
    spend_limit = float(team["cap_room"]) + float(rules.get("hard_cap_buffer", HARD_CAP_BUFFER))
    moves: dict[str, dict[str, Any]] = {}

    def sign(player: dict[str, Any], years: int) -> None:
        salary = float(player["contract_quotes"][str(years)])
        if salary <= spend_limit:
            moves[f"sign:{player['id']}:{years}y"] = {
                "type": "sign_free_agent",
                "player_id": player["id"],
                "years": years,
                "salary": salary,
            }

    free_agents = observation.get("free_agents") or []
    by_overall = sorted(free_agents, key=lambda player: player["overall"], reverse=True)
    for player in by_overall[:3]:
        sign(player, 1)
    if by_overall:
        sign(by_overall[0], 3)
    young = [player for player in free_agents if player["age"] <= 24]
    if young:
        sign(max(young, key=lambda player: player["potential"]), 3)

    owned = sorted(int(s) for s, count in team.get("draft_picks", {}).items() if int(s) > season and count > 0)
    max_ahead = int(rules.get("pick_trading", {}).get("max_seasons_ahead", 3))
    tradeable = [s for s in owned if s <= season + max_ahead]
    # A buy must beat the weakest dressed player; a short roster dresses everyone.
    overalls = sorted(player["overall"] for player in roster)
    lineup_size = int(rules.get("lineup_size", 18))
    lineup_floor = overalls[-lineup_size] if len(overalls) >= lineup_size else 0.0
    market = [
        offer
        for offer in observation.get("trade_market") or []
        if offer["player"]["overall"] > lineup_floor and offer["player"]["salary"] <= spend_limit
    ]
    for offer in sorted(market, key=lambda offer: offer["player"]["overall"], reverse=True)[:3]:
        picks = tradeable[: max(1, min(2, math.ceil(float(offer.get("estimated_price", 1.0)))))]
        if picks:
            moves[f"buy:{offer['player']['id']}"] = {
                "type": "trade",
                "partner_team_id": offer["team_id"],
                "give_player_ids": [],
                "receive_player_ids": [offer["player"]["id"]],
                "give_pick_seasons": picks,
                "receive_pick_seasons": [],
            }

    standings = observation.get("standings") or []
    buyers = [row for row in standings if row["team_id"] != team["id"]]
    veterans = sorted((player for player in roster if player["age"] >= 30), key=lambda p: p["salary"], reverse=True)
    if buyers and len(roster) > int(rules.get("roster_min", 18)):
        for player in veterans[:2]:
            # Sell to the strongest club (contenders buy veterans) for its
            # nearest tradeable pick.
            buyer = max(buyers, key=lambda row: row.get("public_strength", 0.0))
            seasons = sorted(int(s) for s, n in buyer.get("draft_picks", {}).items() if season < int(s) and n > 0)
            seasons = [s for s in seasons if s <= season + max_ahead]
            if seasons:
                moves[f"sell:{player['id']}"] = {
                    "type": "trade",
                    "partner_team_id": buyer["team_id"],
                    "give_player_ids": [player["id"]],
                    "receive_player_ids": [],
                    "give_pick_seasons": [],
                    "receive_pick_seasons": [seasons[0]],
                }

    for offer in observation.get("incoming_offers") or []:
        moves[f"accept:{offer['offer_id']}"] = {"type": "accept_trade_offer", "offer_id": offer["offer_id"]}

    waivers = observation.get("waiver_wire") or []
    if phase == "midseason" and waivers:
        best = max(waivers, key=lambda player: player["overall"])
        moves[f"claim:{best['id']}"] = {"type": "claim_waiver", "player_id": best["id"]}

    if len(roster) > int(rules.get("roster_min", 18)):
        worst = min(roster, key=lambda player: player["overall"])
        moves[f"release:{worst['id']}"] = {"type": "release", "player_id": worst["id"]}
    return moves


# --------------------------------------------------------------------------
# Stepping
# --------------------------------------------------------------------------


def _pre_step(league: League, index: int) -> None:
    _season, phase = STEPS[index]
    if phase == "midseason":
        league.prepare_midseason()
    if phase == "trade_deadline":
        league.prepare_trade_deadline()
    if phase == "draft":
        league.run_opponent_draft(before_user=True)


def _finish_step(league: League, index: int) -> None:
    _season, phase = STEPS[index]
    if phase == "draft":
        league.run_opponent_draft(before_user=False)
    league.run_autopilot_opponents(phase)
    if phase == PHASES[-1]:
        league.simulate_season()


def play_step(league: League, agent: Agent, index: int) -> None:
    """Advance one decision window exactly as gm_bench.runner.run_episode does."""
    _pre_step(league, index)
    run_decision_point(league, agent, STEPS[index][1], CONFIG)
    _finish_step(league, index)


def rollout(league: League, start: int, policy: str = BASE_POLICY, *, luck_neutral: bool = False) -> float:
    agent = planner.policy_factory(policy)()
    for index in range(start, len(STEPS)):
        play_step(league, agent, index)
    return objective(league, luck_neutral)


# --------------------------------------------------------------------------
# Hindsight beam search
# --------------------------------------------------------------------------


def hindsight_search(
    seed: int,
    beam: int,
    luck_neutral: bool = False,
    contract: str = "1.0",
    *,
    menu: str = "base",
    commit: bool = False,
    two_goalies: bool = True,
) -> dict[str, Any]:
    """Beam search on the real league. With ``commit``, each beam entry keeps
    its own plan (the policy its rollouts continue with), and ``plan:X``
    candidates switch it."""
    moves = candidate_moves(hindsight=True, menu=menu, two_goalies=two_goalies)
    frontier: list[tuple[float, list[str], League, str]] = [(0.0, [], new_league(seed, contract), BASE_POLICY)]
    for index in range(len(STEPS)):
        expanded: list[tuple[float, list[str], League, str]] = []
        for _value, path, league, plan in frontier:
            menu_here = with_commitments(dict(moves), plan, menu, two_goalies) if commit else moves
            for name, factory in menu_here.items():
                child = copy.deepcopy(league)
                play_step(child, factory(), index)
                then = continuation_of(name, plan)
                value = rollout(copy.deepcopy(child), index + 1, then, luck_neutral=luck_neutral)
                expanded.append((value, [*path, name], child, then))
        expanded.sort(key=lambda item: item[0], reverse=True)
        # Distinct moves often produce the same league (e.g. a policy that
        # does nothing this window); keep the beam diverse by rollout value.
        frontier, seen = [], set()
        for item in expanded:
            key = round(item[0], 6)
            if key in seen:
                continue
            seen.add(key)
            frontier.append(item)
            if len(frontier) == beam:
                break
    _value, path, league, _plan = frontier[0]
    return {"path": path, "league": league}


# --------------------------------------------------------------------------
# Fair determinized planning
# --------------------------------------------------------------------------


def _posterior_potential(public: float, rng: random.Random, scout_report: float | None) -> float:
    if scout_report is not None:
        mean, sd = scout_report, SCOUT_REPORT_NOISE / math.sqrt(3.0)
    else:
        precision = 1.0 / POTENTIAL_PRIOR_SD**2 + 1.0 / POTENTIAL_OBS_SD**2
        mean = (POTENTIAL_PRIOR_MEAN / POTENTIAL_PRIOR_SD**2 + public / POTENTIAL_OBS_SD**2) / precision
        sd = math.sqrt(1.0 / precision)
    return min(95.0, max(38.0, rng.gauss(mean, sd)))


def sample_world(league: League, phase: str, world_seed: int) -> League:
    """Return a copy of ``league`` with every hidden quantity redrawn.

    ``world_seed`` must come from the planner's own randomness, never from the
    league. Public state (rosters, contracts, ratings, standings, picks, the
    drawn lottery, scout reports, the offers already shown) is kept as is.
    """
    world = copy.deepcopy(league)
    rng = random.Random(f"world:{world_seed}")
    world.seed = rng.randrange(1 << 62)
    pools = [world.players, world.prospects]
    for pool in pools:
        for player_id, player in pool.items():
            player.true_potential = _posterior_potential(player.potential, rng, world.scout_reports.get(player_id))
            player.injured_games = 0
    # Midseason injuries are drawn after the partial season and are not in the
    # observation; redraw them with the simulator's own rule.
    if league.partial_season_played and phase in ("midseason", "trade_deadline"):
        candidates = [player for player in world.players.values() if player.team_id is not None]
        candidates.sort(key=lambda player: player.id)
        rng.shuffle(candidates)
        for player in candidates[: rng.randint(2, 5)]:
            if rng.random() < player.injury_risk * 2.5:
                player.injured_games = INJURY_GAMES_DEFAULT
    return world


def fair_menu(
    league: League,
    index: int,
    generated: bool,
    *,
    menu: str = "base",
    plan: str = BASE_POLICY,
    commit: bool = False,
    two_goalies: bool = True,
) -> dict[str, Callable[[], Agent]]:
    """Candidates for this window, built from the real league's public state only."""
    moves = candidate_moves(hindsight=False, menu=menu, two_goalies=two_goalies)
    if generated:
        _season, phase = STEPS[index]
        observation = copy.deepcopy(league).observation(phase, tier="full")
        built: dict[str, Any] = dict(generated_moves(observation))
        if menu in MENUS_WITH_EXTENSIONS:
            built.update(planner.extension_moves(observation, two_goalies=two_goalies))
        if menu == "extended":
            rosters = planner.public_rosters(league)
            built.update(planner.buy_moves(observation, rosters, two_goalies=two_goalies))
        for name, move in built.items():
            moves[name] = lambda move=move: OneMoveThenBase(move, plan)
    if commit:
        moves = with_commitments(moves, plan, menu, two_goalies)
    return moves


def menu_outcomes(
    league: League,
    index: int,
    worlds: int,
    planner_seed: int,
    *,
    generated: bool = False,
    menu: str = "base",
    plan: str = BASE_POLICY,
    commit: bool = False,
    two_goalies: bool = True,
) -> tuple[dict[str, list[float]], dict[str, Callable[[], Agent]]]:
    """Each candidate's rollout value in each sampled world.

    A candidate is played on a copy of each world, and the rest of the
    episode by the policy it hands over to: the current ``plan``, or X for a
    ``plan:X`` candidate.
    """
    moves = fair_menu(league, index, generated, menu=menu, plan=plan, commit=commit, two_goalies=two_goalies)
    _season, phase = STEPS[index]
    sampled = [sample_world(league, phase, planner_seed * 1000 + index * 50 + w) for w in range(worlds)]
    outcomes: dict[str, list[float]] = {}
    for name, factory in moves.items():
        totals = []
        for world in sampled:
            trial = copy.deepcopy(world)
            run_decision_point(trial, factory(), phase, CONFIG)
            _finish_step(trial, index)
            totals.append(rollout(trial, index + 1, continuation_of(name, plan), luck_neutral=True))
        outcomes[name] = totals
    return outcomes, moves


def fair_choose(
    league: League,
    index: int,
    worlds: int,
    planner_seed: int,
    margin_z: float = 1.5,
    *,
    generated: bool = False,
    menu: str = "base",
    plan: str = BASE_POLICY,
    commit: bool = False,
    two_goalies: bool = True,
) -> tuple[str, dict[str, Callable[[], Agent]]]:
    """Pick the move with the best paired gain over the plan across sampled worlds.

    Called *after* the window's pre-step (midseason sim, deadline offers,
    opponent draft) so the sampled worlds share the public state the GM sees.
    """
    outcomes, moves = menu_outcomes(
        league,
        index,
        worlds,
        planner_seed,
        generated=generated,
        menu=menu,
        plan=plan,
        commit=commit,
        two_goalies=two_goalies,
    )
    # Every move is scored on the same worlds, whose dice are fixed by the
    # world seed, so compare each move with the plan's own move world by world.
    # Picking the raw best of many noisy means overfits the sampled worlds
    # (winner's curse); deviate only when the paired gain clears `margin_z`
    # standard errors.
    base = outcomes[plan]
    gains: dict[str, float] = {plan: 0.0}
    for name, totals in outcomes.items():
        if name == plan:
            continue
        diffs = [a - b for a, b in zip(totals, base)]
        mean = statistics.mean(diffs)
        se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else math.inf
        if mean > 0 and mean > margin_z * se:
            gains[name] = mean
    best = max(gains, key=lambda name: (gains[name], name == plan))
    return best, moves


def fair_search(
    seed: int,
    worlds: int,
    planner_seed: int,
    margin_z: float = 1.5,
    *,
    generated: bool = False,
    contract: str = "1.0",
    menu: str = "base",
    commit: bool = False,
    two_goalies: bool = True,
) -> dict[str, Any]:
    """Play the real league one window at a time with ``fair_choose``.

    The plan starts as ``pick-trader``; with ``commit`` a chosen ``plan:X``
    makes X the policy every later rollout, and every later window's default
    move, continues with.
    """
    league = new_league(seed, contract)
    path = []
    plan = BASE_POLICY
    for index in range(len(STEPS)):
        _pre_step(league, index)
        choice, moves = fair_choose(
            league,
            index,
            worlds,
            planner_seed,
            margin_z,
            generated=generated,
            menu=menu,
            plan=plan,
            commit=commit,
            two_goalies=two_goalies,
        )
        path.append(choice)
        run_decision_point(league, moves[choice](), STEPS[index][1], CONFIG)
        _finish_step(league, index)
        plan = continuation_of(choice, plan)
    return {"path": path, "league": league}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_seeds(text: str) -> list[int]:
    seeds: list[int] = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            seeds.extend(range(int(low), int(high) + 1))
        else:
            seeds.append(int(part))
    return seeds


def _components(league: League) -> dict[str, float]:
    scorer = scoring_v2.score_components if isinstance(league, League21) else score_components
    components = scorer(league, league.user_team_id)
    return {
        key.removesuffix("_contribution"): round(value, 3)
        for key, value in components.items()
        if key.endswith("_contribution")
    }


def _run_seed(job: tuple[str, int, dict[str, Any]]) -> dict[str, Any]:
    mode, seed, options = job
    contract = options.get("contract", "1.0")
    started = time.perf_counter()
    baseline = new_league(seed, contract)
    rollout(baseline, 0)
    planner_options = {key: options[key] for key in PLANNER_OPTIONS if key in options}
    if mode == "policy":
        found = play_policy(seed, options["policy"], contract)
    elif mode == "hindsight":
        found = hindsight_search(seed, options["beam"], options["luck_neutral"], contract, **planner_options)
    else:
        found = fair_search(
            seed,
            options["worlds"],
            options["planner_seed"],
            options["margin_z"],
            generated=options["generated"],
            contract=contract,
            **planner_options,
        )
    league = found["league"]
    if contract == "2.1":
        row = _row_v21(seed, baseline, league, found["path"], started)
        if planner_options or mode == "policy":
            row.update(planner.play_counts(baseline, league))
            row.update(planner.continuation(baseline, league, play_step))
        return row
    base_score, score = score_team(baseline, 0), score_team(league, 0)
    base_neutral, neutral = luck_neutral_score(baseline), luck_neutral_score(league)
    return {
        "seed": seed,
        "baseline": round(base_score, 3),
        "score": round(score, 3),
        "lift": round(score - base_score, 3),
        "baseline_luck_neutral": round(base_neutral, 3),
        "luck_neutral": round(neutral, 3),
        "luck_neutral_lift": round(neutral - base_neutral, 3),
        "championships": league.user_team.championships,
        "expected_championships": round(sum(t for _r, t in league.expected_playoffs.values()), 3),
        "baseline_expected_championships": round(sum(t for _r, t in baseline.expected_playoffs.values()), 3),
        "baseline_components": _components(baseline),
        "components": _components(league),
        "path": found["path"],
        "seconds": round(time.perf_counter() - started, 1),
    }


def play_policy(seed: int, policy: str, contract: str = "1.0") -> dict[str, Any]:
    """One scripted policy (a registered one or a win-now one) for a whole episode."""
    league = new_league(seed, contract)
    rollout(league, 0, policy)
    return {"path": [policy] * len(STEPS), "league": league}


def _row_v21(seed: int, baseline: League, league: League, path: list[str], started: float) -> dict[str, Any]:
    """A 2.1 row: ``score`` is score-v2; ``realized_playoffs`` puts the playoff dice back."""
    base_score, score = contract_score(baseline), contract_score(league)
    base_real, real = realized_playoff_score(baseline), realized_playoff_score(league)
    return {
        "seed": seed,
        "baseline": round(base_score, 3),
        "score": round(score, 3),
        "lift": round(score - base_score, 3),
        "baseline_realized_playoffs": round(base_real, 3),
        "realized_playoffs": round(real, 3),
        "realized_playoffs_lift": round(real - base_real, 3),
        "championships": league.user_team.championships,
        "baseline_championships": baseline.user_team.championships,
        "expected_championships": round(sum(t for _r, t in user_expected_playoffs(league).values()), 3),
        "baseline_expected_championships": round(sum(t for _r, t in user_expected_playoffs(baseline).values()), 3),
        "baseline_components": _components(baseline),
        "components": _components(league),
        "path": path,
        "seconds": round(time.perf_counter() - started, 1),
    }


def _mean_se(values: list[float]) -> tuple[float, float | None]:
    se = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
    return round(statistics.mean(values), 3), (round(se, 3) if se is not None else None)


def _summary_v21(mode: str, options: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    lift, lift_se = _mean_se([row["lift"] for row in rows])
    real_lift, real_se = _mean_se([row["realized_playoffs_lift"] for row in rows])
    component_lifts = {
        term: _mean_se([row["components"][term] - row["baseline_components"][term] for row in rows])
        for term in rows[0]["components"]
    }

    def mean(key: str) -> float:
        return round(statistics.mean(row[key] for row in rows), 3)

    play: dict[str, Any] = {}
    if "wins" in rows[0]:
        # Non-default runs only, so the committed 2.1 files reproduce as written.
        play = {
            "play_means": {
                "wins": mean("wins"),
                "baseline_wins": mean("baseline_wins"),
                "championships": mean("championships"),
                "baseline_championships": mean("baseline_championships"),
                "roster_at_end": mean("roster_at_end"),
                "baseline_roster_at_end": mean("baseline_roster_at_end"),
                "moves": {
                    kind: round(statistics.mean(row["moves"][kind] for row in rows), 3) for kind in rows[0]["moves"]
                },
                "baseline_moves": {
                    kind: round(statistics.mean(row["baseline_moves"][kind] for row in rows), 3)
                    for kind in rows[0]["baseline_moves"]
                },
            },
            "illegal_actions_total": sum(row["illegal_actions"] for row in rows),
            "baseline_illegal_actions_total": sum(row["baseline_illegal_actions"] for row in rows),
            "rejected_offers_total": sum(row["rejected_offers"] for row in rows),
            # Winning value over five more seasons under pick-trader, against the
            # end-state score that is supposed to stand in for it.
            "continuation": {
                "end_state_gap": dict(
                    zip(("mean", "se"), _mean_se([r["end_state"] - r["baseline_end_state"] for r in rows]))
                ),
                "winning_gap": dict(
                    zip(
                        ("mean", "se"),
                        _mean_se([r["continuation_winning"] - r["baseline_continuation_winning"] for r in rows]),
                    )
                ),
            },
        }
    return {
        "mode": mode,
        "contract": "2.1",
        "scoring_version": scoring_v2.SCORING_VERSION,
        "options": options,
        "seeds": [row["seed"] for row in rows],
        "baseline_mean": mean("baseline"),
        "score_mean": mean("score"),
        "lift_mean": lift,
        "lift_se": lift_se,
        "seeds_ahead": sum(row["lift"] > 0 for row in rows),
        "baseline_realized_playoffs_mean": mean("baseline_realized_playoffs"),
        "realized_playoffs_mean": mean("realized_playoffs"),
        "realized_playoffs_lift_mean": real_lift,
        "realized_playoffs_lift_se": real_se,
        "realized_playoffs_seeds_ahead": sum(row["realized_playoffs_lift"] > 0 for row in rows),
        "baseline_expected_championships_mean": mean("baseline_expected_championships"),
        "expected_championships_mean": mean("expected_championships"),
        "component_lift_means": {term: {"mean": m, "se": se} for term, (m, se) in component_lifts.items()},
        **play,
        "rows": rows,
    }


def _summary_v1(mode: str, options: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    lift, lift_se = _mean_se([row["lift"] for row in rows])
    neutral_lift, neutral_se = _mean_se([row["luck_neutral_lift"] for row in rows])
    return {
        "mode": mode,
        "options": options,
        "seeds": [row["seed"] for row in rows],
        "baseline_mean": round(statistics.mean(row["baseline"] for row in rows), 3),
        "score_mean": round(statistics.mean(row["score"] for row in rows), 3),
        "lift_mean": lift,
        "lift_se": lift_se,
        "baseline_luck_neutral_mean": round(statistics.mean(row["baseline_luck_neutral"] for row in rows), 3),
        "luck_neutral_mean": round(statistics.mean(row["luck_neutral"] for row in rows), 3),
        "luck_neutral_lift_mean": neutral_lift,
        "luck_neutral_lift_se": neutral_se,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("hindsight", "fair", "policy"))
    parser.add_argument("--seeds", default="101-108", help="e.g. 101-108 or 101,105 (public seeds only)")
    parser.add_argument(
        "--contract",
        choices=CONTRACTS,
        default="1.0",
        help="1.0: 1.0 simulator and score-v1 (default); 2.1: League21 and score-v2",
    )
    parser.add_argument("--beam", type=int, default=4, help="hindsight beam width")
    parser.add_argument(
        "--luck-neutral", action="store_true", help="hindsight: optimize expected, not realized, playoffs"
    )
    parser.add_argument("--worlds", type=int, default=4, help="fair: sampled hidden worlds per decision")
    parser.add_argument("--generated", action="store_true", help="fair: add generated single moves to the menu")
    parser.add_argument("--margin-z", type=float, default=1.5, help="fair: paired-gain z needed to leave the base")
    parser.add_argument("--planner-seed", type=int, default=0, help="fair: the planner's own randomness")
    parser.add_argument(
        "--menu",
        choices=MENUS,
        default="base",
        help="base: the 2026-10-14 menu; policies: + win-now policies; extensions: + generated"
        " extensions (with --generated); extended: both, plus generated buys",
    )
    parser.add_argument(
        "--commit", action="store_true", help="candidates may also switch the continuation policy for the rest"
    )
    parser.add_argument(
        "--one-goalie",
        action="store_true",
        help="win-now policies dress a second goalie only if he ranks in by overall (the bonus is unpublished)",
    )
    parser.add_argument("--policy", help="policy mode: the scripted or win-now policy to play")
    parser.add_argument("--jobs", type=int, default=1, help="seeds to search in parallel (local CPU only)")
    parser.add_argument("--out", type=Path, help="write per-seed JSON here")
    args = parser.parse_args(argv)
    v21 = args.contract == "2.1"
    if v21 and args.luck_neutral:
        parser.error("--luck-neutral is 1.0 only: score-v2 already scores expected playoffs")

    options = {
        "beam": args.beam,
        "luck_neutral": args.luck_neutral,
        "worlds": args.worlds,
        "generated": args.generated,
        "planner_seed": args.planner_seed,
        "margin_z": args.margin_z,
    }
    if v21:
        # Only set off the default, so 1.0 output stays byte for byte as before.
        options["contract"] = args.contract
    # Likewise: the planner options are recorded only when they are used.
    if args.menu != "base":
        options["menu"] = args.menu
    if args.commit:
        options["commit"] = True
    if args.one_goalie:
        options["two_goalies"] = False
    if args.mode == "policy":
        if not args.policy:
            parser.error("policy mode needs --policy")
        planner.policy_factory(args.policy)
        options["policy"] = args.policy
    jobs = [(args.mode, seed, options) for seed in _parse_seeds(args.seeds)]
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for row in pool.map(_run_seed, jobs):
            rows.append(row)
            other = (
                f"realized playoffs {row['realized_playoffs_lift']:+.1f}"
                if v21
                else f"luck-neutral {row['luck_neutral_lift']:+.1f}"
            )
            print(
                f"seed {row['seed']}: {BASE_POLICY} {row['baseline']:7.1f}  {args.mode} {row['score']:7.1f}"
                f"  ({row['lift']:+.1f}; {other}; {row['championships']} titles; {row['seconds']}s)",
                flush=True,
            )
    if v21:
        summary = _summary_v21(args.mode, options, rows)
        print(
            f"mean {BASE_POLICY} {summary['baseline_mean']:.1f}  {args.mode} {summary['score_mean']:.1f}"
            f"  score-v2 lift {summary['lift_mean']:+.1f} (se {summary['lift_se']}),"
            f" ahead on {summary['seeds_ahead']}/{len(rows)}; realized-playoffs lift"
            f" {summary['realized_playoffs_lift_mean']:+.1f} (se {summary['realized_playoffs_lift_se']})"
        )
    else:
        summary = _summary_v1(args.mode, options, rows)
        print(
            f"mean {BASE_POLICY} {summary['baseline_mean']:.1f}  {args.mode} {summary['score_mean']:.1f}"
            f"  lift {summary['lift_mean']:+.1f} (se {summary['lift_se']});"
            f" luck-neutral {summary['baseline_luck_neutral_mean']:.1f}"
            f" -> {summary['luck_neutral_mean']:.1f}, lift {summary['luck_neutral_lift_mean']:+.1f}"
            f" (se {summary['luck_neutral_lift_se']})"
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
