"""GM-Bench public package interface."""

from gm_bench.agents import AGENTS, Agent
from gm_bench.runner import BenchmarkResult, run_episode, run_many
from gm_bench.simulator import League

# Keep in sync with pyproject.toml; stamped into result payloads so runs can be
# attributed to the benchmark revision that produced them.
__version__ = "0.1.0"

__all__ = ["AGENTS", "Agent", "BenchmarkResult", "League", "__version__", "run_episode", "run_many"]
