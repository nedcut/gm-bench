"""Benchmark configuration presets and JSON config loading."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gm_bench.providers import PROVIDER_NAMES

PRESET_NAMES = ("smoke", "standard", "benchmark", "leaderboard")
PROFILE_NAMES = ("tiny", "compact")
PRIVATE_SEEDS_ENV = "GM_BENCH_PRIVATE_SEEDS"
PUBLIC_LEADERBOARD_PANEL_NAME = "public-leaderboard"
PRIVATE_LEADERBOARD_PANEL_NAME = "private-env"
CUSTOM_SEED_PANEL_NAME = "custom"

# Presets pin the observation profile so scores produced under the same preset
# are comparable across providers: provider defaults differ (ollama defaults to
# "tiny", openai to "compact"), and a tiny-profile score answers a different
# question than a compact-profile one. An explicit --profile / config value
# still wins over the preset.
PRESETS: dict[str, dict[str, Any]] = {
    "smoke": {
        "seeds": [1],
        "seasons": 1,
        "baselines": ["random", "conservative", "win-now", "rebuild"],
        "agent_timeout": 120.0,
        "profile": "compact",
    },
    "standard": {
        "seeds": [1, 2, 3],
        "seasons": 3,
        "baselines": ["random", "conservative", "win-now", "rebuild"],
        "agent_timeout": 120.0,
        "profile": "compact",
    },
    "benchmark": {
        "seeds": [1, 2, 3, 4, 5],
        "seasons": 5,
        "baselines": ["random", "conservative", "win-now", "rebuild", "value"],
        "agent_timeout": 120.0,
        "profile": "compact",
    },
    # Official leaderboard runs. The public seed panel deliberately avoids the
    # 1-5 dev seeds used throughout the docs and examples, and can be replaced
    # wholesale with a held-out panel via GM_BENCH_PRIVATE_SEEDS (e.g.
    # "101,102,110-115"), which is never committed to the repository.
    "leaderboard": {
        "seeds": [11, 12, 13, 14, 15, 16, 17, 18],
        "seasons": 5,
        "baselines": ["random", "conservative", "win-now", "rebuild", "value", "shrewd"],
        "agent_timeout": 180.0,
        "profile": "compact",
    },
}


@dataclass
class BenchmarkConfig:
    provider: str | None = None
    model: str | None = None
    agent: str = "value"
    agent_cmd: str | None = None
    agent_timeout: float | None = None
    profile: str | None = None
    seeds: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    seasons: int = 5
    repeats: int = 1
    baselines: list[str] = field(default_factory=lambda: ["random", "conservative", "win-now", "rebuild"])
    preset: str | None = None
    use_baseline_cache: bool = True
    verbose: bool = False
    json_output: bool = False
    no_log: bool = False
    db: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    def apply_preset(self, preset: str) -> None:
        if preset not in PRESETS:
            supported = ", ".join(PRESET_NAMES)
            raise ValueError(f"unknown preset {preset!r}; supported presets: {supported}")
        values = PRESETS[preset]
        self.seeds = list(values["seeds"])
        if preset == "leaderboard" and os.environ.get(PRIVATE_SEEDS_ENV):
            self.seeds = _parse_seeds(os.environ[PRIVATE_SEEDS_ENV])
        self.seasons = int(values["seasons"])
        self.baselines = list(values["baselines"])
        if self.agent_timeout is None:
            self.agent_timeout = float(values["agent_timeout"])
        if self.profile is None:
            self.profile = values.get("profile")
        self.preset = preset

    def validate(self) -> None:
        if self.provider and self.provider.lower() not in PROVIDER_NAMES:
            raise ValueError(f"unknown provider {self.provider!r}")
        if self.provider and self.agent_cmd:
            raise ValueError("use either provider or agent_cmd, not both")
        # The adapter silently treats anything except "tiny" as compact, so an
        # unvalidated typo would run compact while run_info records a third
        # profile name — breaking the metadata guarantee this config backs.
        if self.profile is not None and self.profile not in PROFILE_NAMES:
            supported = ", ".join(PROFILE_NAMES)
            raise ValueError(f"unknown profile {self.profile!r}; supported profiles: {supported}")
        if not self.seeds:
            raise ValueError("seeds must not be empty")
        if self.seasons < 1:
            raise ValueError("seasons must be >= 1")
        if self.repeats < 1:
            raise ValueError("repeats must be >= 1")


def load_config(path: str | Path) -> BenchmarkConfig:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError("benchmark config must be a JSON object")
    return config_from_dict(payload)


def config_from_dict(payload: dict[str, Any]) -> BenchmarkConfig:
    preset = payload.get("preset")
    config = BenchmarkConfig(
        provider=payload.get("provider"),
        model=payload.get("model"),
        agent=str(payload.get("agent", "value")),
        agent_cmd=payload.get("agent_cmd"),
        agent_timeout=payload.get("agent_timeout"),
        profile=payload.get("profile"),
        seeds=_parse_seeds(payload.get("seeds", [1, 2, 3, 4, 5])),
        seasons=int(payload.get("seasons", 5)),
        repeats=int(payload.get("repeats", 1)),
        baselines=list(payload.get("baselines", ["random", "conservative", "win-now", "rebuild"])),
        preset=preset,
        use_baseline_cache=bool(payload.get("use_baseline_cache", True)),
        verbose=bool(payload.get("verbose", False)),
        json_output=bool(payload.get("json", False)),
        no_log=bool(payload.get("no_log", False)),
        db=payload.get("db"),
        extra_env=dict(payload.get("env", {})),
    )
    if preset:
        config.apply_preset(str(preset))
        for key in ("seeds", "seasons", "baselines", "agent_timeout"):
            if key in payload:
                if key == "seeds":
                    config.seeds = _parse_seeds(payload["seeds"])
                elif key == "seasons":
                    config.seasons = int(payload["seasons"])
                elif key == "baselines":
                    config.baselines = list(payload["baselines"])
                elif key == "agent_timeout":
                    config.agent_timeout = float(payload["agent_timeout"])
    config.validate()
    return config


def _parse_seeds(value: Any) -> list[int]:
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        seeds: list[int] = []
        for part in value.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                start_text, end_text = part.split("-", 1)
                seeds.extend(range(int(start_text), int(end_text) + 1))
            else:
                seeds.append(int(part))
        return seeds
    if isinstance(value, list):
        return [int(item) for item in value]
    raise ValueError(f"unsupported seeds value: {value!r}")


def seed_panel_hash(seeds: list[int]) -> str:
    """Stable public commitment to an ordered seed panel."""

    text = ",".join(str(seed) for seed in seeds)
    return hashlib.sha256(text.encode()).hexdigest()


def seed_panel_metadata(seeds: list[int], preset: str | None) -> dict[str, Any]:
    if preset == "leaderboard" and seeds == list(PRESETS["leaderboard"]["seeds"]):
        name = PUBLIC_LEADERBOARD_PANEL_NAME
    elif preset == "leaderboard" and os.environ.get(PRIVATE_SEEDS_ENV):
        private_seeds = _parse_seeds(os.environ[PRIVATE_SEEDS_ENV])
        name = PRIVATE_LEADERBOARD_PANEL_NAME if seeds == private_seeds else CUSTOM_SEED_PANEL_NAME
    else:
        name = CUSTOM_SEED_PANEL_NAME
    return {
        "name": name,
        "count": len(seeds),
        "sha256": seed_panel_hash(seeds),
        "preset": preset,
    }
