"""Which driver code played a 2.0 run: every agentic file classified, digest and git state recorded."""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from gm_bench.agentic import contract, provenance
from gm_bench.agentic.provenance import (
    CONTRACT_SOURCES,
    DRIVER_SOURCES,
    POST_HOC_SOURCES,
    RECORD_SOURCES,
    dirty_files,
    dirty_played_files,
    driver_digest,
    driver_provenance,
    provenance_problems,
    reproducible_driver,
)

PACKAGE = Path("gm_bench/agentic")
CLASSES = {
    "contract": CONTRACT_SOURCES,
    "driver": DRIVER_SOURCES,
    "record": RECORD_SOURCES,
    "post-hoc": POST_HOC_SOURCES,
}


def test_every_agentic_file_is_classified_exactly_once() -> None:
    """A new module must be declared contract, driver, record or post-hoc before it can ship."""
    present = sorted(
        str(path)
        for path in PACKAGE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    classified = [name for names in CLASSES.values() for name in names]
    assert len(classified) == len(set(classified)), "a file is in two classes"
    assert sorted(classified) == present


def test_contract_class_is_exactly_what_the_fingerprint_hashes() -> None:
    assert CONTRACT_SOURCES == tuple(f"gm_bench/agentic/{name}" for name in contract._AGENTIC_CONTRACT_SOURCES)
    assert not set(DRIVER_SOURCES) & set(CONTRACT_SOURCES)


def _agentic_imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("gm_bench.agentic"):
            if node.module == "gm_bench.agentic":
                imported.update(f"gm_bench/agentic/{alias.name}.py" for alias in node.names)
            else:
                imported.add(node.module.replace(".", "/") + ".py")
        elif isinstance(node, ast.Import):
            imported.update(
                alias.name.replace(".", "/") + ".py"
                for alias in node.names
                if alias.name.startswith("gm_bench.agentic.")
            )
    return imported


def test_driver_and_contract_code_never_imports_post_hoc_code() -> None:
    """Otherwise a fix to publication or validation would silently change play without moving the digest."""
    for name in DRIVER_SOURCES + CONTRACT_SOURCES + RECORD_SOURCES:
        assert not _agentic_imports(Path(name)) & set(POST_HOC_SOURCES), name


def test_recording_the_driver_leaves_the_fingerprint_alone() -> None:
    assert contract.agentic_fingerprint() == "07de948a4f4afbae"
    assert "driver" not in contract.agentic_contract()


def _copy_package(root: Path) -> None:
    for name in CONTRACT_SOURCES + DRIVER_SOURCES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, root / name)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_digest_covers_the_driver_files_bytes_and_names_only(tmp_path: Path) -> None:
    _copy_package(tmp_path)
    assert driver_digest(root=tmp_path) == driver_digest()
    assert driver_digest(tuple(reversed(DRIVER_SOURCES)), root=tmp_path) == driver_digest()
    before = driver_digest(root=tmp_path)
    (tmp_path / CONTRACT_SOURCES[0]).write_text("# not the driver\n")
    assert driver_digest(root=tmp_path) == before
    with (tmp_path / "gm_bench/agentic/_proxy.py").open("a") as handle:
        handle.write("# one byte of driver\n")
    assert driver_digest(root=tmp_path) != before


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_provenance_records_the_commit_and_whether_the_driver_matched_it(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    _copy_package(root)
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "x")
    head = _git(root, "rev-parse", "HEAD")

    record = driver_provenance(root)
    assert record == {
        "driver_digest": driver_digest(root=root),
        "driver_files": list(DRIVER_SOURCES),
        "git_head": head,
        "git_driver_clean": True,
        "changed_during_run": False,
    }
    assert reproducible_driver(record)
    assert dirty_played_files(root) == []

    # A contract edit leaves the driver clean but blocks a panel launch.
    (root / "gm_bench/agentic/tools.py").write_text("# edited\n")
    assert driver_provenance(root)["git_driver_clean"] is True
    assert dirty_played_files(root) == ["gm_bench/agentic/tools.py"]
    _git(root, "checkout", "--", "gm_bench/agentic/tools.py")

    # Modified, staged, or untracked driver files are all dirty.
    (root / "gm_bench/agentic/codex.py").write_text("# edited\n")
    assert driver_provenance(root)["git_driver_clean"] is False
    _git(root, "add", "gm_bench/agentic/codex.py")
    assert dirty_files(DRIVER_SOURCES, root) == ["gm_bench/agentic/codex.py"]
    _git(root, "reset", "-q", "--hard")
    _git(root, "rm", "-q", "--cached", "gm_bench/agentic/harness.py")
    _git(root, "commit", "-q", "-m", "untrack")
    assert dirty_files(DRIVER_SOURCES, root) == ["gm_bench/agentic/harness.py"]
    assert not reproducible_driver(driver_provenance(root))

    # A staged rename between driver files names both paths whole.
    (root / "gm_bench/agentic/harness.py").unlink()
    _git(root, "mv", "gm_bench/agentic/codex.py", "gm_bench/agentic/harness.py")
    assert dirty_files(DRIVER_SOURCES, root) == ["gm_bench/agentic/codex.py", "gm_bench/agentic/harness.py"]


def test_outside_a_git_checkout_the_commit_is_unknown(tmp_path: Path) -> None:
    root = tmp_path / "install"
    _copy_package(root)
    record = driver_provenance(root)
    assert record["git_head"] is None and record["git_driver_clean"] is None
    assert record["driver_digest"] == driver_digest()
    assert dirty_played_files(root) is None
    assert not reproducible_driver(record)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_an_install_inside_another_repository_does_not_borrow_its_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    root = tmp_path / ".venv" / "site-packages"
    _copy_package(root)
    assert driver_provenance(root)["git_head"] is None


def test_a_git_failure_is_unknown_not_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args, **_kwargs):
        raise OSError("no git")

    monkeypatch.setattr(provenance.subprocess, "run", broken)
    record = driver_provenance()
    assert record["git_head"] is None and record["git_driver_clean"] is None
    assert dirty_played_files() is None


def test_malformed_driver_blocks_are_named() -> None:
    good = {
        "driver_digest": "0123456789abcdef",
        "driver_files": ["gm_bench/agentic/opencode.py"],
        "git_head": "a" * 40,
        "git_driver_clean": True,
        "changed_during_run": False,
    }
    assert provenance_problems(good) == []
    assert provenance_problems("x") == ["driver must be an object"]
    assert any("missing" in p for p in provenance_problems({k: v for k, v in good.items() if k != "git_head"}))
    assert any("driver_digest" in p for p in provenance_problems(dict(good, driver_digest="XYZ")))
    assert any("driver_files" in p for p in provenance_problems(dict(good, driver_files=[])))
    assert any("git_head" in p for p in provenance_problems(dict(good, git_head="main")))
    assert any("git_driver_clean" in p for p in provenance_problems(dict(good, git_driver_clean="yes")))
    assert any("changed_during_run" in p for p in provenance_problems(dict(good, changed_during_run=None)))
    assert not reproducible_driver(dict(good, changed_during_run=True))
    assert not reproducible_driver(dict(good, git_head=None, git_driver_clean=None))


def test_run_panel_records_a_driver_edited_mid_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from gm_bench.agentic import opencode

    monkeypatch.setattr(opencode, "run_episode", lambda seed, **kwargs: {"seed": seed})
    monkeypatch.setattr(opencode, "opencode_version", lambda binary: "x")
    monkeypatch.setattr(opencode, "summarize_episodes", lambda episodes: {})
    monkeypatch.setattr(opencode, "_agentic_summary", lambda episodes: {})
    monkeypatch.setattr(opencode, "driver_digest", lambda: "f" * 16)  # the bytes on disk at the end

    opencode.run_panel([11], model="m", run_dir=tmp_path)
    recorded = json.loads((tmp_path / "run.json").read_text())["driver"]
    assert recorded["driver_digest"] == driver_digest()  # taken at the start
    assert recorded["changed_during_run"] is True
    assert not reproducible_driver(recorded)
