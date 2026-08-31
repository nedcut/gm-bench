from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent
from gm_bench.benchmark_config import PRESETS
from gm_bench.contract import contract_fingerprint
from gm_bench.oracle import OracleAgent
from gm_bench.runner import run_many


def test_oracle_preserves_frozen_contract_fingerprint() -> None:
    # The current sota-v3 fingerprint moved for contract economics: dead cap,
    # term-priced free agency, incumbent extensions, and market/cap inflation.
    # Frozen sota-v2 remains pinned separately in SOTA_V2_CONTRACT.
    #
    # The fingerprint hashes raw source bytes, so docstrings and comments in a
    # _CONTRACT_SOURCES file move it too. That is deliberately cheap before a
    # panel is bought and impossible afterward.
    # Moved again when protocol.py entered the fingerprint, built-in model
    # adapters gained the complete canonical action surface, and malformed
    # action discriminators were made fail-closed at the simulator boundary.
    # Private seeds remain internal to the trusted harness; model prompts,
    # adapter transports, and child environments no longer expose them.
    # Moved again for the v6 draft lottery: draft order is drawn from the
    # seeded RNG over the non-playoff teams, and traded picks carry their
    # original team's identity through the observation and the draft.
    # Moved again for v6 free-agent willingness: quotes and reservations now
    # carry the published signing_appeal multiplier (team record, lineup role,
    # veteran win sensitivity), and opponent signings price the same way.
    # Moved again for v6 lineup construction: forwards now carry a published
    # center-or-wing sub_position, and a dressed lineup earns a bonus for
    # having enough natural centers.
    # Moved again for v6 expiring contracts: an unresigned expiring incumbent
    # now enters an immediate rival scramble for the best expiring players
    # leaguewide before the user's next decision window.
    # Moved again for v6 dead-field removal: the inert morale, market, and
    # patience fields (never read by any mechanic) are gone from the model,
    # generator, and observation.
    # Moved again for the release-then-re-sign fix: a team may not sign back a
    # player it released until the next season, so releasing an expiring
    # incumbent can no longer undercut his extension quote.
    # Moved again when that block was made per (team, player) rather than one
    # team per player, so a rival's later drop cannot erase it, and when waiver
    # claims started enforcing it alongside free-agent signings.
    # Moved again for the v6 compact observation render: the model view is now
    # pipe-delimited tables inside the ~6,500-token budget, the candidate lists
    # it carries are shorter, and the transaction ledger publishes two seasons
    # of roster-changing moves instead of the last twelve transactions.
    # Moved again for the v6 execution rules: one paid model call per decision
    # phase, no paid retry, and deterministic local repair of malformed output
    # (gm_bench/repair.py) with a structured no-op when intent is ambiguous.
    assert contract_fingerprint() == "3167d95f860770c5"
    assert "oracle" not in AGENTS


def test_oracle_hidden_information_shows_without_illegal_actions() -> None:
    """Hidden information must still be visible in behavior, deterministically.

    History: this test once asserted `oracle mean_score > pick-trader
    mean_score` on the 8-seed public panel (it had earlier been weakened to
    `!=`, a tautology, and was restored). The v6 draft-lottery reroll exposed
    that ordering as seed luck: on the 24-seed canary panel the paired
    oracle-minus-pick-trader difference was +4.9 (SD 56.8) before the lottery
    and -10.0 (SD 56.2) after -- unresolved noise both times, far inside the
    benchmark's own ~30-point minimum detectable difference. Re-pinning the
    8-seed ordering would launder a coin flip as a guarantee.

    What perfect hidden-threshold knowledge does guarantee, on every seed:

    - the oracle never has a negotiation rejected (it computes the exact
      reservation and valuation thresholds the public policy must probe), and
    - regenerated latent potential changes at least one draft-day decision
      relative to the public policy it inherits.

    If a future mechanic breaks either invariant, hidden information has
    genuinely stopped mattering and that should be discussed, not relaxed.
    """
    seeds = list(PRESETS["leaderboard"]["seeds"])
    oracle = run_many(OracleAgent(), seeds=seeds, seasons=5, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=seeds, seasons=5, workers=1)
    assert oracle["summary"]["illegal_actions"] == 0
    assert oracle["summary"]["rejected_offers"] == 0
    assert pick_trader["summary"]["rejected_offers"] > 0

    def drafted(result: dict) -> dict[int, list[int]]:
        picks: dict[int, list[int]] = {}
        for episode in result["episodes"]:
            picks[episode["seed"]] = [
                transaction["action"]["prospect_id"]
                for transaction in episode["transactions"]
                if transaction["team_id"] == 0
                and transaction["accepted"]
                and transaction["action"].get("type") == "draft"
            ]
        return picks

    assert drafted(oracle) != drafted(pick_trader)
