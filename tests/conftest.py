from __future__ import annotations

from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner


@pytest.fixture(autouse=True)
def isolate_baseline_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the baseline cache so tests never touch the repo's data/ directory.

    Also inherited by subprocess-based CLI tests via the environment.
    """
    monkeypatch.setenv("GM_BENCH_BASELINE_CACHE", str(tmp_path / "baseline_cache.json"))


@pytest.fixture(autouse=True)
def block_real_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the test suite from ever authenticating against a paid provider.

    The publication runner calls ``load_environment_files(ROOT)`` at startup,
    which reads the gitignored ``.env.local`` out of the working tree. Any test
    that drives ``main()`` through a paid phase without stubbing out the child
    process therefore runs the real benchmark against real routes and bills a
    real account -- with no failure to signal it, because the run succeeds.
    That is exactly what happened on 2026-08-04: a test written to assert that
    a spend ceiling *blocks* a run instead spent $0.44 across 38 live calls,
    because the fixture lane it resolved to had every gate already unlocked.

    Neutralising the loader is enough. Tests that need a credential present
    still set one explicitly with ``monkeypatch.setenv``, which continues to
    work; what they cannot do any more is silently inherit a live key.
    """
    monkeypatch.setattr(publication_runner, "load_environment_files", lambda _root: [])
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
