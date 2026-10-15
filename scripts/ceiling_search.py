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

    python scripts/ceiling_search.py hindsight --seeds 101-108 --beam 4
    python scripts/ceiling_search.py hindsight --seeds 101-108 --beam 4 --luck-neutral
    python scripts/ceiling_search.py fair --seeds 101-108 --worlds 6 --generated
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

from gm_bench.agents import AGENTS, Agent  # noqa: E402
from gm_bench.oracle import OracleAgent  # noqa: E402
from gm_bench.protocol import PHASES, EpisodeConfig  # noqa: E402
from gm_bench.runner import run_decision_point  # noqa: E402
from gm_bench.scoring import ACTIVE_SCORE_SCALE, score_components, score_team  # noqa: E402
from gm_bench.simulator import HARD_CAP_BUFFER, INJURY_GAMES_DEFAULT, SCOUT_REPORT_NOISE, League, Team  # noqa: E402

CONFIG = EpisodeConfig()
SEASONS = 5
STEPS: list[tuple[int, str]] = [(season, phase) for season in range(1, SEASONS + 1) for phase in PHASES]
BASE_POLICY = "pick-trader"

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


def new_league(seed: int) -> TrackedLeague:
    return TrackedLeague.new(seed=seed)


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

    def __init__(self, move: dict[str, Any], base: str = BASE_POLICY) -> None:
        self.move = move
        self.base = AGENTS[base]()
        self.name = self.base.name
        self.played = False

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.played:
            self.played = True
            return [self.move, {"type": "inspect_team", "team_id": observation["team"]["id"]}]
        return self.base.act({**observation, "interaction_round": 0})


def candidate_moves(*, hindsight: bool) -> dict[str, Callable[[], Agent]]:
    moves: dict[str, Callable[[], Agent]] = {name: AGENTS[name] for name in PUBLIC_POLICIES}
    for drop in DROPPABLE:
        moves[f"{BASE_POLICY}-no-{drop}"] = lambda drop=drop: DropActions(AGENTS[BASE_POLICY], drop)
    if hindsight:
        # The oracle reads the seed; that is only acceptable when the search
        # is already clairvoyant.
        moves["oracle"] = OracleAgent
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
    agent = AGENTS[policy]()
    for index in range(start, len(STEPS)):
        play_step(league, agent, index)
    return objective(league, luck_neutral)


# --------------------------------------------------------------------------
# Hindsight beam search
# --------------------------------------------------------------------------


def hindsight_search(seed: int, beam: int, luck_neutral: bool = False) -> dict[str, Any]:
    moves = candidate_moves(hindsight=True)
    frontier: list[tuple[float, list[str], League]] = [(0.0, [], new_league(seed))]
    for index in range(len(STEPS)):
        expanded: list[tuple[float, list[str], League]] = []
        for _value, path, league in frontier:
            for name, factory in moves.items():
                child = copy.deepcopy(league)
                play_step(child, factory(), index)
                value = rollout(copy.deepcopy(child), index + 1, luck_neutral=luck_neutral)
                expanded.append((value, [*path, name], child))
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
    _value, path, league = frontier[0]
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


def fair_menu(league: League, index: int, generated: bool) -> dict[str, Callable[[], Agent]]:
    menu = candidate_moves(hindsight=False)
    if generated:
        _season, phase = STEPS[index]
        observation = copy.deepcopy(league).observation(phase, tier="full")
        for name, move in generated_moves(observation).items():
            menu[name] = lambda move=move: OneMoveThenBase(move)
    return menu


def fair_choose(
    league: League,
    index: int,
    worlds: int,
    planner_seed: int,
    margin_z: float = 1.5,
    *,
    generated: bool = False,
) -> tuple[str, dict[str, Callable[[], Agent]]]:
    """Pick the move with the best paired gain over the base across sampled worlds.

    Called *after* the window's pre-step (midseason sim, deadline offers,
    opponent draft) so the sampled worlds share the public state the GM sees.
    """
    menu = fair_menu(league, index, generated)
    _season, phase = STEPS[index]
    sampled = [sample_world(league, phase, planner_seed * 1000 + index * 50 + w) for w in range(worlds)]
    outcomes: dict[str, list[float]] = {}
    for name, factory in menu.items():
        totals = []
        for world in sampled:
            trial = copy.deepcopy(world)
            run_decision_point(trial, factory(), phase, CONFIG)
            _finish_step(trial, index)
            totals.append(rollout(trial, index + 1, luck_neutral=True))
        outcomes[name] = totals
    # Every move is scored on the same worlds, whose dice are fixed by the
    # world seed, so compare each move with the base policy world by world.
    # Picking the raw best of many noisy means overfits the sampled worlds
    # (winner's curse); deviate only when the paired gain clears `margin_z`
    # standard errors.
    base = outcomes[BASE_POLICY]
    gains: dict[str, float] = {BASE_POLICY: 0.0}
    for name, totals in outcomes.items():
        if name == BASE_POLICY:
            continue
        diffs = [a - b for a, b in zip(totals, base)]
        mean = statistics.mean(diffs)
        se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else math.inf
        if mean > 0 and mean > margin_z * se:
            gains[name] = mean
    best = max(gains, key=lambda name: (gains[name], name == BASE_POLICY))
    return best, menu


def fair_search(
    seed: int, worlds: int, planner_seed: int, margin_z: float = 1.5, *, generated: bool = False
) -> dict[str, Any]:
    league = new_league(seed)
    path = []
    for index in range(len(STEPS)):
        _pre_step(league, index)
        choice, menu = fair_choose(league, index, worlds, planner_seed, margin_z, generated=generated)
        path.append(choice)
        run_decision_point(league, menu[choice](), STEPS[index][1], CONFIG)
        _finish_step(league, index)
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
    components = score_components(league, league.user_team_id)
    return {
        key.removesuffix("_contribution"): round(value, 3)
        for key, value in components.items()
        if key.endswith("_contribution")
    }


def _run_seed(job: tuple[str, int, dict[str, Any]]) -> dict[str, Any]:
    mode, seed, options = job
    started = time.perf_counter()
    baseline = new_league(seed)
    rollout(baseline, 0)
    if mode == "hindsight":
        found = hindsight_search(seed, options["beam"], options["luck_neutral"])
    else:
        found = fair_search(
            seed, options["worlds"], options["planner_seed"], options["margin_z"], generated=options["generated"]
        )
    league = found["league"]
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


def _mean_se(values: list[float]) -> tuple[float, float | None]:
    se = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
    return round(statistics.mean(values), 3), (round(se, 3) if se is not None else None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("hindsight", "fair"))
    parser.add_argument("--seeds", default="101-108", help="e.g. 101-108 or 101,105 (public seeds only)")
    parser.add_argument("--beam", type=int, default=4, help="hindsight beam width")
    parser.add_argument(
        "--luck-neutral", action="store_true", help="hindsight: optimize expected, not realized, playoffs"
    )
    parser.add_argument("--worlds", type=int, default=4, help="fair: sampled hidden worlds per decision")
    parser.add_argument("--generated", action="store_true", help="fair: add generated single moves to the menu")
    parser.add_argument("--margin-z", type=float, default=1.5, help="fair: paired-gain z needed to leave the base")
    parser.add_argument("--planner-seed", type=int, default=0, help="fair: the planner's own randomness")
    parser.add_argument("--jobs", type=int, default=1, help="seeds to search in parallel (local CPU only)")
    parser.add_argument("--out", type=Path, help="write per-seed JSON here")
    args = parser.parse_args(argv)

    options = {
        "beam": args.beam,
        "luck_neutral": args.luck_neutral,
        "worlds": args.worlds,
        "generated": args.generated,
        "planner_seed": args.planner_seed,
        "margin_z": args.margin_z,
    }
    jobs = [(args.mode, seed, options) for seed in _parse_seeds(args.seeds)]
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for row in pool.map(_run_seed, jobs):
            rows.append(row)
            print(
                f"seed {row['seed']}: {BASE_POLICY} {row['baseline']:7.1f}  {args.mode} {row['score']:7.1f}"
                f"  ({row['lift']:+.1f}; luck-neutral {row['luck_neutral_lift']:+.1f};"
                f" {row['championships']} titles; {row['seconds']}s)",
                flush=True,
            )
    lift, lift_se = _mean_se([row["lift"] for row in rows])
    neutral_lift, neutral_se = _mean_se([row["luck_neutral_lift"] for row in rows])
    summary = {
        "mode": args.mode,
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
    print(
        f"mean {BASE_POLICY} {summary['baseline_mean']:.1f}  {args.mode} {summary['score_mean']:.1f}"
        f"  lift {lift:+.1f} (se {lift_se}); luck-neutral {summary['baseline_luck_neutral_mean']:.1f}"
        f" -> {summary['luck_neutral_mean']:.1f}, lift {neutral_lift:+.1f} (se {neutral_se})"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
