"""Checkout and wheel resource-resolution regressions."""

from __future__ import annotations

from pathlib import Path

from gm_bench import contract, providers


def _fake_package(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "site-packages"
    package_root = root / "gm_bench"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("")
    resources = package_root / "_resources"
    (resources / "examples").mkdir(parents=True)
    (resources / "schemas").mkdir()
    return root, package_root


def test_ambient_site_packages_siblings_cannot_override_resources(tmp_path, monkeypatch) -> None:
    root, package_root = _fake_package(tmp_path)
    ambient_example = root / "examples" / "gm_agent_common.py"
    ambient_example.parent.mkdir()
    ambient_example.write_text("ambient")
    ambient_schema = root / "schemas" / "gm_actions.schema.json"
    ambient_schema.parent.mkdir()
    ambient_schema.write_text("ambient")
    packaged_example = package_root / "_resources" / "examples" / "gm_agent_common.py"
    packaged_example.write_text("packaged")
    packaged_schema = package_root / "_resources" / "schemas" / "gm_actions.schema.json"
    packaged_schema.write_text("packaged")
    monkeypatch.setattr(contract, "_ROOT", root)
    monkeypatch.setattr(contract, "_PACKAGE_ROOT", package_root)
    monkeypatch.setattr(providers, "_PACKAGE_ROOT", package_root)

    assert contract._repository_checkout_root() is None
    assert contract._source_path("examples/gm_agent_common.py") == packaged_example
    assert contract._source_path("schemas/gm_actions.schema.json") == packaged_schema
    assert providers._examples_path() == package_root / "_resources" / "examples"


def test_verified_repository_checkout_prefers_source_resources(tmp_path, monkeypatch) -> None:
    root, package_root = _fake_package(tmp_path)
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "gm-bench"\n')
    checkout_example = root / "examples" / "gm_agent_common.py"
    checkout_example.parent.mkdir()
    checkout_example.write_text("checkout")
    monkeypatch.setattr(contract, "_ROOT", root)
    monkeypatch.setattr(contract, "_PACKAGE_ROOT", package_root)
    monkeypatch.setattr(providers, "_PACKAGE_ROOT", package_root)

    assert contract._repository_checkout_root() == root
    assert contract._source_path("examples/gm_agent_common.py") == checkout_example
    assert providers._examples_path() == root / "examples"


def test_scaffold_fingerprint_covers_provider_registry_and_resolved_examples(tmp_path, monkeypatch) -> None:
    seen: list[str] = []

    def fake_source_path(relative_path: str) -> Path:
        seen.append(relative_path)
        target = tmp_path / relative_path.replace("/", "-")
        target.write_text(relative_path)
        return target

    monkeypatch.setattr(contract, "_source_path", fake_source_path)

    assert contract.scaffold_fingerprint("openrouter")
    assert seen == [
        "gm_bench/providers.py",
        "gm_bench/scaffold_view.py",
        "examples/gm_agent_common.py",
        "examples/openrouter_agent.py",
    ]
