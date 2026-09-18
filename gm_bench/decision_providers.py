"""Decision-model lanes, registered beside the frozen chat-provider registry.

``gm_bench/providers.py`` is hashed into every provider's scaffold fingerprint
and ``gm_bench/benchmark_config.py`` into the benchmark contract fingerprint,
so adding a lane to either file after the sota-v5 freeze would move the
recorded fingerprints of every published row (``c582e126bbb6af10`` for the
OpenRouter scaffold, ``a600b7da0c302231`` for the contract) and fail release
verification. Lanes added after the freeze are declared here instead and
registered into the live registry when the package is imported, which
``gm_bench/__init__.py`` does before any consumer reads ``PROVIDER_NAMES``.

A lane registered here is fingerprinted with this file in place of a change
to ``providers.py``: see ``gm_bench.contract.scaffold_fingerprint``.
"""

from __future__ import annotations

from gm_bench import providers
from gm_bench.providers import ProviderSpec

# TypeSafe's Jev is a decision model, not a chat model: it answers typed
# questions about the observation and the adapter composes the action batch
# from those answers under published rules (docs/typesafe_jev_lane.md). It
# gets its own transport label so a Jev row is never silently compared with a
# direct-api chat row, and no output ceiling because it generates no tokens.
# One HTTP call per phase carries the whole question batch.
TYPESAFE = ProviderSpec(
    name="typesafe",
    script="typesafe_jev_agent.py",
    model_env="TYPESAFE_MODEL",
    default_model="jev-latest",
    default_timeout=120.0,
    default_profile="compact",
    transport="decision-api",
    # Either key works, depending on JEV_ROUTE: the direct TypeSafe API or
    # OpenRouter's decisions endpoint, which resells the same model.
    credential_env=("TYPESAFE_API_KEY", "OPENROUTER_API_KEY"),
    extra_env={"JEV_ROUTE": "typesafe", "JEV_NOUL_THRESHOLD": "0.5", "JEV_ENABLE_TRADES": "1"},
    provenance_env=("JEV_ROUTE", "TYPESAFE_API_BASE", "JEV_NOUL_THRESHOLD", "JEV_ENABLE_TRADES"),
)

DECISION_PROVIDERS: dict[str, ProviderSpec] = {TYPESAFE.name: TYPESAFE}

# The credential each JEV_ROUTE needs. The adapter reads it to pick a key and
# the strict credential preflight reads it so a recorder is refused up front
# rather than after two failed decisions.
ROUTE_CREDENTIALS: dict[str, str] = {"typesafe": "TYPESAFE_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
DEFAULT_JEV_ROUTE = "typesafe"


def route_credential(route: str | None) -> str:
    """The credential env var for a JEV_ROUTE value, or ValueError if unknown."""
    name = (route or DEFAULT_JEV_ROUTE).strip().lower()
    if name not in ROUTE_CREDENTIALS:
        raise ValueError(f"JEV_ROUTE must be one of {', '.join(sorted(ROUTE_CREDENTIALS))}; got {name!r}")
    return ROUTE_CREDENTIALS[name]


def register() -> None:
    """Add the decision lanes to the live provider registry, idempotently.

    ``PROVIDERS`` is the dict every lookup reads at call time. ``PROVIDER_NAMES``
    is a tuple that ``cli.py`` and ``benchmark_config.py`` bind by name when they
    are imported, so it is rebound here before either of them loads.
    """
    for name, spec in DECISION_PROVIDERS.items():
        providers.PROVIDERS.setdefault(name, spec)
    missing = tuple(name for name in DECISION_PROVIDERS if name not in providers.PROVIDER_NAMES)
    if missing:
        providers.PROVIDER_NAMES = (*providers.PROVIDER_NAMES, *missing)


register()
