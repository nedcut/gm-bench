from __future__ import annotations

from pathlib import Path

import pytest

from gm_bench.providers import PROVIDERS


@pytest.fixture(autouse=True)
def isolate_baseline_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the baseline cache so tests never touch the repo's data/ directory.

    Also inherited by subprocess-based CLI tests via the environment.
    """
    monkeypatch.setenv("GM_BENCH_BASELINE_CACHE", str(tmp_path / "baseline_cache.json"))


@pytest.fixture(autouse=True)
def block_real_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the test suite from ever authenticating against a paid provider.

    Every entry point (the publication runner, the CLI, the route-evidence
    collector) calls ``load_environment_files`` at startup, which reads the
    gitignored ``.env.local`` out of the working tree. Any test that reaches a
    paid phase without stubbing out the provider call therefore runs the real
    benchmark against real routes and bills a real account -- with no failure
    to signal it, because the run succeeds. That is exactly what happened on
    2026-08-04: a test written to assert that a spend ceiling *blocks* a run
    instead spent $0.44 across 38 live calls, because the fixture lane it
    resolved to had every gate already unlocked.

    ``GM_BENCH_DISABLE_ENV_FILES`` neutralises the loader at its source module
    rather than patching one importer's reference, so it also covers tests
    that drive the CLI as a subprocess (the child inherits the variable) and
    any future script that adds its own ``load_environment_files`` call.
    Tests that need a credential present still set one explicitly with
    ``monkeypatch.setenv``, which continues to work; what they cannot do any
    more is silently inherit a live key.
    """
    monkeypatch.setenv("GM_BENCH_DISABLE_ENV_FILES", "1")
    credential_names = {
        "LLM_API_KEY",
        *(name for spec in PROVIDERS.values() for name in spec.credential_env),
    }
    for name in credential_names:
        monkeypatch.delenv(name, raising=False)
