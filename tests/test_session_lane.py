"""Session-lane wiring: provider construction, provenance, and validation."""

from gm_bench.official import SOTA_V2_POLICY, validate_leaderboard_payload
from gm_bench.providers import build_provider_agent
from gm_bench.session import PersistentProcessAgent


def test_build_provider_agent_session_returns_persistent_agent() -> None:
    agent = build_provider_agent("openai", model="gpt-test", session=True)
    assert isinstance(agent, PersistentProcessAgent)
    assert agent.metadata["session"] is True


def test_build_provider_agent_default_is_fresh_spawn() -> None:
    agent = build_provider_agent("openai", model="gpt-test")
    assert not isinstance(agent, PersistentProcessAgent)
    assert agent.metadata["session"] is False


def test_sota_v2_rejects_session_rows() -> None:
    from test_official_results import _official_payload

    payload = _official_payload(repeats=3)
    payload["run_info"]["session"] = True
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert any("session-condition" in error for error in report.errors)


def test_fresh_spawn_rows_still_pass_sota_v1() -> None:
    from test_official_results import _official_payload

    payload = _official_payload(repeats=3)
    payload["run_info"]["session"] = False
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert report.ok
