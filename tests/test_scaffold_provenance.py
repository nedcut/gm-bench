"""Scaffold-fingerprint provenance tests."""

from gm_bench.contract import scaffold_fingerprint
from gm_bench.official import _validate_scaffold_provenance


def test_scaffold_fingerprint_known_provider_is_stable_hex() -> None:
    first = scaffold_fingerprint("ollama")
    assert first is not None
    assert len(first) == 16
    assert first == scaffold_fingerprint("ollama")
    int(first, 16)


def test_scaffold_fingerprint_differs_across_providers() -> None:
    assert scaffold_fingerprint("ollama") != scaffold_fingerprint("codex")


def test_scaffold_fingerprint_unknown_provider_is_none() -> None:
    assert scaffold_fingerprint("not-a-provider") is None


def test_validator_warns_when_fingerprint_missing() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_scaffold_provenance(errors, warnings, {"provider": "ollama"})
    assert not errors
    assert any("scaffold_fingerprint missing" in w for w in warnings)


def test_validator_errors_on_mismatch() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_scaffold_provenance(
        errors, warnings, {"provider": "ollama", "scaffold_fingerprint": "0" * 16}
    )
    assert any("does not match current scaffold" in e for e in errors)


def test_validator_accepts_current_fingerprint() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_scaffold_provenance(
        errors,
        warnings,
        {"provider": "ollama", "scaffold_fingerprint": scaffold_fingerprint("ollama")},
    )
    assert not errors
    assert not warnings


def test_validator_warns_on_unknown_provider_with_fingerprint() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_scaffold_provenance(
        errors, warnings, {"provider": "someones-fork", "scaffold_fingerprint": "abc"}
    )
    assert not errors
    assert any("not a built-in provider" in w for w in warnings)
