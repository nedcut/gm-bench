"""TypeSafe Jev adapter: wire format, answer-to-action rules, and lane registration."""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from examples import typesafe_jev_agent as jev
from gm_bench.action_validation import validate_action_list
from gm_bench.model_runs import ModelRunAborted, preflight_provider
from gm_bench.providers import build_provider_agent, resolve_provider
from gm_bench.simulator import League
from gm_bench.telemetry import estimate_cost_usd, normalize_usage


@pytest.fixture(autouse=True)
def pinned_adapter_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The question set follows the compact view; an inherited profile or knob
    from another test must not change what the composer is allowed to do."""
    monkeypatch.setenv("GM_AGENT_PROFILE", "compact")
    for name in (
        "JEV_ROUTE",
        "JEV_NOUL_THRESHOLD",
        "JEV_ENABLE_TRADES",
        "JEV_DECISION_LOG",
        "TYPESAFE_API_BASE",
        "TYPESAFE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _observation(phase: str = "preseason", seed: int = 3) -> dict[str, Any]:
    league = League.new(seed=seed, user_team_id=0)
    if phase == "midseason":
        league.prepare_midseason()
    if phase == "trade_deadline":
        league.prepare_trade_deadline()
    if phase == "draft":
        league.run_opponent_draft(before_user=True)
    # Adapters receive the observation over stdin as JSON, so every key is a
    # string by the time build_questions sees it.
    return json.loads(json.dumps(league.observation(phase, tier="full")))


def _answer_everything(questions: dict[str, Any]) -> dict[str, Any]:
    """A plausible Jev reply: first real option for every choice, dress everyone."""
    answers: dict[str, Any] = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            answers[key] = {"type": "noul", "noul": 0.9}
        else:
            labels = list(question["criteria"])
            chosen = next((label for label in labels if label != jev.NONE_LABEL), labels[0])
            probabilities = {label: (0.7 if label == chosen else 0.3 / max(1, len(labels) - 1)) for label in labels}
            answers[key] = {"type": "choice", "choice": chosen, "probabilities": probabilities, "confidence": 0.6}
    return answers


class _Response:
    headers = {"X-Request-Id": "req-test"}

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_question_batch_covers_every_advertised_decision() -> None:
    questions, index = jev.build_questions(_observation("preseason"))
    assert questions["sign_free_agent"]["type"] == "choice"
    assert jev.NONE_LABEL in questions["sign_free_agent"]["criteria"]
    assert set(questions["sign_years"]["criteria"]) == set(jev.CONTRACT_TERMS)
    assert questions["release"]["type"] == "choice"
    assert questions["scout"]["type"] == "choice"
    assert questions["trade_target"]["type"] == "choice"
    assert questions["trade_give"]["type"] == "choice"
    assert any(label.startswith("pick_") for label in questions["trade_give"]["criteria"])
    assert index["extensions"], "seed 3 has expiring contracts in preseason"
    assert set(questions["extend_years"]["criteria"]) == set(jev.EXTENSION_TERMS)
    dress = [key for key in questions if key.startswith("dress_")]
    assert dress == index["lineup_ids"]
    assert all(questions[key]["type"] == "noul" for key in dress)
    # Every option label round-trips to a record the composer can act on.
    for label in questions["sign_free_agent"]["criteria"]:
        assert label == jev.NONE_LABEL or label in index["free_agents"]
    assert "draft" not in questions
    assert "claim_waiver" not in questions


def test_question_batch_follows_the_phase() -> None:
    draft_questions, draft_index = jev.build_questions(_observation("draft"))
    assert draft_questions["draft"]["type"] == "choice"
    assert draft_index["pick_count"] >= 1
    assert "extend_years" not in draft_questions

    midseason_questions, midseason_index = jev.build_questions(_observation("midseason"))
    assert "extend_years" not in midseason_questions
    if midseason_index["waiver_wire"]:
        assert set(midseason_questions["claim_waiver"]["criteria"]) == {jev.NONE_LABEL, *midseason_index["waiver_wire"]}
    else:
        assert "claim_waiver" not in midseason_questions

    deadline_questions, deadline_index = jev.build_questions(_observation("trade_deadline"))
    assert deadline_index["offers"], "seed 3 trade deadline generates incoming offers"
    for key in deadline_index["offers"]:
        assert set(deadline_questions[key]["criteria"]) == {"accept", "reject", "ignore"}


def test_trade_questions_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_ENABLE_TRADES", "0")
    questions, _ = jev.build_questions(_observation("preseason"))
    assert "trade_target" not in questions
    assert "trade_give" not in questions


@pytest.mark.parametrize("phase", ["preseason", "midseason", "trade_deadline", "draft"])
def test_composed_actions_validate_and_apply_without_illegal_moves(phase: str) -> None:
    observation = _observation(phase)
    questions, index = jev.build_questions(observation)
    answers = _answer_everything(questions)
    # Mark the answers so the batch exercises every rule: a real signing term,
    # every offer accepted, a pick given in trade, nobody released.
    answers["sign_years"]["choice"] = "3"
    answers["release"]["choice"] = jev.NONE_LABEL
    if "trade_give" in answers:
        answers["trade_give"]["choice"] = next(
            label for label in questions["trade_give"]["criteria"] if label.startswith("pick_")
        )
    actions = jev.compose_actions(observation, answers, index)
    validate_action_list(actions)
    types = [action["type"] for action in actions]
    # The lineup leads the batch and is legal on the roster Jev was asked
    # about, whatever the later roster moves do to it.
    assert types[0] == "set_lineup"
    lineup = actions[0]["player_ids"]
    assert len(lineup) == 18 and len(set(lineup)) == 18
    assert set(map(str, lineup)) <= set(index["roster"])
    signing = next(action for action in actions if action["type"] == "sign_free_agent")
    player = index["free_agents"][str(signing["player_id"])]
    assert signing["years"] == 3
    assert signing["salary"] == player["contract_quotes"]["3"]
    if phase == "draft":
        assert types.count("draft") == index["pick_count"]
    if phase == "trade_deadline":
        accepted = [action["offer_id"] for action in actions if action["type"] == "accept_trade_offer"]
        assert accepted, "every offer was answered accept, so at least the first is sent"
        sent: set[int] = set()
        for offer in index["offers"].values():
            if offer["offer_id"] in accepted:
                assert not sent.intersection(offer["they_receive"]), "a player is never sent away twice"
                sent.update(offer["they_receive"])
    if "trade" in types:
        trade = next(action for action in actions if action["type"] == "trade")
        assert trade["give_pick_seasons"] and not trade["give_player_ids"]

    # Replay the same batch on a fresh league: the composition rules must never
    # produce a structurally illegal action. Simulator refusals (a partner
    # declining a lopsided trade) are Jev's outcome, not a scaffold bug, so only
    # structural rejections are asserted against.
    league = League.new(seed=3, user_team_id=0)
    if phase == "midseason":
        league.prepare_midseason()
    if phase == "trade_deadline":
        league.prepare_trade_deadline()
    if phase == "draft":
        league.run_opponent_draft(before_user=True)
    results = league.apply_actions(actions, phase)
    assert results[0].accepted, results[0].message
    structural = ("invalid", "must", "no such", "not on", "unknown", "exactly", "duplicate")
    for result in results:
        if not result.accepted and result.action.get("type") != "trade":
            assert not any(marker in result.message for marker in structural), result.message


def test_lineup_follows_jev_probability_order_inside_the_legal_shape() -> None:
    observation = _observation("preseason")
    questions, index = jev.build_questions(observation)
    roster = list(index["roster"].values())
    answers: dict[str, Any] = {}
    # Jev strongly prefers the weakest players: the composer must still dress
    # the ones it ranked highest, subject only to 10F/4D/1G and 18 slots.
    ordered = sorted(roster, key=lambda player: player["overall"])
    for rank, player in enumerate(ordered):
        answers[f"dress_{player['id']}"] = {"type": "noul", "noul": 1.0 - rank / (len(ordered) + 1)}
    actions = jev.compose_actions(observation, answers, index)
    lineup = actions[0]["player_ids"]
    assert len(lineup) == 18 and len(set(lineup)) == 18
    goalies = [player["id"] for player in ordered if player["position"] == "G"]
    assert goalies[0] in lineup, "the goalie Jev ranked first is dressed"
    weakest_dressed = [player["id"] for player in ordered[:10]]
    assert set(weakest_dressed) <= set(lineup)


def test_unanswered_questions_produce_no_host_choices() -> None:
    observation = _observation("preseason")
    _, index = jev.build_questions(observation)
    assert jev.compose_actions(observation, {}, index) == [{"type": "noop"}]
    # A released skater is not dressed when the rest can form a legal lineup,
    # and the lineup still leads the batch so it is legal before the release.
    victim = next(label for label, player in index["roster"].items() if player["position"] == "F")
    answers = {"release": {"type": "choice", "choice": victim}}
    answers.update({key: {"type": "noul", "noul": 1.0} for key in index["lineup_ids"]})
    actions = jev.compose_actions(observation, answers, index)
    assert actions[0]["type"] == "set_lineup"
    assert int(victim) not in actions[0]["player_ids"]
    assert actions[1] == {"type": "release", "player_id": int(victim)}
    # Releasing the only goalie: he is still dressed (the simulator drops him
    # once he leaves) rather than the host inventing an illegal lineup.
    goalies = [label for label, player in index["roster"].items() if player["position"] == "G"]
    if len(goalies) == 1:
        answers["release"]["choice"] = goalies[0]
        actions = jev.compose_actions(observation, answers, index)
        assert int(goalies[0]) in actions[0]["player_ids"]


def test_batch_never_exceeds_the_validator_ceiling() -> None:
    """Every roster row expiring at once must not turn the decision into a no-op."""
    observation = _observation("preseason")
    for player in observation["team"]["roster"]:
        player["extension_quotes"] = {"2": 1.0, "3": 1.1, "4": 1.2, "5": 1.3}
    questions, index = jev.build_questions(observation)
    assert len(index["extensions"]) >= 20
    answers = _answer_everything(questions)
    answers["release"]["choice"] = jev.NONE_LABEL
    answers["trade_target"]["choice"] = jev.NONE_LABEL
    actions = jev.compose_actions(observation, answers, index)
    validate_action_list(actions)
    assert len(actions) == jev.MAX_ACTIONS_PER_DECISION
    assert actions[0]["type"] == "set_lineup"
    assert any(action["type"] == "sign_free_agent" for action in actions)
    assert any(action["type"] == "scout" for action in actions)
    # Only surplus extensions were cut: everything else Jev asked for is kept.
    assert sum(action["type"] == "extend_contract" for action in actions) < len(index["extensions"])


def test_no_term_answer_means_no_contract() -> None:
    """A signing or extension needs Jev's term as well as its pick; the host
    never fills in a default year count or prices a term with no quote."""
    observation = _observation("preseason")
    _, index = jev.build_questions(observation)
    free_agent = next(iter(index["free_agents"]))
    key, player = index["extensions"][0]
    yes = {"type": "noul", "noul": 1.0}
    pick = {"type": "choice", "choice": free_agent}

    assert jev.compose_actions(observation, {"sign_free_agent": pick, key: yes}, index) == [{"type": "noop"}]
    invalid = {"type": "choice", "choice": "not-a-term"}
    answers = {"sign_free_agent": pick, "sign_years": invalid, key: yes, "extend_years": invalid}
    assert jev.compose_actions(observation, answers, index) == [{"type": "noop"}]
    # A term the quote table does not carry is not priced from the 1-year ask.
    player_quotes = index["free_agents"][free_agent]["contract_quotes"]
    del player_quotes["4"]
    answers = {"sign_free_agent": pick, "sign_years": {"type": "choice", "choice": "4"}}
    assert jev.compose_actions(observation, answers, index) == [{"type": "noop"}]
    answers["sign_years"]["choice"] = "5"
    actions = jev.compose_actions(observation, answers, index)
    assert actions == [
        {"type": "sign_free_agent", "player_id": int(free_agent), "years": 5, "salary": player_quotes["5"]}
    ]


def test_a_player_leaving_in_the_batch_is_not_extended() -> None:
    """Independent answers can release a player and extend him; batch order
    keeps the first claim and drops the later one, so the extension never
    reaches the simulator as a structural illegal action."""
    observation = _observation("preseason")
    _, index = jev.build_questions(observation)
    key, player = index["extensions"][0]
    answers = {
        "release": {"type": "choice", "choice": str(player["id"])},
        key: {"type": "noul", "noul": 1.0},
        "extend_years": {"type": "choice", "choice": "3"},
    }
    actions = jev.compose_actions(observation, answers, index)
    assert actions == [{"type": "release", "player_id": player["id"]}]
    # The same player given away in a trade is not extended either.
    listing = next(iter(index["trade_market"].values()))
    answers = {
        "trade_target": {"type": "choice", "choice": str(listing["player"]["id"])},
        "trade_give": {"type": "choice", "choice": str(player["id"])},
        key: {"type": "noul", "noul": 1.0},
        "extend_years": {"type": "choice", "choice": "3"},
    }
    actions = jev.compose_actions(observation, answers, index)
    assert [action["type"] for action in actions] == ["trade"]
    league = League.new(seed=3, user_team_id=0)
    for result in league.apply_actions(actions, "preseason"):
        assert "not on your roster" not in result.message


def test_noul_threshold_gates_extensions() -> None:
    observation = _observation("preseason")
    _, index = jev.build_questions(observation)
    key, player = index["extensions"][0]
    answers = {key: {"type": "noul", "noul": 0.6}, "extend_years": {"type": "choice", "choice": "4"}}
    low = jev.compose_actions(observation, answers, index, noul_threshold=0.5)
    high = jev.compose_actions(observation, answers, index, noul_threshold=0.75)
    assert len(low) == 1
    assert low[0] == {
        "type": "extend_contract",
        "player_id": player["id"],
        "years": 4,
        "salary": player["extension_quotes"]["4"],
    }
    assert high == [{"type": "noop"}]


def test_choose_actions_posts_one_system_one_call_and_reports_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, **kwargs: Any) -> _Response:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = kwargs["timeout"]
        payload = json.loads(request.data.decode())
        captured["payload"] = payload
        return _Response(
            {
                "model": "jev-1.13.0",
                "answers": _answer_everything(payload["questions"]),
                "usage": {"input_tokens": 4321, "output_tokens": 0},
            }
        )

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-latest")
    monkeypatch.setenv("GM_BENCH_AGENT_TIMEOUT", "120")
    monkeypatch.delenv("TYPESAFE_TIMEOUT", raising=False)
    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)

    actions, usage = jev.choose_actions(_observation("preseason"))

    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["timeout"] == 105.0
    payload = captured["payload"]
    assert payload["model"] == "jev-latest"
    assert payload["state"]["briefing"] == jev.BRIEFING
    # Jev reads exactly the compact view every chat adapter is prompted with.
    assert payload["state"]["observation"]["phase"] == "preseason"
    assert set(payload["state"]["observation"]) >= {"team", "free_agents", "rules", "available_actions"}
    assert all(question["type"] in {"choice", "noul"} for question in payload["questions"].values())
    for question in payload["questions"].values():
        if question["type"] == "choice":
            assert isinstance(question["criteria"], dict) and 2 <= len(question["criteria"]) <= 255

    assert isinstance(actions, list)
    validate_action_list(actions)
    assert usage["provider"] == "typesafe"
    assert usage["model"] == "jev-1.13.0"
    assert usage["api_calls"] == 1
    assert usage["input_tokens"] == 4321
    assert usage["output_tokens"] == 0
    assert usage["generation_id"] == "req-test"
    assert "telemetry_error" not in usage
    normalized = normalize_usage(usage)
    assert normalized is not None
    assert estimate_cost_usd(normalized) == pytest.approx(4321 * 0.042 / 1_000_000, abs=1e-6)


def test_openrouter_route_posts_to_the_decisions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, **kwargs: Any) -> _Response:
        del kwargs
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        payload = json.loads(request.data.decode())
        captured["payload"] = payload
        response = _Response(
            {
                "id": "gen-or-1",
                "model": "typesafe/jev-1.13",
                "provider": "TypeSafe",
                "answers": _answer_everything(payload["questions"]),
                "usage": {"input_tokens": 5000, "output_tokens": 0, "cost": 0.00021},
            }
        )
        response.headers = {}
        return response

    monkeypatch.setenv("JEV_ROUTE", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    # The harness pins the bare TypeSafe id; the route translates it to the slug.
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-latest")
    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)

    actions, usage = jev.choose_actions(_observation("preseason"))

    validate_action_list(actions)
    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["headers"]["Authorization"] == "Bearer or-key"
    assert captured["headers"]["Http-referer"] == "https://github.com/nedcut/gm-bench"
    assert captured["payload"]["model"] == jev.OPENROUTER_LATEST_ALIAS == "~typesafe/jev-latest"
    assert set(captured["payload"]) == {"model", "state", "questions"}
    assert usage["provider"] == "typesafe"
    assert usage["model"] == "typesafe/jev-1.13"
    assert usage["upstream_provider"] == "TypeSafe"
    assert usage["generation_id"] == "gen-or-1"
    assert usage["cost_usd"] == 0.00021
    # Without a gateway cost the slug is still priced from pricing.json.
    normalized = normalize_usage({"model": "typesafe/jev-1.13", "provider": "typesafe", "input_tokens": 5000})
    assert normalized is not None
    assert estimate_cost_usd(normalized) == pytest.approx(5000 * 0.042 / 1_000_000, abs=1e-6)


def test_openrouter_route_translates_pinned_ids_to_vendor_slugs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_ROUTE", "openrouter")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-1.13")
    assert jev.resolve_route()["model"] == "typesafe/jev-1.13"
    monkeypatch.setenv("TYPESAFE_MODEL", "typesafe/jev-1.12")
    assert jev.resolve_route()["model"] == "typesafe/jev-1.12"
    monkeypatch.delenv("TYPESAFE_MODEL")
    assert jev.resolve_route()["model"] == "typesafe/jev-1.13"
    normalized = normalize_usage({"model": "~typesafe/jev-latest", "provider": "typesafe", "input_tokens": 1000})
    assert normalized is not None
    assert estimate_cost_usd(normalized) == pytest.approx(1000 * 0.042 / 1_000_000, abs=1e-6)


def test_api_base_override_must_not_leak_the_key_over_plain_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-key")
    monkeypatch.setattr(jev.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no call expected"))
    for insecure in ("http://api.typesafe.ai", "http://evil.example/v1", "ftp://127.0.0.1", "api.typesafe.ai"):
        monkeypatch.setenv("TYPESAFE_API_BASE", insecure)
        actions, usage = jev.choose_actions(_observation("preseason"))
        assert "TYPESAFE_API_BASE" in actions[0]["model_error"], insecure
        assert usage is None
    for allowed in (
        "https://proxy.example/typesafe/",
        "http://127.0.0.1:18777",
        "http://localhost:9",
        "http://[::1]:9",
    ):
        monkeypatch.setenv("TYPESAFE_API_BASE", allowed)
        assert jev.resolve_route()["base"] == allowed.rstrip("/")


def test_openrouter_route_needs_the_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_ROUTE", "openrouter")
    monkeypatch.setenv("TYPESAFE_API_KEY", "direct-key-is-not-enough")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert "missing OPENROUTER_API_KEY" in actions[0]["model_error"]
    assert usage is None

    monkeypatch.setenv("JEV_ROUTE", "sideways")
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert "JEV_ROUTE" in actions[0]["model_error"]
    assert usage is None


def test_choose_actions_logs_the_decision_when_asked(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    def fake_urlopen(request: Any, **kwargs: Any) -> _Response:
        del kwargs
        payload = json.loads(request.data.decode())
        answers = _answer_everything(payload["questions"])
        answers.pop("release")
        return _Response({"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 0}})

    log_path = tmp_path / "jev.jsonl"
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("JEV_DECISION_LOG", str(log_path))
    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)

    actions, usage = jev.choose_actions(_observation("draft"))

    record = json.loads(log_path.read_text().splitlines()[-1])
    assert record["phase"] == "draft"
    assert record["actions"] == actions
    assert record["missing"] == ["release"]
    assert usage["telemetry_error"].startswith("1 of ")
    assert "test-key" not in log_path.read_text()


def test_choose_actions_without_key_marks_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert actions[0]["type"] == "noop"
    assert "missing TYPESAFE_API_KEY" in actions[0]["model_error"]
    assert usage is None


def test_choose_actions_reports_provider_errors_as_measured_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-key")

    class _Body:
        def read(self, size: int = -1) -> bytes:
            del size
            return json.dumps({"error": {"message": "rate limited for secret-key"}}).encode()

        def close(self) -> None:
            return None

    def raise_http(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", 429, "Too Many Requests", {}, _Body())

    monkeypatch.setattr(jev.urllib.request, "urlopen", raise_http)
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert actions[0]["type"] == "noop"
    assert "HTTP 429" in actions[0]["model_error"]
    assert "secret-key" not in actions[0]["model_error"]
    assert "[redacted]" in usage["telemetry_error"]
    assert usage["api_calls"] == 1

    monkeypatch.setattr(
        jev.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert "api_error" in actions[0]["model_error"]
    assert usage["api_latency_ms"] >= 0

    def no_answers(request: Any, **kwargs: Any) -> _Response:
        del request, kwargs
        return _Response({"model": "jev-1.13.0", "answers": {}, "usage": {"input_tokens": 5, "output_tokens": 0}})

    monkeypatch.setattr(jev.urllib.request, "urlopen", no_answers)
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert "no answers" in actions[0]["model_error"]
    assert usage["input_tokens"] == 5


def test_malformed_usage_field_still_yields_a_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, **kwargs: Any) -> _Response:
        del kwargs
        payload = json.loads(request.data.decode())
        return _Response({"model": "jev-1.13.0", "answers": _answer_everything(payload["questions"]), "usage": "n/a"})

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)
    actions, usage = jev.choose_actions(_observation("preseason"))
    validate_action_list(actions)
    assert actions[0]["type"] == "set_lineup"
    assert usage["api_calls"] == 1
    assert "input_tokens" not in usage


def test_failure_before_the_request_counts_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("JEV_NOUL_THRESHOLD", "1.5")
    monkeypatch.setattr(jev.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no call expected"))
    actions, usage = jev.choose_actions(_observation("preseason"))
    assert "JEV_NOUL_THRESHOLD" in actions[0]["model_error"]
    assert usage["api_calls"] == 0


def test_follow_up_rounds_close_the_window_without_a_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(jev.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no call expected"))
    assert jev.choose_actions({"phase": "action_results", "action_results": []}) == ([{"type": "end_turn"}], None)


def test_lane_registers_without_moving_the_frozen_fingerprints() -> None:
    """providers.py and benchmark_config.py are hashed into the frozen sota-v5
    fingerprints, so the lane registers from decision_providers.py instead."""
    from gm_bench import decision_providers, providers
    from gm_bench.benchmark_config import PROVIDER_NAMES, BenchmarkConfig
    from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
    from gm_bench.official import SOTA_V5_POLICY

    assert "typesafe" in PROVIDER_NAMES
    assert providers.PROVIDERS["typesafe"] is decision_providers.TYPESAFE
    BenchmarkConfig(provider="typesafe", seeds=[1], seasons=1).validate()
    decision_providers.register()  # idempotent
    assert providers.PROVIDER_NAMES.count("typesafe") == 1
    assert contract_fingerprint() == "a600b7da0c302231"
    assert scaffold_fingerprint("openrouter") == SOTA_V5_POLICY.expected_scaffold_fingerprints["openrouter"]
    own = scaffold_fingerprint("typesafe")
    assert own is not None and len(own) == 16 and own != scaffold_fingerprint("openai")


def test_model_command_preflight_follows_the_config_route(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """`gm-bench model --preflight-only` resolves JEV_ROUTE from the config env
    block, the same way the child will, so a bad route fails closed up front."""
    import subprocess
    import sys

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"provider": "typesafe", "preset": "smoke", "env": {"JEV_ROUTE": "sideways"}}))
    completed = subprocess.run(
        [sys.executable, "-m", "gm_bench", "model", "--config", str(bad), "--preflight-only"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "JEV_ROUTE" in completed.stderr
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gm_bench",
            "model",
            "--config",
            "examples/typesafe.jev.openrouter.smoke.json",
            "--preflight-only",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "provider preflight ok: typesafe" in completed.stdout


def test_provider_registry_and_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = resolve_provider("typesafe")
    assert spec.script == "typesafe_jev_agent.py"
    assert spec.credential_env == ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY")
    assert spec.output_ceiling_env is None, "Jev generates no tokens, so there is no output ceiling to pin"
    agent = build_provider_agent("typesafe")
    assert agent.name == "typesafe:jev-latest"
    assert agent.metadata["transport"] == "decision-api"
    assert agent.metadata["profile"] == "compact"
    assert agent.metadata["provider_options"]["JEV_ROUTE"] == "typesafe"
    assert agent.metadata["provider_options"]["JEV_NOUL_THRESHOLD"] == "0.5"
    routed = build_provider_agent("typesafe", model="typesafe/jev-1.13", extra_env={"JEV_ROUTE": "openrouter"})
    assert routed.name == "typesafe:typesafe/jev-1.13"
    assert routed.metadata["provider_options"]["JEV_ROUTE"] == "openrouter"
    assert agent.metadata["provider_options"]["JEV_ENABLE_TRADES"] == "1"

    # The strict preflight demands the key for the route the child will run
    # under, resolved exactly as build_provider_agent resolves it: a config
    # env entry beats the spec pin, and the pin beats the shell. A shell-only
    # JEV_ROUTE therefore changes nothing, on either side.
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    preflight_provider("typesafe")
    with pytest.raises(ModelRunAborted, match="set TYPESAFE_API_KEY"):
        preflight_provider("typesafe", require_credentials=True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "present")
    monkeypatch.setenv("JEV_ROUTE", "openrouter")
    with pytest.raises(ModelRunAborted, match="set TYPESAFE_API_KEY"):
        preflight_provider("typesafe", require_credentials=True)
    assert build_provider_agent("typesafe").metadata["provider_options"]["JEV_ROUTE"] == "typesafe"
    switched = {"JEV_ROUTE": "openrouter"}
    preflight_provider("typesafe", require_credentials=True, extra_env=switched)
    assert (
        build_provider_agent("typesafe", extra_env=switched).metadata["provider_options"]["JEV_ROUTE"] == "openrouter"
    )
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("TYPESAFE_API_KEY", "present")
    with pytest.raises(ModelRunAborted, match="set OPENROUTER_API_KEY"):
        preflight_provider("typesafe", require_credentials=True, extra_env=switched)
    monkeypatch.setenv("JEV_ROUTE", "sideways")
    preflight_provider("typesafe")  # the shell value never reaches the child
    with pytest.raises(ModelRunAborted, match="JEV_ROUTE"):
        preflight_provider("typesafe", extra_env={"JEV_ROUTE": "sideways"})
