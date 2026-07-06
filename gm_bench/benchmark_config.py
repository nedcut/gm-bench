"""Benchmark configuration presets and JSON config loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gm_bench.providers import PROVIDER_NAMES

PRESET_NAMES = ("smoke", "standard", "benchmark")

PRESETS: dict[str, dict[str, Any]] = {
    "smoke": {
        "seeds": [1],
        "seasons": 1,
        "baselines": ["random", "conservative", "win-now", "rebuild"],
        "agent_timeout": 120.0,
    },
    "standard": {
        "seeds": [1, 2, 3],
        "seasons": 3,
        "baselines": ["random", "conservative", "win-now", "rebuild"],
        "agent_timeout": 120.0,
    },
    "benchmark": {
        "seeds": [1, 2, 3, 4, 5],
        "seasons": 5,
        "baselines": ["random", "conservative", "win-now", "rebuild", "value"],
        "agent_timeout": 120.0,
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
        self.seasons = int(values["seasons"])
        self.baselines = list(values["baselines"])
        if self.agent_timeout is None:
            self.agent_timeout = float(values["agent_timeout"])
        self.preset = preset

    def validate(self) -> None:
        if self.provider and self.provider.lower() not in PROVIDER_NAMES:
            raise ValueError(f"unknown provider {self.provider!r}")
        if self.provider and self.agent_cmd:
            raise ValueError("use either provider or agent_cmd, not both")
        if not self.seeds:
            raise ValueError("seeds must not be empty")
        if self.seasons < 1:
            raise ValueError("seasons must be >= 1")


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
