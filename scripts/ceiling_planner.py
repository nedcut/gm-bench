"""Win-now policies, extension and buy moves for ``scripts/ceiling_search.py``.

The 2026-10-26 2.1 ceiling searches stayed below ``gpt-6-astra``'s +46.9 and
the write-up (``docs/score_ceiling.md``) offered three reasons, none measured:
(a) every candidate deviates from ``pick-trader`` for one window and hands
back to it, so a sustained plan is never scored as one; (b) no scripted
policy on the menu is a good win-now policy; (c) the generated moves include
no contract extension. This module supplies what (b) and (c) say is missing;
the plan-commitment option for (a) lives in ``ceiling_search.fair_search``.

Everything here reads only what a GM can see: the observation, plus other
teams' rosters through ``inspect_team`` (which any agent may call; the policy
queries it in its first interaction round, and ``public_rosters`` builds the
identical payload for the planner's move generator). Two engine rules the
policies use are worth naming:

- ``League._team_strength`` adds 2.5 per dressed goalie, up to two
  (``GOALIE_BONUS``). ``get_rules`` does not publish it
  (``docs/bench_v2_1_queue.md`` item 26), so the policies take it as an
  option (``two_goalies``) and the search reports runs with and without it.
- A partner accepts a trade when the public asset value it gives up, times a
  hidden per-season bias in [0.9, 1.1], is at most the value it receives
  over 0.95. ``Player.asset_value`` reads only public fields, so a bid can be
  priced to an expected acceptance; only the bias is unknown, and a declined
  bid is a rejected offer, not a protocol penalty.
"""

from __future__ import annotations

import copy
from typing import Any

from gm_bench.agent_utils import public_asset_value
from gm_bench.agents import AGENTS, Agent
from gm_bench.models import LINEUP_MIN_POSITIONS, LINEUP_SIZE, ROSTER_MIN
from gm_bench.protocol import PHASES
from gm_bench.v21 import scoring as scoring_v2

# League._team_strength: +2.5 per dressed goalie up to two; +0.4 per dressed
# center up to three; 0.25 strength per unit of payroll over the cap.
GOALIE_BONUS = 2.5
GOALIE_BONUS_MAX = 2
CENTER_BONUS = 0.4
CENTER_TARGET = 3
CAP_STRENGTH_PENALTY = 0.25
SEASONS = 5
# The roster is scored after the final season's contracts expire. A deal that
# should still be on the books then must run past the last season.
FINAL_SEASON = SEASONS


def strength_of(players: list[dict[str, Any]], payroll: float, cap: float) -> float:
    """``League._team_strength`` (no injury noise) for a dressed lineup."""
    lineup = sorted(players, key=lambda player: player["overall"], reverse=True)
    if not lineup:
        return 20.0
    goalies = sum(1 for player in lineup if player["position"] == "G")
    centers = sum(1 for player in lineup if player["position"] == "F" and player.get("sub_position") == "C")
    bonus = min(goalies, GOALIE_BONUS_MAX) * GOALIE_BONUS + min(centers, CENTER_TARGET) * CENTER_BONUS
    weighted = total = 0.0
    for index, player in enumerate(lineup):
        weight = 1.0 if index < 6 else 0.74 if index < 12 else 0.48
        weighted += player["overall"] * weight
        total += weight
    return weighted / total + bonus - max(0.0, payroll - cap) * CAP_STRENGTH_PENALTY


def lineup_is_legal(lineup: list[dict[str, Any]]) -> bool:
    """Whether ``set_lineup`` would accept these players (size and position minimums)."""
    if len(lineup) != LINEUP_SIZE or len({p["id"] for p in lineup}) != LINEUP_SIZE:
        return False
    return all(sum(p["position"] == pos for p in lineup) >= need for pos, need in LINEUP_MIN_POSITIONS.items())


def roster_has_positions(roster: list[dict[str, Any]]) -> bool:
    """Whether a legal lineup can still be dressed from this roster."""
    return all(sum(p["position"] == pos for p in roster) >= need for pos, need in LINEUP_MIN_POSITIONS.items())


def best_lineup(roster: list[dict[str, Any]], *, two_goalies: bool = True) -> list[dict[str, Any]]:
    """The strongest legal 18 among a few constructions ([] if none is legal).

    A roster of 18 or fewer dresses whole, as ``League._effective_lineup``
    does. With ``two_goalies`` off, extra goalies compete for the open slots
    by overall, as in the scripted policies' lineups; with it on, the search
    also tries dressing exactly two.
    """
    if len(roster) <= LINEUP_SIZE:
        return list(roster)
    by_overall = sorted(roster, key=lambda player: (-player["overall"], player["id"]))
    by_position = {pos: [p for p in by_overall if p["position"] == pos] for pos in LINEUP_MIN_POSITIONS}
    options: list[list[dict[str, Any]]] = []
    for goalies in (1, GOALIE_BONUS_MAX) if two_goalies else (1,):
        if len(by_position["G"]) < goalies:
            continue
        for centers_first in (False, True):
            forwards = by_position["F"]
            if centers_first:
                centers = [p for p in forwards if p.get("sub_position") == "C"][:CENTER_TARGET]
                forwards = centers + [p for p in forwards if p not in centers]
            chosen = (
                by_position["G"][:goalies]
                + by_position["D"][: LINEUP_MIN_POSITIONS["D"]]
                + forwards[: LINEUP_MIN_POSITIONS["F"]]
            )
            ids = {p["id"] for p in chosen}
            rest = [p for p in by_overall if p["id"] not in ids and not (two_goalies and p["position"] == "G")]
            chosen += rest[: LINEUP_SIZE - len(chosen)]
            if lineup_is_legal(chosen):
                options.append(chosen)
    if not options:
        return []
    return max(options, key=lambda lineup: strength_of(lineup, 0.0, 1.0))


def dressed(players: list[dict[str, Any]], *, two_goalies: bool) -> list[dict[str, Any]]:
    """The best lineup, or the top 18 by overall when no legal lineup exists."""
    return best_lineup(players, two_goalies=two_goalies) or sorted(players, key=lambda p: -p["overall"])[:LINEUP_SIZE]


def lineup_strength(players: list[dict[str, Any]], payroll: float, cap: float, *, two_goalies: bool) -> float:
    """Strength of the lineup ``dressed`` picks, after the cap penalty."""
    return strength_of(dressed(players, two_goalies=two_goalies), payroll, cap)


def asset_value(player: dict[str, Any]) -> float:
    """``Player.asset_value`` from the public fields it reads (what partners price)."""
    age_factor = max(0.05, 1.18 - max(player["age"] - 23, 0) * 0.055)
    contract_factor = 1.0
    if player.get("contract_years", 0) > 0:
        surplus = max(-10.0, player["overall"] - 52.0 - player["salary"] * 2.5)
        contract_factor += surplus * 0.018
    return max(0.0, (player["overall"] * 0.55 + player["potential"] * 0.45 - 45.0) * age_factor * contract_factor)


def contract_years_to_end(season: int, *, extension: bool = False) -> int:
    """Shortest term that keeps a deal signed in ``season`` past the final rollover."""
    low = 2 if extension else 1
    return max(low, min(5, FINAL_SEASON + 2 - season))


def public_rosters(league: Any) -> dict[int, list[dict[str, Any]]]:
    """Every other team's roster, exactly as ``inspect_team`` returns it."""
    return {
        team.id: [league.players[player_id].public_dict() for player_id in team.roster]
        for team in league.teams.values()
        if team.id != league.user_team_id
    }


def _trades_this_season(observation: dict[str, Any]) -> dict[int, int]:
    """Accepted user trades per partner this season, from the public ledger."""
    season = int(observation["season"])
    user = observation["team"]["id"]
    names = {row["team_name"]: row["team_id"] for row in observation.get("standings") or []}
    counts: dict[int, int] = {}
    for row in observation.get("recent_transactions") or []:
        if row.get("season") != season or row.get("team_id") != user or not row.get("accepted"):
            continue
        action = row.get("action") or {}
        partner = None
        if action.get("type") == "trade":
            partner = action.get("partner_team_id")
        elif action.get("type") in ("accept_trade_offer", "accept_offer"):
            partner = names.get(str(row.get("message", "")).removeprefix("accepted offer from "))
        if partner is not None:
            counts[int(partner)] = counts.get(int(partner), 0) + 1
    return counts


def _owned_tradeable_picks(observation: dict[str, Any]) -> list[int]:
    season = int(observation["season"])
    window = int(observation["rules"]["pick_trading"].get("max_seasons_ahead", 3))
    picks = observation["team"].get("draft_picks") or {}
    owned: list[int] = []
    for pick_season in range(season + 1, season + window + 1):
        # A season no trade has touched is an implicit single own pick.
        count = picks.get(pick_season, picks.get(str(pick_season), 1))
        owned.extend([pick_season] * int(count))
    return owned


def plan_buys(
    observation: dict[str, Any],
    rosters: dict[int, list[dict[str, Any]]],
    roster: list[dict[str, Any]],
    payroll: float,
    *,
    two_goalies: bool,
    over_cap: float,
    margin: float,
    max_trades: int,
    min_gain: float,
    spend_youth: bool,
    exclude_ids: frozenset[int] = frozenset(),
) -> list[dict[str, Any]]:
    """Trades that buy strength now with picks and players who don't dress.

    Each bid takes currency (future picks and bench players, by public asset
    value, largest first) until it reaches ``margin`` times the target's
    value, then drops any item it can do without, and must raise lineup strength by ``min_gain`` after the cap
    penalty. Hard-cap and roster-floor checks assume every earlier bid in the
    batch is accepted on the payroll side and rejected on the roster side, so
    no bid can turn into a penalized move whatever the partners decide.
    """
    rules = observation["rules"]
    cap = float(rules["salary_cap"])
    hard_cap = cap + float(rules.get("hard_cap_buffer", 8.0))
    pick_values = {int(s): float(v) for s, v in rules["pick_trading"]["pick_value_estimate"].items()}
    limit = int(rules.get("trade_limit_per_partner", 2))
    used_with = _trades_this_season(observation)
    picks = _owned_tradeable_picks(observation)
    payroll_hi = payroll
    roster_lo = len(roster)
    current = list(roster)
    given: set[int] = set()
    trades: list[dict[str, Any]] = []
    partners_used: set[int] = set()
    partners = {
        row["team_id"] for row in observation.get("standings") or [] if row["team_id"] != observation["team"]["id"]
    }

    def gain_with(players: list[dict[str, Any]], pay: float) -> float:
        return lineup_strength(players, pay, cap, two_goalies=two_goalies)

    base = gain_with(current, payroll)
    targets: list[tuple[float, int, dict[str, Any]]] = []
    floor = min((p["overall"] for p in dressed(current, two_goalies=two_goalies)), default=0.0)
    for team_id, players in rosters.items():
        if used_with.get(team_id, 0) >= limit or team_id not in partners:
            continue
        for player in players:
            if player["overall"] <= floor + 1.0 or player["id"] in exclude_ids:
                continue
            gain = gain_with([*current, player], payroll + player["salary"]) - base
            if gain >= min_gain:
                targets.append((gain, team_id, player))
    targets.sort(key=lambda item: (-item[0], item[2]["id"]))
    for _gain, team_id, target in targets:
        if len(trades) >= max_trades:
            break
        if team_id in partners_used:
            continue
        partner_roster = rosters[team_id]
        partner_payroll = sum(p["salary"] for p in partner_roster)
        lineup_ids = {p["id"] for p in dressed([*current, target], two_goalies=two_goalies)}
        bench = [
            p for p in current if p["id"] not in lineup_ids and p["id"] not in given and (spend_youth or p["age"] > 24)
        ]
        currency: list[tuple[float, str, Any]] = [(pick_values.get(s, 0.0), "pick", s) for s in picks]
        currency += [(asset_value(p), "player", p) for p in bench if asset_value(p) > 0.5]
        currency.sort(key=lambda item: -item[0])
        need = asset_value(target) * margin
        if need <= 0.0:
            continue
        bid: list[tuple[float, str, Any]] = []
        total = 0.0
        for item in currency:
            if total >= need:
                break
            bid.append(item)
            total += item[0]
        if total < need:
            continue
        # Drop any item the bid still clears without, largest first.
        for item in sorted(bid, key=lambda item: -item[0]):
            if total - item[0] >= need:
                bid.remove(item)
                total -= item[0]
        give_players = [item[2] for item in bid if item[1] == "player"]
        give_picks = sorted(item[2] for item in bid if item[1] == "pick")
        give_salary = sum(p["salary"] for p in give_players)
        net = target["salary"] - give_salary
        if payroll_hi + max(0.0, net) > min(hard_cap, cap + over_cap) and net > 0:
            continue
        if partner_payroll - target["salary"] + give_salary > hard_cap:
            continue
        shrink = len(give_players) - 1
        if shrink > 0 and roster_lo - len(give_players) < ROSTER_MIN:
            continue
        # A pure pick bid shrinks the partner's roster by one.
        if not give_players and len(partner_roster) - 1 < ROSTER_MIN:
            continue
        new_roster = [p for p in current if p not in give_players] + [target]
        if not roster_has_positions(new_roster):
            continue
        new_pay = payroll + net
        if gain_with(new_roster, new_pay) - gain_with(current, payroll) < min_gain:
            continue
        trades.append(
            {
                "type": "trade",
                "partner_team_id": team_id,
                "give_player_ids": [p["id"] for p in give_players],
                "receive_player_ids": [target["id"]],
                "give_pick_seasons": give_picks,
                "receive_pick_seasons": [],
            }
        )
        partners_used.add(team_id)
        for p in give_players:
            given.add(p["id"])
        for s in give_picks:
            picks.remove(s)
        payroll_hi += max(0.0, net)
        roster_lo -= len(give_players)
        # Plan the next bid as if this one went through.
        current, payroll = new_roster, new_pay
    return trades


class Contender(Agent):
    """A scripted win-now policy: keep the core, fill the cap, buy veterans.

    Per decision window, using public information only:

    1. If ``buy``, query every other team's roster (``inspect_team``).
    2. Preseason: extend every extension-eligible player who dresses, for
       the shortest term that runs past the final season.
    3. Midseason: claim a waiver player who raises strength.
    4. Sign free agents who raise lineup strength by ``min_gain`` (after the
       cap penalty), best first, while payroll stays within the cap plus
       ``over_cap``.
    5. If ``buy``, bid future picks and non-dressing players for other teams'
       players who raise strength (``plan_buys``).
    6. Draft the best prospect by public asset value with every pick held.
    7. Next round, dress the strongest legal lineup on the roster that
       actually resulted (two goalies when ``two_goalies``).
    """

    name = "contend"

    def __init__(
        self,
        *,
        extend: bool = True,
        sign: bool = True,
        buy: bool = True,
        two_goalies: bool = True,
        over_cap: float = 0.0,
        margin: float = 1.0,
        max_trades: int = 3,
        min_gain: float = 0.15,
        spend_youth: bool = True,
        label: str | None = None,
    ) -> None:
        self.extend = extend
        self.sign = sign
        self.buy = buy
        self.two_goalies = two_goalies
        self.over_cap = over_cap
        self.margin = margin
        self.max_trades = max_trades
        self.min_gain = min_gain
        self.spend_youth = spend_youth
        if label:
            self.name = label
        self._window: tuple[int, str] | None = None
        self._stage = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        window = (int(observation["season"]), observation["phase"])
        if window != self._window:
            self._window, self._stage = window, 0
        team = observation["team"]
        rosters = {
            int(result["data"]["team"]["id"]): result["data"]["roster"]
            for result in observation.get("action_results") or []
            if result.get("accepted")
            and (result.get("action") or {}).get("type") == "inspect_team"
            and isinstance(result.get("data"), dict)
            and result["data"].get("team", {}).get("id") != team["id"]
        }
        if self._stage == 0 and self.buy and not rosters:
            self._stage = 1
            return [
                {"type": "inspect_team", "team_id": row["team_id"]}
                for row in observation.get("standings") or []
                if row["team_id"] != team["id"]
            ]
        if self._stage <= 1:
            self._stage = 2
            moves = self._moves(observation, rosters)
            if moves:
                return [*moves, {"type": "inspect_team", "team_id": team["id"]}]
        self._stage = 3
        lineup = best_lineup(team["roster"], two_goalies=self.two_goalies)
        if lineup_is_legal(lineup):
            return [{"type": "set_lineup", "player_ids": [p["id"] for p in lineup]}]
        return []

    def _moves(self, observation: dict[str, Any], rosters: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        phase = observation["phase"]
        season = int(observation["season"])
        team = observation["team"]
        rules = observation["rules"]
        cap = float(rules["salary_cap"])
        hard_cap = cap + float(rules.get("hard_cap_buffer", 8.0))
        spend_cap = min(hard_cap, cap + self.over_cap)
        roster = [dict(p) for p in team["roster"]]
        payroll = float(team["payroll"])
        actions: list[dict[str, Any]] = []

        def strength(players: list[dict[str, Any]], pay: float) -> float:
            return lineup_strength(players, pay, cap, two_goalies=self.two_goalies)

        if phase == "preseason" and self.extend:
            core = {p["id"] for p in dressed(roster, two_goalies=self.two_goalies)}
            years = contract_years_to_end(season, extension=True)
            for player in sorted(roster, key=lambda p: -p["overall"]):
                quotes = player.get("extension_quotes")
                if not quotes or player["id"] not in core:
                    continue
                salary = float(quotes[str(years)])
                if payroll - player["salary"] + salary > hard_cap:
                    continue
                actions.append({"type": "extend_contract", "player_id": player["id"], "years": years, "salary": salary})
                payroll += salary - player["salary"]
                player["salary"] = salary

        pool: list[tuple[str, dict[str, Any]]] = [
            ("sign_free_agent", p) for p in observation.get("free_agents") or [] if not p.get("resign_blocked")
        ]
        if phase == "midseason":
            pool += [("claim_waiver", p) for p in observation.get("waiver_wire") or [] if not p.get("resign_blocked")]
        signed: set[int] = set()
        for _ in range(4 if self.sign else 0):
            here = strength(roster, payroll)
            best: tuple[float, str, dict[str, Any], int, float] | None = None
            for kind, player in pool:
                if player["id"] in signed:
                    continue
                years = 1 if kind == "claim_waiver" else contract_years_to_end(season)
                salary = (
                    float(player["contract_quotes"][str(years)])
                    if kind == "sign_free_agent"
                    else float(player["asking_salary"])
                )
                if payroll + salary > spend_cap:
                    continue
                gain = strength([*roster, {**player, "salary": salary}], payroll + salary) - here
                if gain >= self.min_gain and (best is None or gain > best[0]):
                    best = (gain, kind, player, years, salary)
            if best is None:
                break
            _gain, kind, player, years, salary = best
            if kind == "claim_waiver":
                actions.append({"type": "claim_waiver", "player_id": player["id"]})
            else:
                actions.append({"type": "sign_free_agent", "player_id": player["id"], "years": years, "salary": salary})
            signed.add(player["id"])
            roster.append({**player, "salary": salary, "contract_years": years})
            payroll += salary

        if self.buy and rosters:
            actions += plan_buys(
                observation,
                rosters,
                roster,
                payroll,
                two_goalies=self.two_goalies,
                over_cap=self.over_cap,
                margin=self.margin,
                max_trades=self.max_trades,
                min_gain=self.min_gain,
                spend_youth=self.spend_youth,
            )

        if phase == "draft" and observation.get("draft_class"):
            picks = team.get("draft_picks") or {}
            held = int(picks.get(season, picks.get(str(season), 0)) or 0)
            prospects = sorted(observation["draft_class"], key=public_asset_value, reverse=True)
            for prospect in prospects[:held]:
                actions.append({"type": "draft", "prospect_id": prospect["id"]})
        return actions


def extension_moves(observation: dict[str, Any], *, two_goalies: bool = True) -> dict[str, list[dict[str, Any]]]:
    """Preseason extensions built from the observation's published quotes.

    One move per extension-eligible player in the lineup (best four by
    overall), plus ``extend-core``, which extends all of them. Each runs for
    the shortest term that keeps the player past the final season; the
    published incumbent quote is always accepted.
    """
    if observation["phase"] != "preseason":
        return {}
    team = observation["team"]
    cap = float(observation["rules"]["salary_cap"])
    hard_cap = cap + float(observation["rules"].get("hard_cap_buffer", 8.0))
    years = contract_years_to_end(int(observation["season"]), extension=True)
    core = {p["id"] for p in dressed(team["roster"], two_goalies=two_goalies)}
    eligible = sorted(
        (p for p in team["roster"] if p.get("extension_quotes") and p["id"] in core),
        key=lambda p: (-p["overall"], p["id"]),
    )
    moves: dict[str, list[dict[str, Any]]] = {}
    payroll = float(team["payroll"])
    everyone: list[dict[str, Any]] = []
    for player in eligible:
        salary = float(player["extension_quotes"][str(years)])
        if payroll - player["salary"] + salary > hard_cap:
            continue
        action = {"type": "extend_contract", "player_id": player["id"], "years": years, "salary": salary}
        if len(moves) < 4:
            moves[f"extend:{player['id']}:{years}y"] = [action]
        everyone.append(action)
        payroll += salary - player["salary"]
    if len(everyone) > 1:
        moves["extend-core"] = everyone
    return moves


def buy_moves(
    observation: dict[str, Any],
    rosters: dict[int, list[dict[str, Any]]],
    *,
    two_goalies: bool = True,
    count: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Up to ``count`` single trades for other teams' players who raise lineup strength now."""
    if observation["phase"] not in ("preseason", "midseason", "trade_deadline"):
        return {}
    team = observation["team"]
    moves: dict[str, list[dict[str, Any]]] = {}
    seen: set[int] = set()
    for _ in range(count):
        trades = plan_buys(
            observation,
            rosters,
            [dict(p) for p in team["roster"]],
            float(team["payroll"]),
            two_goalies=two_goalies,
            over_cap=0.0,
            margin=1.0,
            max_trades=1,
            min_gain=0.15,
            spend_youth=True,
            exclude_ids=frozenset(seen),
        )
        if not trades:
            break
        target = trades[0]["receive_player_ids"][0]
        seen.add(target)
        moves[f"buy-now:{target}"] = trades
    return moves


def win_now_policies(*, two_goalies: bool = True) -> dict[str, Any]:
    """The win-now family as fresh-agent factories, keyed by menu name."""
    suffix = "" if two_goalies else "-1g"
    variants: dict[str, dict[str, Any]] = {
        "contend": {},
        "contend-nobuy": {"buy": False},
        "contend-extend": {"buy": False, "sign": False},
    }
    return {
        f"{name}{suffix}": (
            lambda kwargs=kwargs, label=f"{name}{suffix}": Contender(two_goalies=two_goalies, label=label, **kwargs)
        )
        for name, kwargs in variants.items()
    }


WIN_NOW_POLICIES: dict[str, Any] = {**win_now_policies(two_goalies=True), **win_now_policies(two_goalies=False)}


class PhaseMix(Agent):
    """One policy per phase, each keeping its own state across the episode."""

    def __init__(self, by_phase: dict[str, str], label: str) -> None:
        self.by_phase = by_phase
        self.name = label
        self._agents: dict[str, Agent] = {}

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        policy = self.by_phase[observation["phase"]]
        if policy not in self._agents:
            self._agents[policy] = policy_factory(policy)()
        return self._agents[policy].act(observation)


# Reference rows for the policy mode only; not on any search menu. The fair
# planner's paths mix win-now preseasons with pick-trader's in-season play;
# these are that mix written as fixed scripted policies.
MIXED_POLICIES: dict[str, Any] = {
    f"{policy}-preseason{suffix}": (
        lambda policy=policy, suffix=suffix: PhaseMix(
            {phase: f"{policy}{suffix}" if phase == "preseason" else "pick-trader" for phase in PHASES},
            f"{policy}-preseason{suffix}",
        )
    )
    for policy in ("contend", "contend-nobuy")
    for suffix in ("", "-1g")
}


def policy_factory(name: str) -> Any:
    """A fresh-agent factory for a registered scripted policy or a win-now policy."""
    if name in WIN_NOW_POLICIES:
        return WIN_NOW_POLICIES[name]
    if name in MIXED_POLICIES:
        return MIXED_POLICIES[name]
    return AGENTS[name]


def play_counts(baseline: Any, league: Any) -> dict[str, Any]:
    """Wins and the user's moves, for explaining a lift (rows of non-default runs only)."""

    def counts(played: Any) -> dict[str, int]:
        own = [t for t in played.transactions if t.team_id == played.user_team_id and t.accepted]
        kinds = ("extend_contract", "sign_free_agent", "trade", "release", "claim_waiver", "accept_trade_offer")
        return {kind: sum(t.action.get("type") == kind for t in own) for kind in kinds}

    return {
        "wins": sum(summary.wins for summary in league.summaries),
        "baseline_wins": sum(summary.wins for summary in baseline.summaries),
        "illegal_actions": league.illegal_actions,
        "baseline_illegal_actions": baseline.illegal_actions,
        "rejected_offers": league.rejected_offers,
        "moves": counts(league),
        "baseline_moves": counts(baseline),
        "roster_at_end": len(league.user_team.roster),
        "baseline_roster_at_end": len(baseline.user_team.roster),
    }


END_STATE_TERMS = ("total_assets", "young_assets", "future_pick_assets", "cap_room", "current_strength", "roster_depth")
CONTINUATION_SEASONS = 5


def continuation(baseline: Any, league: Any, play_step: Any, manager: str = "pick-trader") -> dict[str, float]:
    """Do the end-state terms turn into later wins? (``score_deep_dive.py continuation21``'s check.)

    Copies of both final leagues are handed to ``manager`` for five more
    seasons. The dice are drawn on a fixed schedule, so the two continue
    under the same dice. Each side's later winning value is scored with
    score-v2's winning weights (wins, expected rounds and titles, every
    season); the row records it next to the end-state terms it should match.
    """
    out: dict[str, float] = {}
    for key, played in (("baseline_", baseline), ("", league)):
        parts = scoring_v2.score_components(played, played.user_team_id)
        out[f"{key}end_state"] = round(sum(parts[f"{term}_contribution"] for term in END_STATE_TERMS), 3)
        future = copy.deepcopy(played)
        agent = policy_factory(manager)()
        start = len(future.summaries)
        for _season in range(CONTINUATION_SEASONS):
            for index in range(len(PHASES)):
                play_step(future, agent, index)
        scale = scoring_v2.SCALE
        value = 0.0
        for summary in future.summaries[start:]:
            rounds, title = future.expected_playoffs[summary.season].get(future.user_team_id, (0.0, 0.0))
            value += summary.wins * scale.season_win + rounds * scale.playoff_round + title * scale.championship
        out[f"{key}continuation_winning"] = round(value, 3)
    return out
