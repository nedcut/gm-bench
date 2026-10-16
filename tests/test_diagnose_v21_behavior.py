import json
import sys
from pathlib import Path

import pytest

from gm_bench.v21.episode import AgenticEpisode21

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diagnose_v21_behavior as diagnose  # noqa: E402


def _play(ledger: Path, *, read_status: bool) -> float:
    """A public-seed 2.1 episode that never moves: optionally get_status, then end_phase, 20 times."""
    episode = AgenticEpisode21(11, ledger_path=ledger)
    while not episode.done:
        if read_status:
            episode.call_tool("get_status", {})
        episode.call_tool("end_phase", {})
    episode.close()
    return episode.result()["final_score"]


def _run(tmp_path: Path, name: str, agent: str, *, read_status: bool) -> tuple[Path, dict]:
    run = tmp_path / name
    (run / "episode-00").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"agent": agent}))
    score = _play(run / "episode-00" / "ledger.jsonl", read_status=read_status)
    return run, {"agent": agent, "episodes": [{"index": 0, "final_score": score, "empty_phases": 20}]}


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[Path]]:
    rows = tmp_path / "rows"
    rows.mkdir()
    monkeypatch.setattr(diagnose, "ROWS", rows)
    monkeypatch.setattr(diagnose, "ROOT", tmp_path)
    dirs = []
    for name, agent, status in (("astra", "codex:gpt-6-astra", True), ("opus", "claude:claude-opus-5-5", False)):
        run, row = _run(tmp_path, name, agent, read_status=status)
        (rows / f"{name}.json").write_text(json.dumps(row))
        dirs.append(run)
    return rows, dirs


def test_an_idle_episode_is_empty_everywhere_and_the_family_gap_is_zero(tmp_path: Path, runs) -> None:
    _rows, dirs = runs
    unrowed, _ = _run(tmp_path, "haiku", "claude:claude-haiku-5-5", read_status=False)
    out = tmp_path / "behavior.json"
    assert diagnose.main([*map(str, dirs), str(unrowed), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["skipped_runs"] == [{"run": "haiku", "reason": "no committed row in results/agentic_v21/"}]
    astra, opus = report["models"]["gpt-6-astra"], report["models"]["claude-opus-5-5"]
    for model in (astra, opus):
        assert model["empty_phases"]["count"] == 20
        assert model["drafts"]["count"] == 5
        assert model["end_of_run"]["extensions_per_episode"] == 0
    # Reading the status keeps a phase empty but counts as a status read.
    assert astra["status_habit"]["phases_ended_without_status_read"] == 0
    assert opus["status_habit"]["phases_ended_without_status_read"] == 20
    assert opus["empty_phases"]["without_status_read"] == 20
    # Same seed, same (lack of) moves: every term of the paired gap is zero.
    assert all(term["mean"] == 0 for term in report["family_gap"]["terms"].values())


def test_a_replay_that_disagrees_with_the_committed_row_is_refused(tmp_path: Path, runs) -> None:
    rows, dirs = runs
    row = json.loads((rows / "opus.json").read_text())
    row["episodes"][0]["final_score"] += 1.0
    (rows / "opus.json").write_text(json.dumps(row))
    with pytest.raises(SystemExit, match="does not match the committed row"):
        diagnose.main([*map(str, dirs), "--out", str(tmp_path / "out.json")])
