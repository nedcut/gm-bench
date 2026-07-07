"""GM-Bench public package interface."""

from importlib.metadata import PackageNotFoundError, version

from gm_bench.agents import AGENTS, Agent
from gm_bench.runner import BenchmarkResult, run_episode, run_many
from gm_bench.simulator import League

try:
    __version__ = version("gm-bench")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["AGENTS", "Agent", "BenchmarkResult", "League", "__version__", "run_episode", "run_many"]
