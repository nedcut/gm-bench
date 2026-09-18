"""GM-Bench public package interface."""

from importlib.metadata import PackageNotFoundError, version

# Lanes declared outside the frozen provider registry register on import, and
# must do so before runner (via benchmark_config) binds PROVIDER_NAMES.
import gm_bench.decision_providers  # noqa: F401
from gm_bench.agents import AGENTS, Agent
from gm_bench.runner import BenchmarkResult, run_episode, run_many
from gm_bench.simulator import League

try:
    __version__ = version("gm-bench")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["AGENTS", "Agent", "BenchmarkResult", "League", "__version__", "run_episode", "run_many"]
