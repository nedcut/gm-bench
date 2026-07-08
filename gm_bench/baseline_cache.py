"""Disk cache for deterministic scripted baseline episode scores."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from gm_bench.contract import contract_fingerprint

CACHE_VERSION = 1
_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_PATH = _PACKAGE_DIR.parent / "data" / "baseline_cache.json"


def default_cache_path() -> Path:
    """Resolve the cache location at call time so GM_BENCH_BASELINE_CACHE can redirect it."""
    override = os.environ.get("GM_BENCH_BASELINE_CACHE")
    return Path(override) if override else DEFAULT_CACHE_PATH


@lru_cache(maxsize=1)
def simulation_fingerprint() -> str:
    """Use the score-affecting benchmark contract to invalidate cached episodes."""

    return contract_fingerprint()[:12]


def cache_key(agent_name: str, seed: int, seasons: int, config_fingerprint: str = "") -> str:
    base = f"v{CACHE_VERSION}:{simulation_fingerprint()}:{agent_name}:{seed}:{seasons}"
    # The default episode config appends nothing, so its keys stay identical to
    # the historical cache; non-default configs (e.g. --no-midseason) get their
    # own bucket instead of silently reusing default-config baseline scores.
    return f"{base}:{config_fingerprint}" if config_fingerprint else base


def load_cache(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    cache_path = Path(path) if path is not None else default_cache_path()
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text())
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if isinstance(value, dict)}


def save_cache(cache: dict[str, dict[str, Any]], path: str | Path | None = None) -> None:
    # Entries keyed under an older fingerprint can never be read again, so drop
    # them rather than letting the file accumulate dead episodes forever.
    prefix = f"v{CACHE_VERSION}:{simulation_fingerprint()}:"
    live = {key: value for key, value in cache.items() if key.startswith(prefix)}
    cache_path = Path(path) if path is not None else default_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(live, indent=2, sort_keys=True))
    os.replace(temp_path, cache_path)


def get_cached_episode(
    agent_name: str,
    seed: int,
    seasons: int,
    *,
    config_fingerprint: str = "",
    cache: dict[str, dict[str, Any]] | None = None,
    cache_path: str | Path | None = None,
) -> dict[str, Any] | None:
    store = cache if cache is not None else load_cache(cache_path)
    return store.get(cache_key(agent_name, seed, seasons, config_fingerprint))


def put_cached_episode(
    agent_name: str,
    seed: int,
    seasons: int,
    episode: dict[str, Any],
    *,
    config_fingerprint: str = "",
    cache: dict[str, dict[str, Any]],
) -> None:
    cache[cache_key(agent_name, seed, seasons, config_fingerprint)] = episode
