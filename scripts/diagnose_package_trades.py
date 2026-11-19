#!/usr/bin/env python3
"""The package-trade exploit: who used it, a scripted replica, and the rules tried against it.

The 2026-11-18 pilot showed ``gpt-6.1-sol`` signing free agents in bulk and
trading packages of them to rivals for their best young players. The rival's
side of ``League._trade`` sums the asset value of every player it receives,
and a free agent it could have signed itself counts in full. This script
answers three questions, with no model calls:

1. **Did a published 2.1 row use it?** Each 2.1 panel ledger is read (not
   replayed) for its accepted trades, its signings, and the players it sent
   in a trade in the season it signed them. Only per-model aggregates are
   written: the panel's seeds and per-episode scores are private.
2. **Can a script reproduce it?** ``play`` runs a scripted base policy and,
   after each of its decisions, signs free agents and offers packages of them
   for rivals' cheap high-value players. It reads asset values from the
   league but not the partner's hidden bias, and adapts to the rule in force
   through ``counted``. ``carry`` also stocks free agents in the draft phase
   to trade the season after, the way around a same-season rule.
3. **Which rule closes it?** The replica and three scripted references are
   played on public seeds under 2.2 as the pilot ran it (``unfixed``), under
   each candidate, and under ``League22`` as it now stands (``fixed``).

Usage::

    python scripts/diagnose_package_trades.py [--v21-runs ~/gmb-runs/<2.1 run> ...] \\
        [--out results/diagnostics/package_trades/report.json]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import ceiling_search  # noqa: E402
import score_v3_candidates as candidates  # noqa: E402

from gm_bench.runner import run_decision_point  # noqa: E402
from gm_bench.simulator import HARD_CAP_BUFFER, TRADE_LIMIT_PER_PARTNER  # noqa: E402
from gm_bench.v22 import scoring as score_v3  # noqa: E402
from gm_bench.v22.rules import League22  # noqa: E402

OUT = ROOT / "results" / "diagnostics" / "package_trades" / "report.json"
ROWS = ROOT / "results" / "agentic_v21"
PILOT = ROOT / "results" / "diagnostics" / "v22_pilot" / "behavior.json"
SEEDS = tuple(range(201, 209))  # the pilot's public seeds
REFERENCES = ("pick-trader", "contend-preseason-1g", "strategic")
REPLICA_BASES = ("pick-trader", "contend-preseason-1g")
FILLER_YEARS = 2
STOCK_YEARS = 3
TARGET_MIN_ASSET = 15.0
TARGET_MAX_SALARY = 3.0
MARGIN = 1.25  # the replica cannot see the partner's bias (0.9 to 1.1), so it overpays


# --------------------------------------------------------------------------
# 1. Ledgers
# --------------------------------------------------------------------------


def trade_profile(ledger_path: Path) -> dict[str, int]:
    """Accepted trades, signings, and same-season signings sent away, from the ledger alone."""
    signed: dict[int, int] = {}
    profile = {
        "accepted_trades": 0,
        "free_agent_signings": 0,
        "most_players_sent_in_one_trade": 0,
        "same_season_signings_sent": 0,
        "most_same_season_signings_in_one_trade": 0,
    }
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line) if line.strip() else {}
        if record.get("event") != "tool_call" or not (record.get("ok") and record.get("executed", True)):
            continue
        arguments = record.get("arguments") if isinstance(record.get("arguments"), dict) else {}
        if record["tool"] == "sign_free_agent":
            profile["free_agent_signings"] += 1
            signed[arguments.get("player_id")] = record["season"]
        elif record["tool"] == "trade":
            sent = arguments.get("give_player_ids") if isinstance(arguments.get("give_player_ids"), list) else []
            fresh = sum(1 for player_id in sent if signed.get(player_id) == record["season"])
            profile["accepted_trades"] += 1
            profile["most_players_sent_in_one_trade"] = max(profile["most_players_sent_in_one_trade"], len(sent))
            profile["same_season_signings_sent"] += fresh
            profile["most_same_season_signings_in_one_trade"] = max(
                profile["most_same_season_signings_in_one_trade"], fresh
            )
    return profile


def _summary(profiles: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "episodes": len(profiles),
        **{
            key: {"mean": round(statistics.fmean(p[key] for p in profiles), 2), "max": max(p[key] for p in profiles)}
            for key in profiles[0]
        },
        "episodes_sending_4_or_more_same_season_signings_in_one_trade": sum(
            1 for p in profiles if p["most_same_season_signings_in_one_trade"] >= 4
        ),
    }


def survey_v21(run_dirs: list[Path]) -> dict[str, Any]:
    rows = {json.loads(p.read_text(encoding="utf-8"))["agent"]: p for p in sorted(ROWS.glob("*.json"))}
    models, skipped = {}, []
    for run_dir in run_dirs:
        run_json = run_dir / "run.json"
        agent = json.loads(run_json.read_text(encoding="utf-8"))["agent"] if run_json.exists() else None
        dirs = sorted(run_dir.glob("episode-*"))
        row = json.loads(rows[agent].read_text(encoding="utf-8")) if agent in rows else None
        if row is None or len(dirs) != len(row["episodes"]):
            skipped.append(run_dir.name)
            continue
        model = agent.split(":", 1)[1].rsplit("/", 1)[-1]
        models[model] = {
            "row": rows[agent].relative_to(ROOT).as_posix(),
            **_summary([trade_profile(d / "ledger.jsonl") for d in dirs]),
        }
    return {"models": models, "skipped_runs": skipped}


# --------------------------------------------------------------------------
# 3. Rules (declared before the replica, which asks the rule what counts)
# --------------------------------------------------------------------------


class Unfixed(League22):
    """2.2 as the pilot ran it: a rival pays full value for every player it receives."""

    def _acquired_free_this_season(self, player_id: int | str) -> bool:
        return False

    def counted(self, partner: Any, incoming: list[tuple[float, Any, bool]], sends: int) -> float:
        """The replica's estimate of what ``partner`` counts: (asset value, player, signed for this trade)."""
        return sum(value for value, _player, _new in incoming)

    def factors(self, partner_id: int, give: list[int], sends: int) -> dict[int, float]:
        """What the partner counts each incoming player at, as a factor on his asset value."""
        return {}

    def _trade(self, action: dict[str, Any], phase: str) -> None:
        partner_id, give = action.get("partner_team_id"), action.get("give_player_ids") or []
        sends = len(action.get("receive_player_ids") or []) + len(action.get("receive_pick_seasons") or [])
        valid = partner_id in self.teams and all(player_id in self.players for player_id in give)
        self._factors = self.factors(partner_id, give, sends) if valid else {}
        try:
            super()._trade(action, phase)
        finally:
            self._factors = {}

    def _partner_valuation_bias(self, partner_id: int, player_id: int | str) -> float:
        factor = getattr(self, "_factors", {}).get(player_id, 1.0)
        return super()._partner_valuation_bias(partner_id, player_id) * factor


class RosterMax(Unfixed):
    """A trade may not put the rival's roster above ``MAX`` (no scripted reference's rival exceeds 25)."""

    MAX = 26

    def counted(self, partner: Any, incoming: list[tuple[float, Any, bool]], sends: int) -> float:
        room = max(sends, self.MAX - len(partner.roster) + sends)
        return sum(sorted((value for value, _p, _n in incoming), reverse=True)[:room])

    def _trade(self, action: dict[str, Any], phase: str) -> None:
        partner = self.teams.get(action.get("partner_team_id"))
        if partner is not None and partner.id != self.user_team_id:
            after = (
                len(partner.roster)
                + len(action.get("give_player_ids") or [])
                - len(action.get("receive_player_ids") or [])
            )
            if after > self.MAX and after > len(partner.roster):
                self._record(action, phase, False, f"trade would put partner roster above {self.MAX} players")
                return
        super()._trade(action, phase)


class RosterMax24(RosterMax):
    MAX = 24


class LineupOnly(Unfixed):
    """The rival counts an incoming player only if he would dress for it (top 18 by overall)."""

    def _bar(self, partner: Any, leaving: tuple[int, ...] = ()) -> float:
        overalls = sorted((self.players[i].overall for i in partner.roster if i not in leaving), reverse=True)
        return overalls[17] if len(overalls) >= 18 else 0.0

    def counted(self, partner: Any, incoming: list[tuple[float, Any, bool]], sends: int) -> float:
        bar = self._bar(partner)
        return sum(value for value, player, _new in incoming if player.overall > bar)

    def factors(self, partner_id: int, give: list[int], sends: int) -> dict[int, float]:
        bar = self._bar(self.teams[partner_id])
        return {player_id: 0.0 for player_id in give if self.players[player_id].overall <= bar}


class CountLimit(Unfixed):
    """The rival counts only its best incoming players: as many as the assets it sends, plus ``EXTRA``."""

    EXTRA = 1

    def counted(self, partner: Any, incoming: list[tuple[float, Any, bool]], sends: int) -> float:
        return sum(sorted((value for value, _p, _n in incoming), reverse=True)[: sends + self.EXTRA])

    def factors(self, partner_id: int, give: list[int], sends: int) -> dict[int, float]:
        bias = super()._partner_valuation_bias
        ranked = sorted(give, key=lambda i: -self.players[i].asset_value * bias(partner_id, i))
        return {player_id: 0.0 for player_id in ranked[sends + self.EXTRA :]}


class CountLimit0(CountLimit):
    EXTRA = 0


class Fixed(League22):
    """``League22`` as it stands: no value for a player signed or claimed this season."""

    def counted(self, partner: Any, incoming: list[tuple[float, Any, bool]], sends: int) -> float:
        return sum(
            value for value, player, new in incoming if not new and not self._acquired_free_this_season(player.id)
        )


RULES: dict[str, type] = {
    "unfixed": Unfixed,
    "roster-max-26": RosterMax,
    "roster-max-24": RosterMax24,
    "lineup-only": LineupOnly,
    "count-limit-plus-1": CountLimit,
    "count-limit-plus-0": CountLimit0,
    "fixed": Fixed,
}


# --------------------------------------------------------------------------
# 2. The replica
# --------------------------------------------------------------------------


def _asset_if_signed(player: Any, salary: float) -> float:
    """``Player.asset_value`` once he is under contract at ``salary`` (checked in the tests)."""
    age_factor = max(0.05, 1.18 - max(player.age - 23, 0) * 0.055)
    contract_factor = 1.0 + max(-10.0, player.overall - 52.0 - salary * 2.5) * 0.018
    return max(0.0, (player.overall * 0.55 + player.potential * 0.45 - 45.0) * age_factor * contract_factor)


def _select(
    league: Any,
    partner: Any,
    pool: list[tuple[float, float, int, bool]],
    need: float,
    user_room: float,
    partner_room: float,
    by_gain: bool,
) -> tuple[list[tuple[int, float, bool]], float]:
    """Add players to the package until the rule in force counts ``need`` of value, or nothing more helps."""
    chosen: list[tuple[int, float, bool]] = []
    incoming: list[tuple[float, Any, bool]] = []
    counted = 0.0
    while counted < need:
        best = None
        for asset, salary, player_id, new in pool:
            if any(player_id == c[0] for c in chosen):
                continue
            if new and sum(c[1] for c in chosen if c[2]) + salary > user_room:
                continue
            if sum(c[1] for c in chosen) + salary > partner_room:
                continue
            gain = league.counted(partner, [*incoming, (asset, league.players[player_id], new)], 1) - counted
            rank = gain if by_gain else gain / ((salary if new else 0.0) + 0.05)
            if gain > 1e-9 and (best is None or rank > best[0]):
                best = (rank, asset, salary, player_id, new, gain)
        if best is None:
            break
        _rank, asset, salary, player_id, new, gain = best
        chosen.append((player_id, salary, new))
        incoming.append((asset, league.players[player_id], new))
        counted += gain
    return chosen, counted


def _offer_packages(league: Any, phase: str, stats: dict[str, int], stocked: set[int]) -> None:
    user, hard_cap = league.user_team, league.cap + HARD_CAP_BUFFER
    targets = sorted(
        (
            (league.players[player_id].asset_value, team.id, player_id)
            for team in league.teams.values()
            if team.id != user.id
            for player_id in team.roster
            if league.players[player_id].asset_value >= TARGET_MIN_ASSET
            and league.players[player_id].salary <= TARGET_MAX_SALARY
        ),
        reverse=True,
    )
    declined: set[int] = set()
    for value, partner_id, target_id in targets:
        partner = league.teams[partner_id]
        if (
            league.partner_trades.get(partner_id, 0) >= TRADE_LIMIT_PER_PARTNER
            or partner_id in declined
            or target_id not in partner.roster
        ):
            continue
        market = []
        for player_id in league.free_agents:
            player = league.players[player_id]
            if league._resign_blocked(user.id, player_id):
                continue
            quote = league._signing_quote(player, FILLER_YEARS)
            asset = _asset_if_signed(player, quote)
            if asset > 1.0:
                market.append((asset, quote, player_id, True))
        pool = sorted(market, key=lambda c: -c[0])[:80] + sorted(market, key=lambda c: -c[0] / c[1])[:80]
        pool += [
            (league.players[i].asset_value, league.players[i].salary, i, False) for i in stocked if i in user.roster
        ]
        user_room = hard_cap - league._payroll(user)
        partner_room = hard_cap - league._payroll(partner) + league.players[target_id].salary
        need = value * MARGIN
        # Cheapest first; if a rule limits how many players count, the most valuable first.
        for by_gain in (False, True):
            chosen, counted = _select(league, partner, pool, need, user_room, partner_room, by_gain)
            if counted >= need:
                break
        if counted < need:
            continue
        signings = [
            {"type": "sign_free_agent", "player_id": player_id, "salary": salary, "years": FILLER_YEARS}
            for player_id, salary, new in chosen
            if new
        ]
        results = league.apply_actions(signings, phase)
        give = [a["player_id"] for a, r in zip(signings, results, strict=True) if r.accepted]
        give += [player_id for player_id, _salary, new in chosen if not new]
        stats["signings"] += len(signings)
        trade = {
            "type": "trade",
            "partner_team_id": partner_id,
            "give_player_ids": give,
            "receive_player_ids": [target_id],
        }
        if league.apply_actions([trade], phase)[0].accepted:
            stats["accepted_trades"] += 1
            stats["most_players_sent_in_one_trade"] = max(stats["most_players_sent_in_one_trade"], len(give))
        else:
            declined.add(partner_id)
            stocked.update(give)


def _stock(league: Any, phase: str, stats: dict[str, int], stocked: set[int]) -> None:
    """Sign free agents in the draft phase to trade next season, when a same-season rule no longer covers them."""
    user = league.user_team
    market = []
    for player_id in league.free_agents:
        player = league.players[player_id]
        quote = league._signing_quote(player, STOCK_YEARS)
        asset = _asset_if_signed(player, quote)
        if asset > 3.0:
            market.append((asset / quote, quote, player_id))
    room, actions = league.cap + HARD_CAP_BUFFER - league._payroll(user), []
    for _rate, quote, player_id in sorted(market, reverse=True)[:40]:
        if sum(a["salary"] for a in actions) + quote <= room:
            actions.append({"type": "sign_free_agent", "player_id": player_id, "salary": quote, "years": STOCK_YEARS})
    for action, result in zip(actions, league.apply_actions(actions, phase), strict=True):
        if result.accepted:
            stocked.add(action["player_id"])
            stats["signings"] += 1


def play(seed: int, base: str, rule: str, mode: str = "none") -> tuple[float, dict[str, int]]:
    """``base`` on ``seed`` under ``rule``; ``mode`` is none (the base alone), replica or carry."""
    league = RULES[rule].new(seed=seed)
    agent = candidates.make_agent(base)
    stats = {"accepted_trades": 0, "signings": 0, "most_players_sent_in_one_trade": 0}
    stocked: set[int] = set()
    for index, (season, phase) in enumerate(ceiling_search.STEPS):
        ceiling_search._pre_step(league, index)
        run_decision_point(league, agent, phase, ceiling_search.CONFIG)
        if mode != "none" and phase != "draft":
            _offer_packages(league, phase, stats, stocked)
        if mode == "carry" and phase == "draft" and season < ceiling_search.SEASONS:
            _stock(league, phase, stats, stocked)
        ceiling_search._finish_step(league, index)
    return score_v3.score_team(league, league.user_team_id), stats


def _job(job: tuple[str, int]) -> dict[str, Any]:
    rule, seed = job
    out: dict[str, Any] = {"rule": rule, "seed": seed}
    for base in REFERENCES:
        out[base] = play(seed, base, rule)[0]
    for base in REPLICA_BASES:
        for mode in ("replica", "carry"):
            out[f"{mode}:{base}"], out[f"{mode}-stats:{base}"] = play(seed, base, rule, mode)
    return out


def compare_rules(seeds: tuple[int, ...], jobs: int) -> dict[str, Any]:
    with multiprocessing.Pool(jobs) as pool:
        results = pool.map(_job, [(rule, seed) for rule in RULES for seed in seeds])
    report = {}
    for rule in RULES:
        rows = [r for r in results if r["rule"] == rule]
        reference = statistics.fmean(r["pick-trader"] for r in rows)

        def lift(key: str, rows: list[dict[str, Any]] = rows, reference: float = reference) -> float:
            return round(statistics.fmean(r[key] for r in rows) - reference, 1)

        block: dict[str, Any] = {
            "description": " ".join((RULES[rule].__doc__ or "").split()),
            "pick_trader_mean_score": round(reference, 1),
            "lift_over_pick_trader": {name: lift(name) for name in REFERENCES[1:]},
        }
        for mode in ("replica", "carry"):
            for base in REPLICA_BASES:
                stats = [r[f"{mode}-stats:{base}"] for r in rows]
                block[f"{mode}_on_{base}"] = {
                    "lift_over_pick_trader": lift(f"{mode}:{base}"),
                    "gain_over_its_base": round(
                        lift(f"{mode}:{base}") - (lift(base) if base != "pick-trader" else 0), 1
                    ),
                    "largest_gain_over_its_base_on_a_seed": round(max(r[f"{mode}:{base}"] - r[base] for r in rows), 1),
                    "accepted_trades_per_episode": round(statistics.fmean(s["accepted_trades"] for s in stats), 1),
                    "signings_per_episode": round(statistics.fmean(s["signings"] for s in stats), 1),
                    "most_players_sent_in_one_trade": max(s["most_players_sent_in_one_trade"] for s in stats),
                }
        report[rule] = block
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--v21-runs", nargs="*", type=Path, default=[], help="2.1 raw panel run directories")
    parser.add_argument("--pilot-runs", nargs="*", type=Path, default=[], help="2.2-draft pilot run directories")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    report: dict[str, Any] = {
        "note": (
            "v21_rows holds per-model aggregates only: the panel's seeds and per-episode scores are private. "
            "rules is played on public seeds; the replica reads asset values from the league, so it is a "
            "test of the rule, not a policy an agent could run as written."
        ),
        "seeds": list(SEEDS),
    }
    if args.v21_runs:
        report["v21_rows"] = survey_v21([run.expanduser() for run in args.v21_runs])
    pilot = {}
    for run_dir in (run.expanduser() for run in args.pilot_runs):
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        model = run["agent"].split(":", 1)[1].rsplit("/", 1)[-1]
        for episode in run["episodes"]:
            profile = trade_profile(run_dir / f"seed-{episode['seed']}" / "ledger.jsonl")
            pilot.setdefault(model, []).append({"seed": episode["seed"], **profile})
    if pilot:
        report["pilot_2_2_before_the_fix"] = pilot
    report["rules"] = compare_rules(SEEDS, args.jobs)
    for rule, block in report["rules"].items():
        replica = block["replica_on_contend-preseason-1g"]
        carry = block["carry_on_contend-preseason-1g"]
        print(
            f"{rule:20s} pick-trader {block['pick_trader_mean_score']:6.1f}  contender "
            f"{block['lift_over_pick_trader']['contend-preseason-1g']:+6.1f}  replica on it "
            f"{replica['lift_over_pick_trader']:+6.1f} (gain {replica['gain_over_its_base']:+.1f})  carry gain "
            f"{carry['gain_over_its_base']:+.1f}  replica on pick-trader "
            f"{block['replica_on_pick-trader']['lift_over_pick_trader']:+6.1f}"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
