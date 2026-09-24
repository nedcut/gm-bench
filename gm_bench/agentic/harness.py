"""The harness-specific half of a GM-Bench 2.0 driver.

The episode loop (engine, socket server, sandbox check, nudges, provider-stall
retries, the phase-guard watch, finalization, the run summary) is shared and
lives in ``opencode.py``, where the first driver grew it. Everything that
differs between harnesses is a :class:`HarnessDriver`: how to find its
version, how to stage its configuration beside the proxy, the command lines
for the first run and for a resume, how to read its event stream, and what
counts as a provider stall in that stream. ``opencode.OpenCodeDriver``,
``codex.CodexDriver`` and ``claude.ClaudeDriver`` are the implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gm_bench.agentic.opencode import HarnessLaunch


class HarnessDriver:
    """What a harness must supply to the shared episode loop."""

    #: Row identity: ``<name>:<model>`` and ``harness.name`` in ``run.json``.
    name = ""
    #: The executable looked up on the harness PATH in same-user isolation.
    default_binary = ""
    #: The executable inside the harness container image.
    container_executable = ""
    #: The key of the harness version in the image description from ``container.ensure_image``.
    image_version_key = ""

    @property
    def events_filename(self) -> str:
        return f"{self.name}-events.jsonl"

    @property
    def stderr_filename(self) -> str:
        return f"{self.name}-stderr.log"

    def preflight(self, isolation: str) -> None:
        """Refuse a run this harness cannot start (for example, no credentials). Raises ``ValueError``."""

    def version(self, binary: str) -> str | None:
        raise NotImplementedError

    def ensure_image(self, *, docker: str, env: dict[str, str]) -> dict[str, Any]:
        raise NotImplementedError

    def environment(self, env: dict[str, str], scratch: Path, isolation: str) -> dict[str, str]:
        """Adjust the harness environment before the sandbox check runs under it."""
        return env

    def stage(self, launch: HarnessLaunch) -> None:
        """Write the proxy and this harness's configuration, after the sandbox check passed."""
        raise NotImplementedError

    def run_args(self, *, model: str, variant: str | None, workdir: str, brief: str, isolation: str) -> list[str]:
        """Arguments after the executable for the first invocation; the brief must be the last one."""
        raise NotImplementedError

    def resume_args(
        self, *, model: str, variant: str | None, workdir: str, session_id: str, text: str, isolation: str
    ) -> list[str]:
        """Arguments after the executable to resume ``session_id`` with ``text`` (a nudge or a stall retry)."""
        raise NotImplementedError

    def parse_events(self, lines: list[str]) -> dict[str, Any]:
        """Fold the event stream into the telemetry shape ``parse_opencode_events`` returns."""
        raise NotImplementedError

    def ended_in_provider_stall(self, lines: list[str]) -> bool:
        """Whether one invocation's events end in a retryable provider error."""
        raise NotImplementedError

    def quota_exhausted(self, lines: list[str], *, isolation: str, now: float) -> dict[str, Any] | None:
        """Whether one invocation ended because the subscription's usage window is spent.

        ``{"message_class": ..., "reset_at_utc": ISO string or None}``, or
        ``None`` for any other ending. A quota exhaustion is never a provider
        stall: the shared loop pauses until the reset when the wait fits the
        budget, and otherwise stops the episode and the panel.
        """
        return None

    #: Whether the shared loop should poll :meth:`invocation_parked` while an invocation runs.
    polls_for_park = False

    def invocation_parked(self, lines: list[str]) -> bool:
        """Whether a still-running invocation is parked waiting out a spent usage window.

        Polled with the phase guard (only when :attr:`polls_for_park`) on the
        events the running invocation has written so far. A harness that waits
        inside the process for a subscription window to reset instead of
        exiting (Claude Code) would otherwise hold the episode until the phase
        guard stopped it. When this returns true the loop stops the process and
        asks :meth:`quota_exhausted` about the same events, so the stop is a
        quota pause or stop, never a guard kill or a nudge.
        """
        return False

    def usage_block(self, telemetry: dict[str, Any], *, model: str, decisions: int) -> dict[str, Any]:
        raise NotImplementedError

    def collect(self, launch: HarnessLaunch) -> None:
        """Read what the harness left in its home before :meth:`cleanup` and the container close remove it.

        Runs once per episode, after the last invocation, while the server is
        stopping. Must not raise; whatever it keeps is reported by :meth:`run_record`.
        """

    def run_record(self, launch: HarnessLaunch) -> dict[str, Any]:
        """Extra ``harness_run`` fields describing how this harness was configured."""
        return {}

    def cleanup(self, launch: HarnessLaunch) -> None:
        """Remove anything the stage left that must not outlive the episode, even with ``keep_scratch``.

        Runs after the harness has exited, and also when ``HarnessLaunch``
        fails to start (``environment`` ran, ``stage`` may not have).
        ``launch.evidence_paths`` are the run-directory files the harness
        wrote (event stream, stderr), for a driver that must redact them.
        """
