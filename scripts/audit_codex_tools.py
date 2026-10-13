#!/usr/bin/env python3
"""Audit every tool a Codex panel's agent could call, against the real ChatGPT account.

The prompt check (``gm_bench/agentic/prompt_check.py``) answers Codex's
account endpoints itself, so it cannot see what a ChatGPT login adds. And in
code mode Codex leaves MCP tools out of the prompt text: they are callable
from the ``exec`` tool and listed only in its ``ALL_TOOLS``. On 2026-10-12
that hid 668 tools for the operator's connected ChatGPT apps (Gmail, GitHub,
Google Drive, Neon and others) from every check. This script looks at the
whole tool set instead. It runs before a Codex panel, with the
``--codex-auth-file`` the panel will use. It spends no quota.

It launches one throwaway episode on a public seed in the Codex container
image, set up by the driver exactly as an episode's first invocation: the
same staged config and gm-bench proxy, served by a real engine, the same
home volume with the login, and the same command line. Two things differ.

- The model endpoint (``openai_base_url``, which carries a ChatGPT login's
  ``/backend-api/codex/responses``) is a capture server on the host, with
  request compression off. Codex's account endpoints (plugins, apps,
  connectors, settings) still reach ChatGPT for real, and so does the model
  catalog (``GET .../models``, forwarded to ``chatgpt.com``), so the agent
  gets the tools a real episode would.
- The capture server answers the first model request with a code-mode
  ``exec`` call. That call waits (``--wait-seconds``, so the account's plugin
  sync and the MCP refresh after it finish), then prints the names in
  ``ALL_TOOLS``. The follow-up request is answered with one word.

The episode runs without the egress firewall, so that the harness can reach
the capture server on a second host port; it holds only a public seed.
The privileges are dropped exactly as the firewall entrypoint drops them.

The audit fails if the agent could reach any MCP tool other than
``mcp__gm_bench__*`` or a plugin-install tool (``request_plugin_install``),
if the prompt carries a ``<recommended_plugins>`` list, if any account plugin
was synced into the home, or if no GM-Bench tool is reachable (then the
launch proved nothing). It prints tool-name counts by server, whether the
GM-Bench tool schemas were in the first prompt or deferred, and PASS or
FAIL; nothing else from the request, and never a credential. The login
Codex leaves is written back to ``--codex-auth-file`` as an episode does.

``--without-disabled-features`` drops the driver's ``-c features.*=false``
overrides, to show what the audit catches without them. Hold
``flock /tmp/gmb-subscription-smoke.lock`` around it, as around any launch
with the real login.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.agentic.brief import task_brief  # noqa: E402
from gm_bench.agentic.codex import DISABLED_FEATURES, CodexDriver  # noqa: E402
from gm_bench.agentic.container import (  # noqa: E402
    CODEX_IMAGE,
    EGRESS_ENTRYPOINT,
    HOME,
    HOST_ALIAS,
    driver_listen_host,
    ensure_image,
)
from gm_bench.agentic.episode import AgenticEpisode  # noqa: E402
from gm_bench.agentic.opencode import HarnessLaunch  # noqa: E402
from gm_bench.agentic.prompt_check import CaptureServer, _Handler  # noqa: E402
from gm_bench.simulator import League  # noqa: E402

CHATGPT_CODEX = "https://chatgpt.com/backend-api/codex"
CAPTURE_PATH = "/backend-api/codex"
# What the firewall entrypoint ends with (``container.EGRESS_SCRIPT``), minus the firewall.
DROP_PRIVILEGES = [
    "setpriv",
    "--reuid=node",
    "--regid=node",
    "--init-groups",
    "--inh-caps=-all",
    "--bounding-set=-all",
    "env",
    f"HOME={HOME}",
    "USER=node",
    "LOGNAME=node",
]
GM_BENCH_SERVER = "gm_bench"
PLUGIN_INSTALL_TOOLS = ("request_plugin_install",)
_SKIP_HEADERS = {"host", "accept-encoding", "connection", "content-length"}


def probe_source(wait_seconds: float) -> str:
    """The ``exec`` script: wait for the account sync, then print every tool name the agent could call."""
    return (
        '// @exec: {"yield_time_ms": 120000, "max_output_tokens": 30000}\n'
        "const before = ALL_TOOLS.length;\n"
        f"await new Promise(resolve => setTimeout(resolve, {int(wait_seconds * 1000)}));\n"
        "text(JSON.stringify({gmb_audit: {before, names: ALL_TOOLS.map(tool => tool.name)}}));\n"
    )


def _usage() -> dict[str, Any]:
    return {
        "input_tokens": 1,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 1,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 2,
    }


def declared_tools(request: dict[str, Any]) -> list[dict[str, Any]]:
    """The tools a Responses request declares: top level and in ``additional_tools`` input items, namespaces opened."""
    tools = list(request.get("tools") or [])
    for item in request.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            tools += item.get("tools") or []
    flat: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "namespace":
            flat += [nested for nested in tool.get("tools") or [] if isinstance(nested, dict)]
        elif isinstance(tool, dict):
            flat.append(tool)
    return flat


def has_code_mode(request: dict[str, Any]) -> bool:
    return any(tool.get("name") == "exec" and tool.get("type") == "custom" for tool in declared_tools(request))


def prompt_tool_names(request: dict[str, Any]) -> list[str]:
    """Every tool the first prompt names: declared tools and the ``exec`` description's nested tools."""
    names = {str(tool.get("name")) for tool in declared_tools(request) if tool.get("name")}
    for tool in declared_tools(request):
        names.update(re.findall(r"^### `([^`]+)`", str(tool.get("description") or ""), re.MULTILINE))
    return sorted(names)


class AuditHandler(_Handler):
    """The capture server's side of the audit: model requests captured, the model catalog forwarded."""

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        path, _, query = self.path.partition("?")
        if self.headers.get("upgrade") or not path.rstrip("/").endswith("/models"):
            # A WebSocket upgrade is refused, so Codex falls back to HTTPS, which the server reads.
            self.server.record({"kind": "other", "method": "GET", "path": path})
            return self._json(404, {"error": {"message": "gm-bench audit: not found"}})
        url = CHATGPT_CODEX + path.split(CAPTURE_PATH, 1)[-1] + (f"?{query}" if query else "")
        headers = {key: value for key, value in self.headers.items() if key.lower() not in _SKIP_HEADERS}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                code, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, data = error.code, error.read()
        except OSError as error:
            code, data = 502, json.dumps({"error": {"message": str(error)}}).encode()
        self.server.record({"kind": "catalog", "status": code})
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        path = self.path.split("?", 1)[0]
        body = self._body()
        encoding = (self.headers.get("content-encoding") or "identity").lower()
        if not path.endswith("/responses") or encoding != "identity":
            self.server.record({"kind": "other", "method": "POST", "path": path, "encoding": encoding})
            return self._json(404, {"error": {"message": "gm-bench audit: not found"}})
        request = json.loads(body)
        self.server.record({"kind": "model", "request": request})
        last = (request.get("input") or [{}])[-1]
        answered = isinstance(last, dict) and last.get("type") == "custom_tool_call_output"
        if answered or not has_code_mode(request):
            return self._responses(request)
        item = {
            "id": "ctc_gmb_audit",
            "type": "custom_tool_call",
            "status": "completed",
            "call_id": "call_gmb_audit",
            "name": "exec",
            "input": probe_source(self.server.wait_seconds),
        }
        response = {
            "id": "resp_gmb_audit",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": request.get("model"),
            "output": [item],
            "usage": _usage(),
        }
        self._sse(
            [
                ("response.created", {"type": "response.created", "response": {**response, "output": []}}),
                (
                    "response.output_item.added",
                    {"type": "response.output_item.added", "output_index": 0, "item": {**item, "input": ""}},
                ),
                ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
                ("response.completed", {"type": "response.completed", "response": response}),
            ]
        )


def probe_result(requests: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The ``ALL_TOOLS`` report the ``exec`` call printed, read back from the follow-up request."""
    for request in requests:
        for item in request.get("input") or []:
            if not (isinstance(item, dict) and item.get("type") == "custom_tool_call_output"):
                continue
            output = item.get("output")
            text = (
                output
                if isinstance(output, str)
                else "".join(part.get("text", "") for part in output or [] if isinstance(part, dict))
            )
            match = re.search(r'\{"gmb_audit":.*\}\}', text)
            if match:
                return json.loads(match.group(0))["gmb_audit"]
    return None


def server_of(name: str) -> str:
    """``mcp__<server>__<tool>`` to its server; everything else is a Codex built-in."""
    return name.split("__")[1] if name.startswith("mcp__") and name.count("__") >= 2 else "built-in"


def evaluate(requests: list[dict[str, Any]], plugin_cache_entries: int | None) -> dict[str, Any]:
    """Counts by server and the audit's problems (empty: PASS)."""
    problems: list[str] = []
    if not requests:
        return {"problems": ["Codex sent no model request to the capture server"], "servers": {}}
    first = requests[0]
    prompt_names = prompt_tool_names(first)
    probe = probe_result(requests)
    if has_code_mode(first):
        if probe is None:
            problems.append("the exec call printed no ALL_TOOLS report")
            names: list[str] = prompt_names
        else:
            names = sorted(set(probe["names"]) | set(prompt_names))
    else:
        names = prompt_names
    servers = Counter(server_of(name) for name in names)
    others = {server: count for server, count in servers.items() if server not in ("built-in", GM_BENCH_SERVER)}
    if others:
        problems.append(f"MCP tools from servers other than gm-bench: {others}")
    install = [name for name in names if name in PLUGIN_INSTALL_TOOLS]
    if install:
        problems.append(f"plugin-install tool(s): {install}")
    if "<recommended_plugins>" in json.dumps(first):
        problems.append("the prompt lists <recommended_plugins>")
    if plugin_cache_entries:
        problems.append(f"{plugin_cache_entries} account plugin(s) synced into the harness home")
    if not servers.get(GM_BENCH_SERVER):
        problems.append("no GM-Bench tool reachable: the launch proved nothing")
    gm_bench_in_prompt = sum(1 for name in prompt_names if server_of(name) == GM_BENCH_SERVER)
    return {
        "problems": problems,
        "servers": dict(sorted(servers.items())),
        "code_mode": has_code_mode(first),
        "model_requests": len(requests),
        "first_request_characters": len(json.dumps(first)),
        "gm_bench_tools": servers.get(GM_BENCH_SERVER, 0),
        "gm_bench_tools_in_first_prompt": gm_bench_in_prompt,
        # Codex's identifier for a GM-Bench tool anywhere in the first request (a schema or a bare name).
        "gm_bench_identifiers_in_first_request": json.dumps(first).count(f"mcp__{GM_BENCH_SERVER}__"),
        "built_ins": sorted(name for name in names if server_of(name) == "built-in"),
        "plugin_cache_entries": plugin_cache_entries,
    }


def _plugin_cache_entries(launch: HarnessLaunch, docker: str) -> int | None:
    """How many plugin bundles Codex synced into the home volume (``plugins/cache/<marketplace>/<plugin>``)."""
    assert launch.container is not None
    listing = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "node",
            "--mount",
            f"type=volume,source={launch.container.volume},target={HOME}",
            "--entrypoint",
            "sh",
            launch.container.image["image_id"],
            "-c",
            f"ls -d {HOME}/.codex/plugins/cache/*/* 2>/dev/null | wc -l",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return int(listing.stdout.strip()) if listing.returncode == 0 and listing.stdout.strip().isdigit() else None


def without_disabled_features(args: list[str]) -> list[str]:
    flags = {f"features.{name}=false" for name in DISABLED_FEATURES}
    kept: list[str] = []
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg == "-c" and index + 1 < len(args) and args[index + 1] in flags:
            skip = True
            continue
        kept.append(arg)
    return kept


def run_audit(
    *,
    auth_file: Path,
    model: str,
    seed: int,
    docker: str = "docker",
    wait_seconds: float = 15.0,
    timeout: float = 300.0,
    disabled_features: bool = True,
    codex_version: str | None = None,
) -> dict[str, Any]:
    # Another Codex version builds (or finds) the same image with that version pinned: the committed
    # 0.156.1 rows ran in exactly ``dataclasses.replace(CODEX_IMAGE, version="0.156.1")``.
    spec = dataclasses.replace(CODEX_IMAGE, version=codex_version) if codex_version else CODEX_IMAGE
    image = ensure_image(docker=docker, spec=spec)
    driver = CodexDriver(auth_file=auth_file)
    driver.preflight("container")
    work = Path(tempfile.mkdtemp(prefix="gmb-codex-audit-"))
    events, errors = work / "codex-events.jsonl", work / "codex-stderr.log"
    episode = AgenticEpisode(seed, 1, 0, ledger_path=work / "ledger.jsonl")
    server = CaptureServer(host=driver_listen_host(image), handler=AuditHandler)
    server.wait_seconds = wait_seconds  # type: ignore[attr-defined]
    plugin_cache: int | None = None
    exit_code: int | None = None
    try:
        with server:
            launch = HarnessLaunch(
                episode,
                binary="codex",
                isolation="container",
                image=image,
                docker=docker,
                driver=driver,
                evidence_paths=(events, errors),
            )
            try:
                launch.prepare()
                brief = task_brief(1, League.new(seed=seed, user_team_id=0).user_team.name, 0)
                args = driver.run_args(
                    model=model, variant=None, workdir=launch.workdir, brief=brief, isolation="container"
                )
                if not disabled_features:
                    args = without_disabled_features(args)
                base = f"http://{HOST_ALIAS}:{server.server_address[1]}{CAPTURE_PATH}"
                args = [
                    args[0],
                    "-c",
                    f"openai_base_url={json.dumps(base)}",
                    "-c",
                    "features.enable_request_compression=false",
                    *args[1:],
                ]
                argv, _kill = launch.command(args)
                assert launch.container is not None
                at = argv.index(EGRESS_ENTRYPOINT)
                if argv[at + 1] != str(launch.container.driver_port):
                    raise RuntimeError("unexpected container command line")
                argv[at : at + 2] = DROP_PRIVILEGES
                with events.open("w") as out, errors.open("w") as err:
                    try:
                        exit_code = subprocess.run(
                            argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout, check=False
                        ).returncode
                    except subprocess.TimeoutExpired:
                        exit_code = None
                plugin_cache = _plugin_cache_entries(launch, docker)
            finally:
                launch.close()
            requests = [record["request"] for record in server.records if record["kind"] == "model"]
    finally:
        episode.close()
        for path in sorted(work.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        work.rmdir()
    report = evaluate(requests, plugin_cache)
    report.update(
        {
            "codex_image": image.get("image") or image.get("image_id"),
            "model": model,
            "seed": seed,
            "disabled_features": list(DISABLED_FEATURES) if disabled_features else [],
            "exit_code": exit_code,
            "ok": not report["problems"],
        }
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--codex-auth-file", required=True, type=Path, help="the auth.json the panel will use")
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--seed", type=int, default=11, help="a public seed (default 11)")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--wait-seconds", type=float, default=15.0)
    parser.add_argument(
        "--without-disabled-features",
        action="store_true",
        help="drop the driver's -c features.*=false overrides (shows what the audit catches)",
    )
    parser.add_argument(
        "--codex-version", help=f"audit another Codex CLI version's image (default the pinned {CODEX_IMAGE.version})"
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    options = parser.parse_args(argv)
    report = run_audit(
        auth_file=options.codex_auth_file.expanduser(),
        model=options.model,
        seed=options.seed,
        docker=options.docker,
        wait_seconds=options.wait_seconds,
        disabled_features=not options.without_disabled_features,
        codex_version=options.codex_version,
    )
    if options.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"codex tool audit: {report['codex_image']} {report['model']} seed {report['seed']}")
        print(f"  disabled features: {report['disabled_features'] or 'none'}")
        print(f"  model requests: {report['model_requests'] if 'model_requests' in report else 0}")
        print(f"  code mode: {report.get('code_mode')}")
        print(f"  tools by server: {report['servers']}")
        print(
            f"  GM-Bench tools: {report.get('gm_bench_tools', 0)}, "
            f"of which in the first prompt: {report.get('gm_bench_tools_in_first_prompt', 0)} "
            f"(identifiers in the first request: {report.get('gm_bench_identifiers_in_first_request', 0)})"
        )
        print(f"  account plugins synced into the home: {report.get('plugin_cache_entries')}")
        for problem in report["problems"]:
            print(f"  problem: {problem}")
        print("PASS" if report["ok"] else "FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
