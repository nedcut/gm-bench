"""Deterministic, unpaid repair of malformed adapter output.

The v6 execution rules (docs/bench_v6_spec.md) allow exactly one paid model
call per decision phase, so a model that emits unusable output gets no second
chance to fix it. What it gets instead is this fixed, published list of local
repairs, applied at no cost and only where the intent is unambiguous:

``strip_code_fence``
    The payload is wrapped in exactly one Markdown fence. More than one fenced
    block is ambiguous -- there is no rule that says which one is the answer.
``strip_surrounding_prose``
    Exactly one balanced JSON value sits inside surrounding chatter. A second
    bracketed value after it is ambiguous for the same reason.
``strip_trailing_comma``
    A comma directly before ``]`` or ``}`` outside a string. JSON has one
    reading of the author's intent here, so removing it invents nothing.
``wrap_single_action``
    A lone action object where a list was required.
``normalize_action_type``
    An action ``type`` that maps onto exactly one canonical type after
    case-folding and turning spaces and hyphens into underscores
    (``"SET-LINEUP"`` -> ``set_lineup``). A near-miss like ``"sign"`` matches
    nothing and stays malformed rather than being guessed at.
``coerce_numeric_string``
    A decimal number delivered as a JSON string in a field the action schema
    declares numeric (``"player_id": "42"``). Anything that is not a plain
    decimal literal -- ``"42nd"``, ``"1e3"``, ``"0x2a"`` -- is left alone.

Anything these rules cannot settle becomes a structured no-op for the whole
phase: the model's turn is recorded as unrecoverable and nothing it did not
clearly ask for moves roster state. Repair never changes which actions were
requested, only how they were spelled, so it cannot lift a score; it exists so
a formatting slip is measured as a formatting slip instead of silently
deciding the episode.

Model adapters do not parse or repair the model's reply themselves. They put
it verbatim in the envelope's ``raw_text`` field beside their usage block, so
these rules are the only ones that decide what a reply means and the recorded
malformed rate is the model's own formatting record. A bare ``actions`` list is
still accepted, for third-party adapters and for the case where an adapter
failed before the model answered and has no model text to forward.

Two markers travel back to the runner on the first action, mirroring the
existing ``error``/``model_error`` convention: ``malformed_output`` (why the
raw output was not usable as delivered) and ``repaired_by`` (which rules made
it usable). Adapter-supplied copies of both are stripped on the way in, so an
adapter cannot label its own output as harness-repaired.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from gm_bench.action_validation import (
    ACTION_TYPES,
    INTEGER_FIELDS,
    INTEGER_LIST_FIELDS,
    NUMBER_FIELDS,
    validate_action_list,
)
from gm_bench.telemetry import require_finite_json_numbers

MALFORMED_MARKER = "malformed_output"
REPAIR_MARKER = "repaired_by"
# Envelope field carrying the model's reply exactly as the backend returned it.
RAW_TEXT_FIELD = "raw_text"
RESERVED_MARKERS = (MALFORMED_MARKER, REPAIR_MARKER)

RULE_STRIP_CODE_FENCE = "strip_code_fence"
RULE_STRIP_SURROUNDING_PROSE = "strip_surrounding_prose"
RULE_STRIP_TRAILING_COMMA = "strip_trailing_comma"
RULE_WRAP_SINGLE_ACTION = "wrap_single_action"
RULE_NORMALIZE_ACTION_TYPE = "normalize_action_type"
RULE_COERCE_NUMERIC_STRING = "coerce_numeric_string"

# Published order. Text-shape rules run before structure-shape rules because a
# fenced payload has to become JSON before its fields can be inspected.
REPAIR_RULES = (
    RULE_STRIP_CODE_FENCE,
    RULE_STRIP_SURROUNDING_PROSE,
    RULE_STRIP_TRAILING_COMMA,
    RULE_WRAP_SINGLE_ACTION,
    RULE_NORMALIZE_ACTION_TYPE,
    RULE_COERCE_NUMERIC_STRING,
)

_FENCE_PATTERN = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)
_DECIMAL_PATTERN = re.compile(r"^[+-]?[0-9]+$")
_NUMBER_PATTERN = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")
_CANONICAL_ACTION_TYPES = {action_type: action_type for action_type in ACTION_TYPES}
_NUMERIC_FIELDS = INTEGER_FIELDS | NUMBER_FIELDS


@dataclass(frozen=True)
class RepairOutcome:
    """One decision's worth of adapter output after local repair."""

    actions: list[dict[str, Any]]
    usage: Any
    malformed: bool
    unrecoverable: bool
    rules_applied: tuple[str, ...]
    reason: str | None


def structured_noop(reason: str) -> list[dict[str, Any]]:
    """The action list recorded when a phase's output cannot be repaired.

    It carries ``error`` as well as ``malformed_output`` so the decision counts
    as failed under the existing accounting and as unrecoverable under the new
    accounting: one no-op, two independently reported facts.
    """
    text = reason[:300]
    return [{"type": "noop", "error": text, MALFORMED_MARKER: text}]


def repair_adapter_output(text: str, *, source: str) -> RepairOutcome:
    """Turn one adapter's raw stdout into a usable action list, without paying.

    ``source`` names the transport for the recorded reason ("external agent",
    "persistent agent") so an operator reading results can tell which lane
    produced the malformed output.
    """
    payload, text_rules, text_error = _parse_payload(text)
    if text_error is not None:
        return _unrecoverable(f"{source} {text_error}")

    # The adapter's own envelope is transport, not model output: its usage is
    # kept whatever the model's text turns out to be, and the repair rules are
    # applied to the model's text rather than to the envelope around it.
    envelope_usage = _envelope_usage(payload)
    raw_text = _raw_model_text(payload)
    if raw_text is not None:
        payload, text_rules, text_error = _parse_payload(raw_text)
        if text_error is not None:
            return _unrecoverable(f"{source} model {text_error}", usage=envelope_usage)

    actions, usage, shape_rules, shape_error = _extract_actions(payload)
    if shape_error is not None:
        return _unrecoverable(f"{source} {shape_error}", usage=envelope_usage)
    if raw_text is not None:
        # Telemetry comes from the adapter, never from inside the model's own
        # text, which must not be able to declare what its call cost.
        usage = envelope_usage

    actions = [_without_reserved_markers(action) for action in actions]
    rules = text_rules + shape_rules

    outcome_error = _reject_non_finite(actions)
    if outcome_error is not None:
        return _unrecoverable(f"{source} {outcome_error}", usage=usage)

    validation_error = _validation_error(actions)
    if validation_error is not None:
        actions, structural_rules = _repair_structure(actions)
        rules = rules + structural_rules
        validation_error = _validation_error(actions)
        if validation_error is not None:
            return _unrecoverable(f"{source} returned invalid actions: {validation_error}", usage=usage)

    if not rules:
        return RepairOutcome(
            actions=actions,
            usage=usage,
            malformed=False,
            unrecoverable=False,
            rules_applied=(),
            reason=None,
        )
    reason = f"{source} output needed local repair"
    marked = [dict(action) for action in actions]
    if not marked:
        marked = [{"type": "noop"}]
    marked[0][MALFORMED_MARKER] = reason
    marked[0][REPAIR_MARKER] = ",".join(rules)
    return RepairOutcome(
        actions=marked,
        usage=usage,
        malformed=True,
        unrecoverable=False,
        rules_applied=rules,
        reason=reason,
    )


def is_malformed(actions: Any) -> bool:
    """Whether a decision's actions came from output the model got wrong.

    Covers both the harness marker set by local repair and the adapter's own
    ``model_error`` marker, which means the adapter could not use what the
    model returned. A transport failure (timeout, crashed process) carries
    ``error`` alone and is deliberately not counted here: it is the harness's
    problem, not evidence about the model's formatting.
    """
    if not isinstance(actions, list):
        return False
    return any(
        isinstance(action, dict) and (MALFORMED_MARKER in action or "model_error" in action) for action in actions
    )


def is_unrecoverable(actions: Any) -> bool:
    """Whether malformed output for this decision could not be locally repaired."""
    if not is_malformed(actions):
        return False
    return not any(isinstance(action, dict) and REPAIR_MARKER in action for action in actions)


def _unrecoverable(reason: str, *, usage: Any = None) -> RepairOutcome:
    """A structured no-op that still reports the tokens the call actually cost.

    The decision is worthless, but it was paid for. Dropping the usage would
    understate the run's cost and, worse, hand the spend guard a call with no
    finite cost telemetry -- which fails closed and halts the whole run over
    one garbled reply. A decision with no usage at all (crashed adapter) still
    reports nothing, and still fails closed.
    """
    return RepairOutcome(
        actions=structured_noop(reason),
        usage=usage,
        malformed=True,
        unrecoverable=True,
        rules_applied=(),
        reason=reason[:300],
    )


def _envelope_usage(payload: Any) -> Any:
    if isinstance(payload, dict) and RAW_TEXT_FIELD in payload:
        return payload.get("usage")
    return None


def _raw_model_text(payload: Any) -> str | None:
    """The model's verbatim reply, when the adapter forwarded one."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get(RAW_TEXT_FIELD)
    return raw if isinstance(raw, str) else None


def _without_reserved_markers(action: Any) -> Any:
    if not isinstance(action, dict):
        return action
    if not any(marker in action for marker in RESERVED_MARKERS):
        return action
    return {key: value for key, value in action.items() if key not in RESERVED_MARKERS}


def _reject_non_finite(actions: list[Any]) -> str | None:
    try:
        require_finite_json_numbers(actions)
    except ValueError:
        return "returned non-finite action values"
    return None


def _validation_error(actions: list[Any]) -> str | None:
    try:
        validate_action_list(actions)
    except ValueError as exc:
        return str(exc)
    return None


def _parse_payload(text: str) -> tuple[Any, tuple[str, ...], str | None]:
    """Parse adapter stdout, applying text-shape rules only as far as needed."""
    try:
        return json.loads(text), (), None
    except json.JSONDecodeError:
        pass
    candidate = text
    rules: list[str] = []
    for rule, transform in (
        (RULE_STRIP_CODE_FENCE, _strip_code_fence),
        (RULE_STRIP_SURROUNDING_PROSE, _strip_surrounding_prose),
        (RULE_STRIP_TRAILING_COMMA, _strip_trailing_comma),
    ):
        changed = transform(candidate)
        # A rule that only moves surrounding whitespace did not repair anything
        # -- JSON ignores it -- and must not be reported as having run:
        # `repaired_by` is evidence about the model's output, not a log of which
        # checks the harness performed.
        if changed is None or changed.strip() == candidate.strip():
            continue
        candidate = changed
        rules.append(rule)
        try:
            return json.loads(candidate), tuple(rules), None
        except json.JSONDecodeError:
            continue
    return None, (), "returned invalid JSON"


def _strip_code_fence(text: str) -> str | None:
    """Unwrap the payload when exactly one Markdown fence encloses it."""
    blocks = _FENCE_PATTERN.findall(text)
    if len(blocks) != 1:
        return None
    return blocks[0]


def _strip_surrounding_prose(text: str) -> str | None:
    """Keep the single balanced JSON value embedded in surrounding chatter."""
    start = _first_json_start(text)
    if start is None:
        return None
    end = _balanced_end(text, start)
    if end is None:
        return None
    if _first_json_start(text[end:]) is not None:
        return None
    return text[start:end]


def _first_json_start(text: str) -> int | None:
    for index, character in enumerate(text):
        if character in "[{":
            return index
    return None


def _balanced_end(text: str, start: int) -> int | None:
    """Index just past the balanced bracket run that begins at ``start``."""
    openers = {"[": "]", "{": "}"}
    stack: list[str] = []
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in openers:
            stack.append(openers[character])
        elif character in "]}":
            if not stack or stack[-1] != character:
                return None
            stack.pop()
            if not stack:
                return index + 1
    return None


def _strip_trailing_comma(text: str) -> str | None:
    """Drop commas that sit directly before a closing bracket, outside strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    changed = False
    for index, character in enumerate(text):
        if in_string:
            out.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            out.append(character)
            continue
        if character == ",":
            remainder = text[index + 1 :]
            stripped = remainder.lstrip()
            if stripped[:1] in ("]", "}"):
                changed = True
                continue
        out.append(character)
    return "".join(out) if changed else None


def _extract_actions(payload: Any) -> tuple[list[Any], Any, tuple[str, ...], str | None]:
    """Pull the action list and usage block out of either accepted stdout shape."""
    if isinstance(payload, list):
        return payload, None, (), None
    if isinstance(payload, dict):
        actions = payload.get("actions")
        if isinstance(actions, list):
            return actions, payload.get("usage"), (), None
        if isinstance(actions, dict) and isinstance(actions.get("actions"), list):
            return actions["actions"], payload.get("usage"), (), None
        if isinstance(payload.get("type"), str):
            return [payload], None, (RULE_WRAP_SINGLE_ACTION,), None
    return [], None, (), "must return an action list or envelope"


def _repair_structure(actions: list[Any]) -> tuple[list[Any], tuple[str, ...]]:
    """Apply the field-level rules, reporting only the ones that changed something."""
    repaired: list[Any] = []
    rules: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            repaired.append(action)
            continue
        updated = dict(action)
        canonical = _canonical_action_type(updated.get("type"))
        if canonical is not None:
            updated["type"] = canonical
            if RULE_NORMALIZE_ACTION_TYPE not in rules:
                rules.append(RULE_NORMALIZE_ACTION_TYPE)
        if _coerce_numeric_strings(updated) and RULE_COERCE_NUMERIC_STRING not in rules:
            rules.append(RULE_COERCE_NUMERIC_STRING)
        repaired.append(updated)
    return repaired, tuple(rules)


def _canonical_action_type(raw: Any) -> str | None:
    """The one canonical type this spelling maps to, or None if it is a guess."""
    if not isinstance(raw, str) or raw in _CANONICAL_ACTION_TYPES:
        return None
    key = raw.strip().casefold().replace("-", "_").replace(" ", "_")
    return _CANONICAL_ACTION_TYPES.get(key)


def _coerce_numeric_strings(action: dict[str, Any]) -> bool:
    changed = False
    for key, value in list(action.items()):
        if key in _NUMERIC_FIELDS and isinstance(value, str):
            coerced = _numeric_from_string(value, integer_only=key in INTEGER_FIELDS)
            if coerced is not None:
                action[key] = coerced
                changed = True
        elif key in INTEGER_LIST_FIELDS and isinstance(value, list):
            coerced_items = [
                _numeric_from_string(item, integer_only=True) if isinstance(item, str) else item for item in value
            ]
            if any(item is None for item in coerced_items):
                continue
            if coerced_items != value:
                action[key] = coerced_items
                changed = True
    return changed


def _numeric_from_string(value: str, *, integer_only: bool) -> int | float | None:
    pattern = _DECIMAL_PATTERN if integer_only else _NUMBER_PATTERN
    if not pattern.match(value):
        return None
    return int(value) if integer_only or "." not in value else float(value)
