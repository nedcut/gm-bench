#!/usr/bin/env python3
"""Build the browser's generated simulator bundle and replay fixture.

The browser does not carry a second, hand-maintained simulator. It loads this
zip archive into Pyodide, so the source is always assembled from the checkout's
actual ``gm_bench`` package. ``--write-fixture`` is intentionally explicit:
normal web builds validate the committed fixture but do not silently replace
it when the simulator changes. Fixture generation is local CPython-authority;
the Node/Pyodide validator then checks cross-runtime parity.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "gm_bench"
DEFAULT_BUNDLE = ROOT / "web" / "public" / "replay" / "gm_bench.zip"
DEFAULT_FIXTURE = ROOT / "web" / "public" / "replay" / "replay_fixture.json"

sys.path.insert(0, str(ROOT))


def build_bundle(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    sources = sorted(PACKAGE.glob("*.py"))
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sources:
            info = zipfile.ZipInfo(f"gm_bench/{source.name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def write_fixture(destination: Path) -> None:
    from gm_bench.agents import AGENTS
    from gm_bench.protocol import EpisodeConfig
    from gm_bench.recorder import DecisionRecorder, record_episode

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gm-bench-web-replay-") as temporary:
        record_path = Path(temporary) / "record.jsonl"
        with DecisionRecorder(record_path, agent_name="conservative", ghost_agents=()) as recorder:
            # The fixture is a deterministic seed/action artifact; checkout
            # provenance belongs in decision records, not its reproducibility
            # surface.
            recorder.provenance["git_head"] = None
            league = record_episode(
                AGENTS["conservative"](),
                seed=1,
                recorder=recorder,
                seasons=1,
                config=EpisodeConfig(),
            )
            recorder.export_replay_fixture(destination, league, config=EpisodeConfig())


def check_fixture(source: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema") != "gm-bench-decision-replay-v1":
        raise ValueError("unsupported replay fixture schema")
    expected = payload.get("expected")
    decisions = payload.get("decisions")
    if not isinstance(expected, dict) or not isinstance(expected.get("state_digest"), str):
        raise ValueError("replay fixture expected.state_digest is required")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("replay fixture decisions are required")
    print(f"validated replay fixture shape: {len(decisions)} decisions, digest {expected['state_digest']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args(argv)

    if args.write_fixture:
        write_fixture(args.fixture)
    elif not args.fixture.exists():
        parser.error(f"missing committed replay fixture: {args.fixture}")
    build_bundle(args.bundle)
    check_fixture(args.fixture)
    print(f"built replay source bundle: {args.bundle} ({args.bundle.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
