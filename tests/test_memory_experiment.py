"""Offline tests of the experiment, never paid inference or benchmark evidence."""

import copy
import json
from pathlib import Path

import pytest

from gm_bench import memory_experiment as exp
from gm_bench import memory_experiment_provider as providers
from gm_bench.agentic.contract import agentic_fingerprint
from gm_bench.agentic.episode import AgenticEpisode


def save_manifest(tmp_path, **kwargs):
    manifest = exp.register([701, 702], **kwargs)
    path = tmp_path / "registration.json"
    exp.write_json(path, manifest)
    return path, manifest


def rehash(manifest):
    manifest["manifest_sha256"] = exp.digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    return manifest


def test_offline_panel_and_reproducibility(tmp_path):
    path, manifest = save_manifest(tmp_path)
    first = exp.run(path, tmp_path / "first")
    second = exp.run(path, tmp_path / "second")
    assert first == second
    assert first["complete_panel"] and first["all_episodes_completed"] and first["all_identities_verified"]
    assert first["paired_metrics"]["final_score"]["mean_difference"] == 0
    assert first["paired_metrics"]["tool_calls"]["mean_difference"] == -3
    assert first["paired_metrics"]["final_score"]["pair_count"] == 4
    assert first["paired_metrics"]["final_score"]["seed_count"] == 2
    assert "not whether memory improves LLM performance" in (tmp_path / "first/report.md").read_text()
    assert json.loads((tmp_path / "first/manifest.json").read_text()) == manifest
    for path in (tmp_path / "first").glob("cell-*/ledger.jsonl"):
        replay = AgenticEpisode.from_ledger(path, reopen=False)
        row = json.loads(path.with_name("cell.json").read_text())
        assert replay.result()["final_score"] == row["metrics"]["final_score"]
    with pytest.raises(FileExistsError):
        exp.run(tmp_path / "registration.json", tmp_path / "first")


def test_context_reset_and_only_retention_differs(tmp_path):
    manifest = exp.register([123], seasons=2)
    starts = {}
    for condition in exp.CONDITIONS:
        directory = tmp_path / condition
        directory.mkdir()
        exp.play(manifest, 123, 0, condition, directory)
        events = [json.loads(line) for line in (directory / "trace.jsonl").read_text().splitlines()]
        starts[condition] = [e["request"] for e in events if not e["request"]["history"]]
        assert len(starts[condition]) == 8
        assert all("seed" not in e["request"] and "condition" not in e["request"] for e in events)
        assert all("write_memo" not in [t["name"] for t in e["request"]["tools"]] for e in events)
        assert all(
            "write_memo" not in e["result"]["data"]["legal_tools"]
            for e in events
            if e["action"]["tool"] == "get_status"
        )
    control, journal = (starts[c] for c in exp.CONDITIONS)
    assert control[0] == journal[0]
    for a, b in zip(control[1:], journal[1:]):
        assert a["journal"] == exp.empty_journal()
        assert b["journal"]["facts"] == ["rules reviewed"]
        assert {k: v for k, v in a.items() if k != "journal"} == {k: v for k, v in b.items() if k != "journal"}


@pytest.mark.parametrize(
    "controls,termination", [({"max_calls_per_phase": 1}, "call_budget"), ({"max_request_chars": 1}, "prompt_budget")]
)
def test_experimental_budget_does_not_complete_for_agent(tmp_path, controls, termination):
    manifest = exp.register([701], controls=controls)
    row = exp.play(manifest, 701, 0, exp.CONDITIONS[0], tmp_path)
    assert row["termination"] == termination
    assert row["metrics"]["completed"] == 0
    assert row["metrics"]["failed_decisions"] == 4
    assert row["phases_ended_by"] == {"harness_exit": 4}
    assert row["metrics"]["illegal_actions"] == 0
    assert agentic_fingerprint() == "07de948a4f4afbae"
    assert AgenticEpisode(701).phase_guard_seconds == 1200


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["seeds"].append(701),
        lambda m: m["controls"].update(max_calls_per_phase=True),
        lambda m: m["analysis"].update(primary="tool_calls"),
        lambda m: m["provenance"].update(source_sha256="wrong"),
        lambda m: m["model"].update(requested="other-script"),
    ],
)
def test_invalid_registration_even_if_rehashed(change):
    manifest = copy.deepcopy(exp.register([701]))
    change(manifest)
    with pytest.raises(ValueError):
        exp.validate_manifest(rehash(manifest))


def test_tampering_and_nonfinite_rates():
    manifest = exp.register([701])
    manifest["seasons"] = 3
    with pytest.raises(ValueError, match="hash"):
        exp.validate_manifest(manifest)
    with pytest.raises(ValueError):
        exp.register([701], pricing={"input": float("nan"), "output": 1})


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_model_output_retained_as_malformed(tmp_path, constant):
    manifest = exp.register([701])

    def provider(request, model, controls):
        response = providers.scripted(request, model, controls)
        response["content"] = (
            '{"tool":"get_status","arguments":{"x":' + constant + '},"journal":{"facts":[],"plan":[],"decisions":[]}}'
        )
        return response

    row = exp.play(manifest, 701, 0, exp.CONDITIONS[0], tmp_path, provider)
    assert row["termination"] == "malformed_response"
    assert row["metrics"]["model_calls"] == 1 and row["metrics"]["tool_calls"] == 0
    assert len((tmp_path / "trace.jsonl").read_text().splitlines()) == 1


def test_report_rejects_altered_evidence(tmp_path):
    path, _ = save_manifest(tmp_path, repeats=1)
    exp.run(path, tmp_path / "out")
    trace = tmp_path / "out/cell-0000/trace.jsonl"
    trace.write_text(trace.read_text() + "\n")
    with pytest.raises(ValueError, match="evidence"):
        exp.report_directory(tmp_path / "out")


def test_live_gate_before_creating_output_or_calling_provider(tmp_path):
    path, _ = save_manifest(tmp_path, provider="openai-chat", model="test-2026-01-01")

    def forbidden(*args):
        pytest.fail("must not call provider")

    with pytest.raises(ValueError, match="allow-paid"):
        exp.run(path, tmp_path / "out", provider=forbidden)
    assert not (tmp_path / "out").exists()


def test_pin_markers_and_alias_rejection():
    with pytest.raises(ValueError, match="snapshot"):
        exp.register([701], provider="openai-chat", model="latest")
    for status in ("unpinned", "unsupported"):
        manifest = exp.register([701], provider="openai-chat", model="alias", pin=status)
        assert manifest["model"]["pin_status"] == status
        assert manifest["model"]["expected_response_model"] is None


@pytest.mark.parametrize(
    "mode,termination",
    [
        ("identity", "identity_mismatch"),
        ("json", "malformed_response"),
        ("journal", "malformed_response"),
        ("error", "provider_error"),
    ],
)
def test_failure_retention_and_usage_before_action_validation(tmp_path, mode, termination):
    manifest = exp.register([701], provider="openai-chat", model="test-2026-01-01", pricing={"input": 2, "output": 5})

    def provider(request, model, controls):
        if mode == "error":
            raise RuntimeError("secret-credential-do-not-log")
        response = providers.scripted(request, model, controls)
        response["usage"] = {"prompt_tokens": 100, "completion_tokens": 20}
        if mode == "identity":
            response["model"] = "different-snapshot"
        elif mode == "json":
            response["content"] = "not json"
        else:
            action = json.loads(response["content"])
            action["journal"]["facts"] = ["x" * 10000]
            response["content"] = json.dumps(action)
        return response

    row = exp.play(manifest, 701, 0, exp.CONDITIONS[0], tmp_path, provider)
    assert row["termination"] == termination
    assert row["metrics"]["completed"] == 0
    assert row["metrics"]["model_calls"] == 1
    assert row["metrics"]["tool_calls"] == 0
    if mode == "error":
        assert row["usage"]["prompt_tokens"]["status"] == "unavailable"
        assert row["usage"]["cost_usd"]["value"] is None
        assert "secret-credential" not in (tmp_path / "trace.jsonl").read_text()
    else:
        assert row["usage"]["prompt_tokens"]["value"] == 100
        assert row["usage"]["cost_usd"]["status"] == "estimated"
        assert row["usage"]["cost_usd"]["value"] == pytest.approx(0.0003)


def test_rejection_is_not_necessarily_illegal_action(tmp_path):
    manifest = exp.register([701], controls={"max_calls_per_phase": 3})

    def provider(request, model, controls):
        response = providers.scripted(request, model, controls)
        action = json.loads(response["content"])
        action["tool"] = "write_memo" if not request["history"] else "unknown_tool"
        response["content"] = json.dumps(action)
        return response

    row = exp.play(manifest, 701, 0, exp.CONDITIONS[0], tmp_path, provider)
    assert row["metrics"]["tool_calls"] == row["metrics"]["rejected_tool_calls"] == 3
    assert row["metrics"]["illegal_actions"] == 0


def test_pairs_missing_duplicates_and_repeat_cluster_analysis(tmp_path):
    path, manifest = save_manifest(tmp_path)
    exp.run(path, tmp_path / "out")
    rows = [json.loads(p.read_text()) for p in sorted((tmp_path / "out").glob("cell-*/cell.json"))]
    for row in rows:
        row["metrics"]["final_score"] = 0 if row["condition"] == exp.CONDITIONS[0] else (2 if row["seed"] == 701 else 6)
    report = exp.analyze(manifest, rows)
    metric = report["paired_metrics"]["final_score"]
    assert metric["mean_difference"] == 4
    assert metric["seed_standard_error"] == 2
    assert exp.analyze(manifest, rows[:-1])["paired_metrics"] == {}
    assert exp.analyze(manifest, rows[:-1])["missing_cells"]
    with pytest.raises(ValueError, match="duplicate"):
        exp.analyze(manifest, [*rows, rows[0]])
    with pytest.raises(ValueError):
        exp.analyze(manifest, [dict(rows[0], manifest_sha256="wrong")])
    single = exp.register([701], repeats=1)
    pair = [
        dict(row, manifest_sha256=single["manifest_sha256"])
        for row in rows
        if row["seed"] == 701 and row["repeat"] == 0
    ]
    assert exp.analyze(single, pair)["paired_metrics"]["final_score"]["seed_standard_error"] is None


def test_stateless_openai_wire_without_network(monkeypatch):
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}], "model": "snapshot", "usage": {}}).encode()

    class Client:
        def open(self, request, timeout):
            sent.append((request, timeout))
            return Response()

    monkeypatch.setattr(providers.urllib.request, "build_opener", lambda *args: Client())
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    request = {"instructions": "JSON only", "journal": exp.empty_journal(), "history": []}
    response = providers.openai_chat(request, {"requested": "snapshot"}, exp.CONTROLS)
    assert response["model"] == "snapshot"
    wire, timeout = sent[0]
    body = json.loads(wire.data)
    assert wire.full_url == "https://api.openai.com/v1/chat/completions"
    assert body["temperature"] == 0 and body["store"] is False
    assert "seed" not in body and len(body["messages"]) == 2
    assert body["max_completion_tokens"] == exp.CONTROLS["max_output_tokens"]
    assert timeout == exp.CONTROLS["socket_timeout_seconds"]
    assert providers.NoRedirect().redirect_request(None, None, None, None, None, None) is None


def test_cli_example(tmp_path, capsys):
    manifest, output = tmp_path / "manifest.json", tmp_path / "out"
    exp.main(["register", "--out", str(manifest), "--public-seeds", "701", "--repeats", "1"])
    exp.main(["run", str(manifest), "--out", str(output)])
    report = (output / "report.md").read_text()
    exp.main(["report", str(output)])
    assert (output / "report.md").read_text() == report
    assert str(output / "report.md") in capsys.readouterr().out


def test_new_modules_are_shipped_by_existing_package_configuration():
    # No shared packaging or frozen CLI edits are needed for these top-level modules.
    root = Path(__file__).parents[1]
    assert '"gm_bench",' in (root / "pyproject.toml").read_text()
