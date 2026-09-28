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
a proxy and is refused, and its host is recorded, except a public model
catalog the harness downloads to resolve the model name
(:data:`CATALOG_HOSTS`), which is passed through. The captured requests are
then compared with a second capture of the same launch in which the
operator's home is replaced by an empty synthetic one
(:func:`empty_home_environment`): any prompt line that appears only when the
real home is visible came from the operator, wherever it was read from
(:func:`home_only_lines`). As a second signal, the requests are searched
(:func:`operator_content`) for the operator's home directory path, for any
distinctive line of the operator's instruction files, memories and rules,
and for the descriptions of the operator's skills, including installed
plugins' (:func:`operator_markers`). A check that captured no model request
fails too: it proved nothing.

Only the first invocation is captured, unless it ended in a provider stall
the episode would retry (:meth:`HarnessDriver.ended_in_provider_stall`)
before sending any model request: then the session is resumed with a nudge,
as the episode does, up to ``MAX_STARTUP_SERVER_ERROR_RETRIES`` times.
OpenCode needs this for a model missing from the catalog snapshot it ships
with: its first launch in a fresh home resolves the model before the catalog
download finishes and fails, and the resumed launch finds the downloaded
catalog. Later nudges and provider-stall retries
resume the same session in the same launch: the same private home, config
directory and environment the check proved, with the driver's own nudge text
in place of the brief. So they read no configuration the first invocation
did not; what they can add is what the agent itself wrote during the
episode, and the Claude and Cursor drivers remove config the agent writes
into their homes before every invocation.

What it cannot see: anything a provider adds on its own servers, and
anything an account endpoint would return, because those endpoints are
refused or answered by the capture server. The empty-home run hides the home
the environment names (``HOME`` and every variable holding a path inside it,
except ``*PATH`` search paths, which must still find the harness); a harness
that looks its home up another way (the user database) sees the real one in
both runs, and only the marker search can catch what it reads there. Container runs are not checked:
only the scratch directory and a fresh home volume reach the harness, and
the egress firewall does not let it reach a loopback capture server. Cursor
builds its prompt on Cursor's servers, so ``cursor.py`` audits the prompt
Cursor recorded instead.
"""

from __future__ import annotations

import glob
import json
import os
import re
import select
import shutil
import socket
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
# Public model catalogs a harness downloads at start-up to resolve a model name,
# passed through (a TLS tunnel to port 443) instead of refused. OpenCode GETs
# ``models.opencode.ai/api.json`` (no body; a user agent and trace ids) into its
# cache, which an episode's private home starts without.
CATALOG_HOSTS = ("models.opencode.ai",)
CATALOG_SECONDS = 30.0

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
# More of the operator's instructions: Claude Code's rules, its per-project memories.
INSTRUCTION_GLOBS = (
    ".claude/rules/**/*.md",
    ".claude/projects/*/memory/*.md",
    ".cursor/rules/**/*.md*",
)
# OpenCode configs whose ``instructions`` list names more instruction files.
OPENCODE_CONFIGS = (".config/opencode/opencode.json", ".config/opencode/opencode.jsonc")
# Where the operator's own skills live. Directories starting with a dot are
# skipped: Codex keeps its bundled skills in ``skills/.system``, which every
# Codex run lists anyway. ``.claude/plugins/cache`` holds the installed Claude
# Code plugins (``marketplaces`` holds catalogues of plugins not installed).
SKILL_ROOTS = (
    ".agents/skills",
    ".claude/skills",
    ".claude/plugins/cache",
    ".codex/skills",
    ".config/opencode/skill",
    ".config/opencode/skills",
    ".cursor/skills",
)
MAX_INSTRUCTION_FILES = 500
# ``@path`` on its own line imports a file into a CLAUDE.md or AGENTS.md.
_IMPORT_RE = re.compile(r"^@(\S+)\s*$", re.MULTILINE)
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


def _instruction_paths(home: Path) -> list[Path]:
    """The operator's instruction files: the fixed list, rules and memories, and OpenCode's ``instructions``."""
    paths = [home / relative for relative in INSTRUCTION_FILES]
    for pattern in INSTRUCTION_GLOBS:
        paths += sorted(home.glob(pattern))
    for relative in OPENCODE_CONFIGS:
        try:
            text = (home / relative).read_text(encoding="utf-8")
            # JSONC: drop whole-line comments; a config this cannot read is skipped.
            config = json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))
        except (OSError, ValueError):
            continue
        for entry in config.get("instructions") or [] if isinstance(config, dict) else []:
            if isinstance(entry, str) and not entry.startswith(("http://", "https://")):
                pattern = _in_home(entry, home)
                pattern = pattern if pattern.is_absolute() else (home / relative).parent / pattern
                paths += [Path(found) for found in sorted(glob.glob(str(pattern), recursive=True))]
    return paths


def _in_home(path: str, home: Path) -> Path:
    """``path`` with a leading ``~`` meaning ``home``."""
    return home / path[2:] if path.startswith("~/") else Path(path)


def _label(path: Path, home: Path) -> str:
    try:
        return str(path.relative_to(home))
    except ValueError:
        return str(path)


def operator_markers(home: Path | None = None) -> OperatorMarkers:
    """Collect the operator's home path, instruction lines and skill descriptions from ``home``.

    Instruction files are read with the files they import (``@path`` lines,
    one level deep), so text a CLAUDE.md pulls in from elsewhere counts too.
    """
    home = Path.home() if home is None else home
    markers = OperatorMarkers(home=str(home))
    queue, read = _instruction_paths(home), set()
    while queue and len(read) < MAX_INSTRUCTION_FILES:
        path = queue.pop(0)
        try:
            resolved = path.resolve()
            if resolved in read or not path.is_file():
                continue
            read.add(resolved)
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for target in _IMPORT_RE.findall(text):
            imported = _in_home(target, home)
            queue.append(imported if imported.is_absolute() else path.parent / imported)
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= MIN_LINE:
                markers.lines.setdefault(line, _label(path, home))
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
        host, _, port = self.path.rpartition(":")
        if host in CATALOG_HOSTS and port == "443":
            return self._tunnel(host)
        # A proxied connection to anywhere else: refused, host recorded.
        self.server.record({"kind": "refused", "host": host})
        self.send_response(403)
        self.end_headers()

    def _tunnel(self, host: str) -> None:
        """Pass a proxied connection to a catalog host through until either side closes."""
        try:
            upstream = socket.create_connection((host, 443), timeout=CATALOG_SECONDS)
        except OSError as error:
            self.server.record({"kind": "forwarded", "host": host, "failed": str(error)})
            self.send_response(502)
            self.end_headers()
            return
        self.server.record({"kind": "forwarded", "host": host})
        self.send_response(200)
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        with upstream:
            ends = {self.connection: upstream, upstream: self.connection}
            while True:
                ready, _, _ = select.select(list(ends), [], [], CATALOG_SECONDS)
                try:
                    data = ready[0].recv(65536) if ready else b""
                    if not data:
                        return
                    ends[ready[0]].sendall(data)
                except OSError:
                    return

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


# -- the empty-home comparison ----------------------------------------------------------

# What differs between two launches of the same harness and is nobody's content: temporary
# paths (scratch, private homes, sockets), the capture server's port, ids, dates and times.
_VOLATILE = (
    (
        re.compile(r"(?:/private)?(?:/var/folders|/tmp|" + re.escape(tempfile.gettempdir()) + r")/[^\s\"'`<>),;]*"),
        "<tmp>",
    ),
    (re.compile(r"(?:127\.0\.0\.1|localhost):\d+"), "<loopback>"),
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<uuid>"),
    (re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,}\b"), "<id>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"), "<date>"),
    (
        re.compile(
            r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b|"
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}"
        ),
        "<date>",
    ),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<time>"),
    (re.compile(r"\b\d{9,}\b"), "<number>"),
)


def normalized_lines(texts: list[str]) -> set[str]:
    """Every non-blank line of ``texts`` with the volatile parts of a launch replaced by placeholders."""
    lines = set()
    for text in texts:
        for line in text.splitlines():
            for pattern, placeholder in _VOLATILE:
                line = pattern.sub(placeholder, line)
            if line := line.strip():
                lines.add(line)
    return lines


def home_only_lines(real: list[str], empty: list[str]) -> list[str]:
    """Lines the real-home capture sent that the empty-home capture did not: the operator's content."""
    return sorted(normalized_lines(real) - normalized_lines(empty))


def empty_home_environment(home: Path, empty: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """The operator's environment with their home swapped for ``empty``.

    ``HOME`` and every variable that names a path inside the home point into
    ``empty`` instead; ``*PATH`` search paths are kept, so the harness and its
    interpreter are still found.
    """
    inside = re.compile(re.escape(str(home)) + r"(?=/|:|$)")
    env = dict(os.environ if base is None else base)
    for key, value in env.items():
        if not key.endswith("PATH"):
            env[key] = inside.sub(str(empty), value)
    env["HOME"] = str(empty)
    return env


# -- the check ------------------------------------------------------------------------


@dataclass
class _Capture:
    records: list[dict[str, Any]]
    exit_code: int | None
    timed_out: bool
    stall_retries: int = 0

    @property
    def model_requests(self) -> list[dict[str, Any]]:
        return [record for record in self.records if record["kind"] == "model"]

    @property
    def texts(self) -> list[str]:
        return [text for record in self.model_requests for text in record.get("strings", [])]

    @property
    def readable(self) -> bool:
        return any("strings" in record for record in self.model_requests)


def _capture(
    driver: HarnessDriver,
    *,
    binary: str,
    model: str,
    variant: str | None,
    timeout: float,
    base_environment: dict[str, str] | None = None,
) -> _Capture:
    """Launch the harness once, as an episode's first invocation, against a fresh capture server."""
    from gm_bench.agentic.brief import nudge_message, task_brief
    from gm_bench.agentic.episode import AgenticEpisode
    from gm_bench.agentic.opencode import DEFAULT_MAX_NUDGES, MAX_STARTUP_SERVER_ERROR_RETRIES, HarnessLaunch
    from gm_bench.simulator import League

    work = Path(tempfile.mkdtemp(prefix="gmb-prompt-check-"))
    events, errors = work / "events.jsonl", work / "stderr.log"
    episode = AgenticEpisode(CHECK_SEED, 1, 0, ledger_path=work / "ledger.jsonl")
    exit_code: int | None = None
    timed_out = False
    stall_retries = 0
    try:
        with CaptureServer() as server:
            launch = HarnessLaunch(
                episode,
                binary=binary,
                driver=driver,
                evidence_paths=(events, errors),
                base_environment=base_environment,
            )
            try:
                launch.prepare()
                brief = task_brief(1, League.new(seed=CHECK_SEED, user_team_id=0).user_team.name, 0)
                args = driver.run_args(
                    model=model, variant=variant, workdir=launch.workdir, brief=brief, isolation="same-user"
                )
                while True:
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
                    # A launch that stalled before any model request is resumed, as the episode would.
                    lines = events.read_text(encoding="utf-8").splitlines()
                    if (
                        timed_out
                        or any(record["kind"] == "model" for record in server.records)
                        or stall_retries >= MAX_STARTUP_SERVER_ERROR_RETRIES
                        or not driver.ended_in_provider_stall(lines)
                    ):
                        break
                    session_id = driver.parse_events(lines)["session_id"]
                    if not session_id:
                        break
                    stall_retries += 1
                    text = nudge_message(episode.season, episode.phase, 1, 1, DEFAULT_MAX_NUDGES)
                    args = driver.resume_args(
                        model=model,
                        variant=variant,
                        workdir=launch.workdir,
                        session_id=session_id,
                        text=text,
                        isolation="same-user",
                    )
            finally:
                launch.close()
            records = list(server.records)
    finally:
        episode.close()
        shutil.rmtree(work, ignore_errors=True)
    return _Capture(records, exit_code, timed_out, stall_retries)


def _excerpt(line: str, width: int = 60) -> str:
    return json.dumps(line if len(line) <= width else line[: width - 3] + "...")


def run_prompt_check(
    driver: HarnessDriver,
    *,
    binary: str,
    model: str,
    variant: str | None = None,
    markers: OperatorMarkers | None = None,
    timeout: float = CHECK_SECONDS,
    home: Path | None = None,
) -> dict[str, Any]:
    """Capture the harness's first requests against a loopback server, twice, and find the operator's content.

    The first capture runs in the operator's environment, the second with
    their home (``home``, default the current user's) swapped for an empty
    synthetic one. Lines only the first sent are the operator's; the marker
    search (:func:`operator_content`) runs over the first as well. Returns
    the record ``run.json`` keeps as ``prompt_check``: what was captured,
    what was refused, and ``operator_content`` (empty when clean) plus
    ``problems``, which name counts and, since a check with problems stops
    the panel before anything is recorded, a short excerpt for the operator.
    Never raises for a dirty prompt; the caller decides.
    """
    markers = operator_markers() if markers is None else markers
    home = Path.home() if home is None else home
    options = {"binary": binary, "model": model, "variant": variant, "timeout": timeout}
    real = _capture(driver, **options)
    empty_dir = Path(tempfile.mkdtemp(prefix="gmb-empty-home-"))
    try:
        empty = _capture(driver, **options, base_environment=empty_home_environment(home, empty_dir))
    finally:
        shutil.rmtree(empty_dir, ignore_errors=True)

    findings = operator_content(real.texts, markers)
    problems = list(findings)
    if not real.readable:
        problems.append(
            f"the harness sent no readable model request to the capture server "
            f"(exit {real.exit_code}{', timed out' if real.timed_out else ''}), so nothing shows what it would send"
        )
    problems += [
        f"unreadable model request: {record['unreadable']}" for record in real.model_requests if "unreadable" in record
    ]
    extra: list[str] = []
    if real.readable and not empty.readable:
        problems.append(
            f"with an empty home the harness sent no readable model request "
            f"(exit {empty.exit_code}{', timed out' if empty.timed_out else ''}), so nothing shows which of its "
            "prompt came from the operator's home"
        )
    elif real.readable:
        extra = home_only_lines(real.texts, empty.texts)
        if extra:
            problems.append(
                f"{len(extra)} prompt line(s) ({sum(len(line) for line in extra)} characters) appear only when the "
                f"harness can see the operator's home, e.g. {', '.join(_excerpt(line) for line in extra[:3])}"
            )
    return {
        "checked": True,
        "method": "loopback capture server, then again with an empty home; no provider contacted",
        "model_requests": len(real.model_requests),
        "request_characters": sum(len(text) for text in real.texts),
        "other_requests": sorted({f"{r['method']} {r['path']}" for r in real.records if r["kind"] == "other"}),
        "refused_hosts": sorted({r["host"] for r in real.records if r["kind"] == "refused"}),
        "forwarded_hosts": sorted({r["host"] for r in real.records if r["kind"] == "forwarded"}),
        "stall_retries": real.stall_retries,
        "empty_home": {
            "model_requests": len(empty.model_requests),
            "stall_retries": empty.stall_retries,
            "lines_only_with_operator_home": len(extra),
            "characters_only_with_operator_home": sum(len(line) for line in extra),
        },
        "operator_markers": markers.summary(),
        "operator_content": findings,
        "problems": problems,
        "exit_code": real.exit_code,
        "timed_out": real.timed_out,
    }


CONTAINER_NOT_CHECKED = "container isolation: only the scratch directory and a fresh home volume reach the harness"


def not_checked(reason: str) -> dict[str, Any]:
    return {"checked": False, "reason": reason, "problems": []}


def unchecked_same_user(run: dict[str, Any]) -> str | None:
    """Why a same-user run or row cannot be published without a prompt check; ``None`` when it can.

    Only runs recorded by a driver that has the check count (``run.json``
    carries the ``prompt_check`` key, or the driver's files include this
    module): a same-user run whose check was skipped or not run proves
    nothing about what its harness sent. Runs recorded before the check
    existed and container runs, whose harness sees only the scratch and a
    fresh home volume, are unaffected (so is a row stated at another
    isolation, which a driver never records).
    """
    if run.get("isolation", "same-user") != "same-user":
        return None
    driver_files = (run.get("driver") or {}).get("driver_files") or []
    if "prompt_check" not in run and not any(str(name).endswith("/prompt_check.py") for name in driver_files):
        return None
    check = run.get("prompt_check")
    if isinstance(check, dict) and (check.get("checked") is True or check.get("reason") == CONTAINER_NOT_CHECKED):
        return None
    how = "was skipped (--skip-prompt-check)" if check is None else "did not run"
    return f"prompt check {how}: a same-user row must show what its harness would send the model"


def prompt_check_problems(run: dict[str, Any]) -> list[str]:
    """The problems a run's or a row's recorded ``prompt_check`` found (the panel should never have started).

    A run without a check (recorded before it existed, or with
    ``--skip-prompt-check``) and a container run recorded as not checked have
    none: adding a finding there would change every older row's redaction.
    A same-user run whose check was skipped is refused at publication by
    :func:`unchecked_same_user` instead.
    """
    check = run.get("prompt_check")
    problems = check.get("problems") if isinstance(check, dict) else None
    return [f"prompt check: {problem}" for problem in problems or []]
