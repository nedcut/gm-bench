"""Which driver code played a GM-Bench 2.0 run.

The 2.0 fingerprint (``contract.agentic_fingerprint``) covers what the agent
is measured through: the tool surface, the brief, the episode engine and the
server. It deliberately leaves out the driver: the shared episode loop
(nudges, provider-stall retries and resumes, the phase guard, silent-harness
detection, quota pauses), the harness adapters and the configuration they
stage, the container launcher with its Dockerfiles and firewall, and the
stdio proxy. A driver fix is not a new benchmark, so it must not move the
fingerprint, but two rows played by different driver code are not the same
measurement either. So every run records the driver it ran on, beside the
fingerprint rather than inside it:

- ``driver_digest``: a SHA-256 prefix over the driver files' names and bytes,
  computed when the run starts;
- ``driver_files``: the files that digest covers;
- ``git_head`` and ``git_driver_clean``: the commit the checkout was on and
  whether every driver file matched it (``None`` outside a git checkout), so
  a clean row can be replayed from that commit;
- ``changed_during_run``: whether the driver files' bytes differed when the
  run finished (the proxy is copied from disk for every episode).

Every file in ``gm_bench/agentic/`` is classified below, and a test fails
when a file is left unclassified or a driver file imports a post-hoc one:

- contract: fingerprinted, the measurement itself;
- driver: plays the episode, recorded by ``driver_digest``;
- record: names the run's identity (this file, ``contract.py``) or only
  documents the package; the driver imports them to write ``run.json`` but
  they change nothing about play;
- post-hoc: reads, checks or publishes a finished run, so fixing them does
  not look like a driver change.

Driver code outside this package is already identified elsewhere: the
harness environment filter (``gm_bench/agents.py``) and the run summary
(``gm_bench/runner.py``) are 1.0 contract sources, carried in every row as
``base_contract_fingerprint``. The CLI's defaults for the driver's knobs are
recorded in ``run.json`` as values, not as code.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from gm_bench.agentic.contract import _AGENTIC_CONTRACT_SOURCES

_PACKAGE = "gm_bench/agentic"
# The checkout (or install prefix) that holds ``gm_bench/``.
_ROOT = Path(__file__).resolve().parents[2]

#: Fingerprinted by ``contract.agentic_fingerprint``.
CONTRACT_SOURCES = tuple(f"{_PACKAGE}/{name}" for name in _AGENTIC_CONTRACT_SOURCES)
#: Shape how an episode is played, and are not fingerprinted.
DRIVER_SOURCES = (
    f"{_PACKAGE}/_proxy.py",  # copied into the agent's workspace; the harness launches it
    f"{_PACKAGE}/claude.py",  # Claude Code adapter
    f"{_PACKAGE}/codex.py",  # Codex CLI adapter
    f"{_PACKAGE}/container.py",  # Docker launcher: Dockerfiles, pinned harness versions, egress firewall
    f"{_PACKAGE}/harness.py",  # the interface the shared loop calls
    f"{_PACKAGE}/opencode.py",  # OpenCode adapter and the shared episode loop
)
#: Name the run's identity or document the package; change nothing about play.
RECORD_SOURCES = (
    f"{_PACKAGE}/__init__.py",  # docstring only
    f"{_PACKAGE}/contract.py",  # computes the contract block the run records
    f"{_PACKAGE}/provenance.py",  # this file: records the driver, does not drive
)
#: Read, check or publish a finished run; never imported by driver code.
POST_HOC_SOURCES = (
    f"{_PACKAGE}/audit.py",  # ledger audit, run by validate
    f"{_PACKAGE}/publication.py",  # agentic-redact and artifact validation
    f"{_PACKAGE}/validate.py",  # agentic-validate on a run directory
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{16}$")
_GIT_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
DRIVER_KEYS = ("driver_digest", "driver_files", "git_head", "git_driver_clean", "changed_during_run")


def driver_digest(files: tuple[str, ...] = DRIVER_SOURCES, root: Path = _ROOT) -> str:
    """SHA-256 prefix over the sorted driver files' names and bytes, like the fingerprint."""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def driver_provenance(root: Path = _ROOT) -> dict[str, Any]:
    """The driver identity ``run.json`` records when a run starts."""
    head = _git_head(root)
    dirty = dirty_files(DRIVER_SOURCES, root) if head is not None else None
    return {
        "driver_digest": driver_digest(root=root),
        "driver_files": list(DRIVER_SOURCES),
        "git_head": head,
        "git_driver_clean": None if dirty is None else not dirty,
        "changed_during_run": False,
    }


def dirty_played_files(root: Path = _ROOT) -> list[str] | None:
    """Driver and contract files that differ from HEAD (or are untracked); ``None`` if not a git checkout."""
    if _git_head(root) is None:
        return None
    return dirty_files(CONTRACT_SOURCES + DRIVER_SOURCES, root)


def dirty_files(files: tuple[str, ...], root: Path = _ROOT) -> list[str] | None:
    """Which of ``files`` are modified, staged, or untracked relative to HEAD; ``None`` if git cannot say."""
    output = _git(root, "status", "--porcelain", "--untracked-files=all", "-z", "--", *files)
    if output is None:
        return None
    # ``XY path\0``; a rename adds its old path as a second entry.
    return sorted({entry[3:] for entry in output.split("\0") if len(entry) > 3})


def provenance_problems(driver: Any) -> list[str]:
    """Shape errors in a recorded driver block."""
    if not isinstance(driver, dict):
        return ["driver must be an object"]
    problems = []
    missing = [key for key in DRIVER_KEYS if key not in driver]
    if missing:
        problems.append(f"driver is missing {missing}")
    if not _DIGEST_RE.match(str(driver.get("driver_digest") or "")):
        problems.append("driver.driver_digest must be 16 lowercase hex characters")
    files = driver.get("driver_files")
    if not (isinstance(files, list) and files and all(isinstance(name, str) for name in files)):
        problems.append("driver.driver_files must be a non-empty list of file names")
    head = driver.get("git_head")
    if head is not None and not _GIT_HEAD_RE.match(str(head)):
        problems.append("driver.git_head must be a 40-character commit id or null")
    if driver.get("git_driver_clean") not in (True, False, None):
        problems.append("driver.git_driver_clean must be true, false or null")
    if not isinstance(driver.get("changed_during_run"), bool):
        problems.append("driver.changed_during_run must be true or false")
    return problems


def reproducible_driver(driver: Any) -> bool:
    """A well-formed record of a driver that matched a commit for the whole run."""
    return (
        not provenance_problems(driver)
        and _GIT_HEAD_RE.match(str(driver["git_head"])) is not None
        and driver["git_driver_clean"] is True
        and driver["changed_during_run"] is False
    )


def _git_head(root: Path) -> str | None:
    # ``root`` must be the top of the work tree: an install inside some other
    # repository (a virtualenv in a checkout) would otherwise report that repository.
    top = _git(root, "rev-parse", "--show-toplevel")
    if top is None or Path(top.strip()).resolve() != root.resolve():
        return None
    head = (_git(root, "rev-parse", "HEAD") or "").strip()
    return head if _GIT_HEAD_RE.match(head) else None


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed git command
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return None
    return result.stdout
