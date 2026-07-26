"""The scripted references must carry no state between decision points.

Model rows are produced fresh-spawned, with only a 2,000-character memo carrying
anything between decisions. The scripted references they are compared against
are handed the same observation stream but are ordinary Python objects that
could, in principle, accumulate in-process state across a whole episode.

If one ever did, the published model-versus-`pick-trader` gap would silently
acquire a continuity confound: part of the difference would be "the reference
remembered things the model was not allowed to remember" rather than a
difference in policy. `ScaffoldViewAgent`'s docstring already asserts this is
not the case -- "the scripted policy is stateless and rebuilds its plan from the
observation every turn, so it pays no memo cost to begin with" -- and the
scaffold-view measurement in `docs/run_logs/` is interpreted on that basis.

These tests turn that documented assumption into an enforced one. The check is
behavioural rather than structural: an agent is re-instantiated before every
single decision, and the episode must score identically. That catches state held
anywhere the instance can reach, not just attributes a reviewer thought to look
at.
"""

from __future__ import annotations

from typing import Any

import pytest

from gm_bench.agents import AGENTS
from gm_bench.runner import run_episode

# The references whose scores are compared against model rows. Every registered
# agent is checked, but these are the ones a regression would actually corrupt.
COMPARISON_REFERENCES = ("pick-trader", "scaffold-view", "strategic", "shrewd", "value")


def _fresh_spawn_factory(name: str) -> Any:
    """Return an agent that discards and rebuilds itself before every decision."""
    factory = AGENTS[name]
    base = type(factory())

    class FreshSpawn(base):  # type: ignore[misc, valid-type]
        """Memo-only continuity: nothing survives between decision points."""

        def act(self, observation: dict[str, Any]) -> Any:
            return factory().act(observation)

    return FreshSpawn


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_registered_agents_are_stateless_across_decisions(name: str) -> None:
    """Re-instantiating before every decision must not change the episode."""
    persistent = run_episode(AGENTS[name](), seed=11, seasons=3)
    fresh = run_episode(_fresh_spawn_factory(name)(), seed=11, seasons=3)
    assert fresh.final_score == pytest.approx(persistent.final_score, abs=1e-9), (
        f"{name} scores differently when rebuilt each decision, so it carries "
        f"cross-decision state that model rows are not permitted"
    )
    assert fresh.strategy_score == pytest.approx(persistent.strategy_score, abs=1e-9)


@pytest.mark.parametrize("name", COMPARISON_REFERENCES)
def test_comparison_references_hold_no_instance_state(name: str) -> None:
    """Structural companion to the behavioural check, for a clearer failure."""
    agent = AGENTS[name]()
    mutable = {
        key: value
        for key, value in agent.__dict__.items()
        # Construction-time configuration is fine; accumulating containers are not.
        if isinstance(value, (list, dict, set))
    }
    assert not mutable, f"{name} holds mutable instance state: {sorted(mutable)}"


def test_statelessness_check_would_catch_a_stateful_reference() -> None:
    """Guard the guard: a deliberately stateful agent must fail the check.

    Without this, a change that made `run_episode` reuse one agent instance
    regardless of what it was handed would make every test above pass vacuously.
    """
    base = type(AGENTS["value"]())

    class Stateful(base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            self.seen = 0

        def act(self, observation: dict[str, Any]) -> Any:
            # Drift behaviour with accumulated state: skip acting on the first
            # decision only, which a fresh-spawned copy would never do.
            self.seen += 1
            if self.seen == 1:
                return []
            return super().act(observation)

    persistent = run_episode(Stateful(), seed=11, seasons=3)
    fresh = run_episode(_fresh_spawn_factory("value")(), seed=11, seasons=3)
    assert persistent.final_score != pytest.approx(fresh.final_score, abs=1e-9)
