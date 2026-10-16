"""The 2.1 agentic episode: the frozen 2.0 engine on the 2.1 league and score.

Contract source for 2.1 (fingerprinted by ``gm_bench.v21.contract``).
``AgenticEpisode`` is a 2.0 contract source and stays byte for byte; this
subclass changes only what 2.1 changes. The tool surface, the brief, the
phase calendar, the guard and the ledger format are 2.0's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.scoring import breakdown_from_components
from gm_bench.v21.contract import BENCHMARK_VERSION
from gm_bench.v21.rules import League21
from gm_bench.v21.scoring import SCORING_VERSION, persisted_score_components, score_components


class AgenticEpisode21(AgenticEpisode):
    def _open_phase(self) -> None:
        # The 2.0 constructor builds a ``League`` and opens the first phase
        # straight away. Nothing has been played when that first call
        # arrives, and ``League.new`` is a pure function of the seed, so
        # swapping in the 2.1 league here starts the same league under the
        # 2.1 rules.
        if not isinstance(self.league, League21):
            self.league = League21.new(seed=self.seed, user_team_id=self.user_team_id)
        super()._open_phase()

    def _write(self, record: dict[str, Any]) -> None:
        # The ledger header names its contract, so a replay picks this engine.
        if record.get("event") == "episode":
            record = {**record, "benchmark_version": BENCHMARK_VERSION}
        super()._write(record)

    def result(self, agent_name: str = "agentic") -> dict[str, Any]:
        payload = super().result(agent_name)
        components = score_components(self.league, self.user_team_id)
        breakdown = breakdown_from_components(components)
        payload.update(
            final_score=round(breakdown["final_score"], 3),
            strategy_score=round(breakdown["strategy_score"], 3),
            protocol_penalty=round(breakdown["protocol_penalty"], 3),
            score_components=persisted_score_components(components),
            scoring_version=SCORING_VERSION,
            benchmark_version=BENCHMARK_VERSION,
        )
        return payload


def ledger_benchmark_version(ledger_path: str | Path) -> str:
    """The contract a ledger was played under; 2.0 ledgers predate the field."""
    import json

    with Path(ledger_path).open(encoding="utf-8") as handle:
        header = json.loads(handle.readline() or "{}")
    return str(header.get("benchmark_version") or "gm-bench-2.0")
