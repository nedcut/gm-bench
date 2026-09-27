"""Prove what a harness sends the model before a panel spends anything (``gm-bench agentic``).

A harness assembles its prompt from more than the task brief: its own system
prompt and tools, and whatever it finds in the operator's configuration
(instruction files, skills, plugins) or fetches from the operator's account.
The benchmark wants only the first. The drivers keep the operator's
configuration out by giving the harness private directories, but a harness
can read from places a driver did not think of (on 2026-09-27 same-user
OpenCode was found sending the operator's global ``AGENTS.md`` and skills),
so the prompt itself is checked.

:func:`run_prompt_check` launches the harness once, set up exactly as an
episode's first invocation (same driver, environment, staging and command
line, the real brief), with one change the driver supplies
(:meth:`HarnessDriver.capture_overrides`): the model endpoint is a
:class:`CaptureServer` on the loopback. The server records every model
request and answers with a one-word reply, so no provider is contacted and
nothing is spent. Every other HTTP(S) connection goes through the server as
a proxy and is refused, and its host is recorded. The captured requests are
then searched (:func:`operator_content`) for the operator's home directory
path, for any distinctive line of the operator's instruction files, and for
the descriptions of the operator's skills (:func:`operator_markers`). A
check that captured no model request fails too: it proved nothing.

What it cannot see: anything a provider adds on its own servers, and
anything an account endpoint would return, because those endpoints are
refused or answered by the capture server. Container runs are not checked:
only the scratch directory and a fresh home volume reach the harness, and
the egress firewall does not let it reach a loopback capture server. Cursor
builds its prompt on Cursor's servers, so ``cursor.py`` audits the prompt
Cursor recorded instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gm_bench.agentic.harness import HarnessDriver

# Request paths that carry a prompt: Anthropic Messages, OpenAI Responses, Chat Completions.
MODEL_PATHS = ("/messages", "/responses", "/chat/completions")
CHECK_SECONDS = 180.0
# A public seed: the check's brief must not be built from a private panel seed.
CHECK_SEED = 1
REPLY = "ok"

# Where the operator's own instructions live, relative to their home directory.
INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".agents/AGENTS.md",
    ".codex/AGENTS.md",
    ".codex/AGENTS.override.md",
    ".claude/CLAUDE.md",
    ".config/opencode/AGENTS.md",
    ".cursor/AGENTS.md",
)
# Where the operator's own skills live. Directories starting with a dot are
# skipped: Codex keeps its bundled skills in ``skills/.system``, which every
# Codex run lists anyway.
SKILL_ROOTS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".config/opencode/skill",
    ".config/opencode/skills",
    ".cursor/skills",
)
# Shorter lines and descriptions are too generic to attribute to the operator.
MIN_LINE = 40
MIN_DESCRIPTION = 30
MAX_SKILL_FILES = 2000


class PromptCheckError(ValueError):
    """The harness's prompt carried the operator's content, or the check proved nothing."""


# -- what counts as the operator's content --------------------------------------


@dataclass
class OperatorMarkers:
    """Text that can only have come from the operator's own configuration."""

    home: str
    # Distinctive instruction lines, and the file each came from (relative to home).
    lines: dict[str, str] = field(default_factory=dict)
    # Skill descriptions, and the skill each belongs to.
    skills: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, int]:
        return {"instruction_lines": len(self.lines), "skills": len(set(self.skills.values()))}


def _description(skill_md: Path) -> tuple[str, str] | None:
    """``(name, description)`` from a SKILL.md front matter, or ``None``."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    front = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    fields = dict(
        (key.strip(), value.strip().strip("\"'"))
        for key, _, value in (line.partition(":") for line in front.splitlines())
        if value
    )
    description = fields.get("description", "")
    return (fields.get("name") or skill_md.parent.name, description) if len(description) >= MIN_DESCRIPTION else None


def operator_markers(home: Path | None = None) -> OperatorMarkers:
    """Collect the operator's home path, instruction lines and skill descriptions from ``home``."""
    home = Path.home() if home is None else home
    markers = OperatorMarkers(home=str(home))
    for relative in INSTRUCTION_FILES:
        path = home / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= MIN_LINE:
                markers.lines.setdefault(line, relative)
    seen = 0
    for root in SKILL_ROOTS:
        base = home / root
        if not base.is_dir():
            continue
        for skill_md in sorted(base.rglob("SKILL.md")):
            if any(part.startswith(".") for part in skill_md.relative_to(base).parts):
                continue
            seen += 1
            if seen > MAX_SKILL_FILES:
                break
            found = _description(skill_md)
            if found is not None:
                markers.skills.setdefault(found[1], found[0])
    return markers


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def operator_content(texts: list[str], markers: OperatorMarkers) -> list[str]:
    """What in ``texts`` came from the operator: their home path, instruction lines, skills. Empty when clean."""
    joined = "\n".join(texts)
    findings = []
    hits = joined.count(markers.home + os.sep)
    if hits:
        findings.append(f"the operator's home directory {markers.home} appears {hits} time(s)")
    by_file: dict[str, int] = {}
    for line, source in markers.lines.items():
        if line in joined:
            by_file[source] = by_file.get(source, 0) + 1
    findings += [f"{count} line(s) of ~/{source}" for source, count in sorted(by_file.items())]
    skills = sorted({name for description, name in markers.skills.items() if description in joined})
    if skills:
        findings.append(f"the operator's skills {', '.join(skills)}")
    return findings


# -- the capture server ------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server: CaptureServer

    def log_message(self, *args: Any) -> None:
        pass

    def do_CONNECT(self) -> None:
        # A proxied connection to anywhere else: refused, host recorded.
        self.server.record({"kind": "refused", "host": self.path.rsplit(":", 1)[0]})
        self.send_response(403)
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        self.server.record({"kind": "other", "method": "GET", "path": path})
        if path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [], "models": []})
        self._json(404, {"error": {"message": "gm-bench prompt check: not found"}})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._body()
        model_request = path.endswith(MODEL_PATHS)
        encoding = (self.headers.get("content-encoding") or "identity").lower()
        if model_request and encoding != "identity":
            self.server.record({"kind": "model", "path": path, "unreadable": f"content-encoding {encoding}"})
            return self._json(400, {"error": {"message": "gm-bench prompt check: compressed request"}})
        try:
            parsed = json.loads(body) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {"raw": body.decode("utf-8", errors="replace")}
        if not model_request:
            self.server.record({"kind": "other", "method": "POST", "path": path})
            return self._json(404, {"error": {"message": "gm-bench prompt check: not found"}})
        self.server.record({"kind": "model", "path": path, "strings": _strings(parsed)})
        if path.endswith("/messages"):
            return self._anthropic(parsed)
        if path.endswith("/responses"):
            return self._responses(parsed)
        return self._chat(parsed)

    def _body(self) -> bytes:
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            body = b""
            while (size := int(self.rfile.readline().strip() or b"0", 16)) > 0:
                body += self.rfile.read(size)
                self.rfile.readline()
            self.rfile.readline()
            return body
        return self.rfile.read(int(self.headers.get("content-length") or 0))

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, events: list[tuple[str | None, Any]]) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        for name, data in events:
            text = data if isinstance(data, str) else json.dumps(data)
            self.wfile.write(((f"event: {name}\n" if name else "") + f"data: {text}\n\n").encode())
            self.wfile.flush()
        self.close_connection = True

    def _anthropic(self, request: dict[str, Any]) -> None:
        model = request.get("model", "capture")
        usage = {"input_tokens": 1, "output_tokens": 1}
        message = {"id": "msg_check", "type": "message", "role": "assistant", "model": model, "stop_sequence": None}
        if not request.get("stream"):
            content = [{"type": "text", "text": REPLY}]
            return self._json(200, {**message, "content": content, "stop_reason": "end_turn", "usage": usage})
        block = {"type": "text", "text": ""}
        self._sse(
            [
                ("message_start", {"type": "message_start", "message": {**message, "content": [], "usage": usage}}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": block}),
                (
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": REPLY}},
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                (
                    "message_delta",
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
        )

    def _responses(self, request: dict[str, Any]) -> None:
        item = {
            "id": "msg_check",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": REPLY, "annotations": []}],
        }
        response = {
            "id": "resp_check",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": request.get("model", "capture"),
            "output": [item],
            "usage": {
                "input_tokens": 1,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 1,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 2,
            },
        }
        if not request.get("stream"):
            return self._json(200, response)
        started = {**response, "status": "in_progress", "output": []}
        self._sse(
            [
                ("response.created", {"type": "response.created", "response": started}),
                (
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {**item, "status": "in_progress", "content": []},
                    },
                ),
                (
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": "msg_check",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": REPLY,
                    },
                ),
                ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
                ("response.completed", {"type": "response.completed", "response": response}),
            ]
        )

    def _chat(self, request: dict[str, Any]) -> None:
        model = request.get("model", "capture")
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if not request.get("stream"):
            choice = {"index": 0, "message": {"role": "assistant", "content": REPLY}, "finish_reason": "stop"}
            return self._json(
                200, {"id": "c", "object": "chat.completion", "model": model, "choices": [choice], "usage": usage}
            )
        base = {"id": "c", "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
        delta = {"index": 0, "delta": {"role": "assistant", "content": REPLY}, "finish_reason": None}
        self._sse(
            [
                (None, {**base, "choices": [delta]}),
                (None, {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}),
                (None, "[DONE]"),
            ]
        )


class CaptureServer(ThreadingHTTPServer):
    """A loopback model endpoint and refusing proxy that records what the harness sent."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.records.append(entry)

    def __enter__(self) -> CaptureServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown()
        self.server_close()


def proxy_environment(url: str) -> dict[str, str]:
    """Send every other HTTP(S) connection to the capture server, which refuses it."""
    local = "127.0.0.1,localhost"
    return {
        **{key: url for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")},
        "NO_PROXY": local,
        "no_proxy": local,
    }


# -- the check ------------------------------------------------------------------------


def run_prompt_check(
    driver: HarnessDriver,
    *,
    binary: str,
    model: str,
    variant: str | None = None,
    markers: OperatorMarkers | None = None,
    timeout: float = CHECK_SECONDS,
) -> dict[str, Any]:
    """Capture the harness's first requests against a loopback server and search them for operator content.

    Returns the record ``run.json`` keeps as ``prompt_check``: what was
    captured, what was refused, and ``operator_content`` (empty when clean)
    plus ``problems``. Never raises for a dirty prompt; the caller decides.
    """
    from gm_bench.agentic.brief import task_brief
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import HarnessLaunch
    from gm_bench.simulator import League

    markers = operator_markers() if markers is None else markers
    work = Path(tempfile.mkdtemp(prefix="gmb-prompt-check-"))
    events, errors = work / "events.jsonl", work / "stderr.log"
    episode = AgenticEpisode(CHECK_SEED, 1, 0, ledger_path=work / "ledger.jsonl")
    exit_code: int | None = None
    timed_out = False
    try:
        with CaptureServer() as server:
            launch = HarnessLaunch(episode, binary=binary, driver=driver, evidence_paths=(events, errors))
            try:
                launch.prepare()
                brief = task_brief(1, League.new(seed=CHECK_SEED, user_team_id=0).user_team.name, 0)
                args = driver.run_args(
                    model=model, variant=variant, workdir=launch.workdir, brief=brief, isolation="same-user"
                )
                args, overrides = driver.capture_overrides(args, model=model, base_url=server.url)
                command, _on_kill = launch.command(args)
                env = {**launch.env, **proxy_environment(server.url), **overrides}
                with events.open("w") as out, errors.open("w") as err:
                    try:
                        exit_code = subprocess.run(
                            command,
                            cwd=launch.scratch,
                            env=env,
                            stdin=subprocess.DEVNULL,
                            stdout=out,
                            stderr=err,
                            timeout=timeout,
                            check=False,
                        ).returncode
                    except subprocess.TimeoutExpired:
                        timed_out = True
            finally:
                launch.close()
            records = list(server.records)
    finally:
        episode.close()
        shutil.rmtree(work, ignore_errors=True)

    model_requests = [record for record in records if record["kind"] == "model"]
    readable = [record for record in model_requests if "strings" in record]
    findings = operator_content([text for record in readable for text in record["strings"]], markers)
    problems = list(findings)
    if not readable:
        problems.append(
            f"the harness sent no readable model request to the capture server "
            f"(exit {exit_code}{', timed out' if timed_out else ''}), so nothing shows what it would send"
        )
    problems += [
        f"unreadable model request: {record['unreadable']}" for record in model_requests if "unreadable" in record
    ]
    return {
        "checked": True,
        "method": "loopback capture server; no provider contacted",
        "model_requests": len(model_requests),
        "request_characters": sum(len(text) for record in readable for text in record["strings"]),
        "other_requests": sorted({f"{r['method']} {r['path']}" for r in records if r["kind"] == "other"}),
        "refused_hosts": sorted({r["host"] for r in records if r["kind"] == "refused"}),
        "operator_markers": markers.summary(),
        "operator_content": findings,
        "problems": problems,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }


def not_checked(reason: str) -> dict[str, Any]:
    return {"checked": False, "reason": reason, "problems": []}


def prompt_check_problems(run: dict[str, Any]) -> list[str]:
    """The problems a run's or a row's recorded ``prompt_check`` found (the panel should never have started).

    A run without a check (recorded before it existed, or with
    ``--skip-prompt-check``) and a container run recorded as not checked have
    none: adding a finding there would change every older row's redaction.
    """
    check = run.get("prompt_check")
    problems = check.get("problems") if isinstance(check, dict) else None
    return [f"prompt check: {problem}" for problem in problems or []]
