"""The Codex tool audit's verdict, on synthetic captured requests (no Docker, no login)."""

from __future__ import annotations

import json
from typing import Any

from gm_bench.agentic import codex
from scripts.audit_codex_tools import evaluate, probe_result, prompt_tool_names, without_disabled_features


def _exec(description: str = "### `exec_command`\n### `view_image`\n") -> dict[str, Any]:
    return {"type": "custom", "name": "exec", "description": description}


def _first(*, recommended: bool = False, exec_description: str | None = None) -> dict[str, Any]:
    text = "<recommended_plugins>\n- Gmail\n</recommended_plugins>" if recommended else "skills"
    tools = {"type": "namespace", "name": "functions", "tools": [_exec(exec_description or "### `exec_command`\n")]}
    return {
        "input": [
            {"type": "additional_tools", "role": "developer", "tools": [tools]},
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": text}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "BRIEF"}]},
        ]
    }


def _follow_up(first: dict[str, Any], names: list[str]) -> dict[str, Any]:
    report = json.dumps({"gmb_audit": {"before": len(names), "names": names}})
    output = [{"type": "input_text", "text": "Script completed\nOutput:\n"}, {"type": "input_text", "text": report}]
    return {"input": [*first["input"], {"type": "custom_tool_call_output", "call_id": "c", "output": output}]}


def test_only_built_ins_and_gm_bench_tools_pass() -> None:
    first = _first()
    names = ["exec_command", "view_image", "mcp__gm_bench__get_status", "mcp__gm_bench__end_phase"]
    report = evaluate([first, _follow_up(first, names)], plugin_cache_entries=0)
    assert report["problems"] == []
    assert report["servers"] == {"built-in": 3, "gm_bench": 2}
    assert report["gm_bench_tools"] == 2 and report["gm_bench_tools_in_first_prompt"] == 0


def test_account_apps_plugins_and_install_suggestions_fail() -> None:
    first = _first(recommended=True)
    names = ["exec_command", "request_plugin_install", "mcp__gm_bench__get_status", "mcp__codex_apps__gmail_send_email"]
    report = evaluate([first, _follow_up(first, names)], plugin_cache_entries=24)
    problems = " | ".join(report["problems"])
    assert "codex_apps" in problems and "request_plugin_install" in problems
    assert "<recommended_plugins>" in problems and "24 account plugin" in problems


def test_a_launch_without_gm_bench_tools_or_an_all_tools_report_proves_nothing() -> None:
    assert evaluate([], plugin_cache_entries=None)["problems"]
    report = evaluate([_first()], plugin_cache_entries=0)
    assert any("ALL_TOOLS" in problem for problem in report["problems"])
    assert any("no GM-Bench tool" in problem for problem in report["problems"])


def test_prompt_names_include_the_exec_description_s_nested_tools_and_the_probe_reads_back() -> None:
    first = _first(exec_description="### `exec_command`\n### `mcp__gm_bench__get_status`\n")
    assert "mcp__gm_bench__get_status" in prompt_tool_names(first)
    assert probe_result([_follow_up(first, ["a"])]) == {"before": 1, "names": ["a"]}


def test_without_disabled_features_drops_exactly_the_driver_s_feature_flags() -> None:
    args = codex.CodexDriver().run_args(model="m", variant="low", workdir="/w", brief="B", isolation="container")
    stripped = without_disabled_features(args)
    assert not any(arg.startswith("features.") for arg in stripped)
    assert len(args) - len(stripped) == 2 * len(codex.DISABLED_FEATURES)
    assert 'model_reasoning_effort="low"' in stripped and stripped[-1] == "B"
