"""Disk cache for deterministic scripted baseline episode scores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CACHE_VERSION = 1
DEFAULT_CACHE_PATH = Path("data/baseline_cache.json")


def cache_key(agent_name: str, seed: int, seasons: int) -> str:
    return f"v{CACHE_VERSION}:{agent_name}:{seed}:{seasons}"


def load_cache(path: str | Path = DEFAULT_CACHE_PATH) -> dict[str, dict[str, Any]]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    payload = json.loads(cache_path.read_text())
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if isinstance(value, dict)}


def save_cache(cache: dict[str, dict[str, Any]], path: str | Path = DEFAULT_CACHE_PATH) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def get_cached_episode(
    agent_name: str,
    seed: int,
    seasons: int,
    *,
    cache: dict[str, dict[str, Any]] | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
) -> dict[str, Any] | None:
    store = cache if cache is not None else load_cache(cache_path)
    return store.get(cache_key(agent_name, seed, seasons))


def put_cached_episode(
    agent_name: str,
    seed: int,
    seasons: int,
    episode: dict[str, Any],
    *,
    cache: dict[str, dict[str, Any]],
) -> None:
    cache[cache_key(agent_name, seed, seasons)] = episode
