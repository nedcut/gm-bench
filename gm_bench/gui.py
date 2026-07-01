"""Local web GUI for GM-Bench."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from gm_bench.agents import AGENTS
from gm_bench.runner import evaluate_against_baselines, run_many
from gm_bench.storage import DEFAULT_DB_PATH, log_payload

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "gm_bench" / "gui_static"


def serve(host: str = "127.0.0.1", port: int = 8765, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    handler = _handler_factory(Path(db_path))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"GM-Bench GUI running at http://{host}:{port}")
    print(f"Using database: {db_path}")
    server.serve_forever()


def _handler_factory(db_path: Path) -> type[BaseHTTPRequestHandler]:
    class GuiHandler(BaseHTTPRequestHandler):
        server_version = "GMBenchGUI/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_static("index.html")
            elif parsed.path.startswith("/static/"):
                self._send_static(parsed.path.removeprefix("/static/"))
            elif parsed.path == "/api/dashboard":
                self._send_json(dashboard_payload(db_path))
            elif parsed.path == "/api/transactions":
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["40"])[0])
                self._send_json({"transactions": recent_transactions(db_path, limit=limit)})
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/run":
                self._send_json({"error": "not found"}, status=404)
                return
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                request = json.loads(body.decode("utf-8") or "{}")
                result = run_from_request(request, db_path)
                self._send_json(result)
            except (KeyError, TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_static(self, relative_path: str) -> None:
            path = (STATIC_ROOT / relative_path).resolve()
            if not path.is_file() or STATIC_ROOT not in path.parents:
                self._send_json({"error": "not found"}, status=404)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return GuiHandler


def dashboard_payload(db_path: Path) -> dict[str, Any]:
    return {
        "db_path": str(db_path),
        "agents": sorted(AGENTS),
        "metrics": dashboard_metrics(db_path),
        "leaderboard": leaderboard(db_path),
        "runs": recent_runs(db_path),
        "transactions": recent_transactions(db_path),
    }


def dashboard_metrics(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"runs": 0, "episodes": 0, "best_score": 0.0, "illegal_action_rate": 0.0}
    with sqlite3.connect(db_path) as connection:
        runs = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        episodes = connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        best_score = connection.execute("SELECT COALESCE(MAX(final_score), 0) FROM episodes").fetchone()[0]
        actions = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        illegal = connection.execute("SELECT COUNT(*) FROM transactions WHERE accepted = 0").fetchone()[0]
    rate = (illegal / actions * 100.0) if actions else 0.0
    return {"runs": runs, "episodes": episodes, "best_score": round(best_score, 3), "illegal_action_rate": round(rate, 2)}


def leaderboard(db_path: Path, limit: int = 10) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT agent, seed, seasons, final_score, wins, championships, illegal_actions
            FROM episodes
            ORDER BY final_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_runs(db_path: Path, limit: int = 8) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, created_at, command, agent, seasons, seeds_json, summary_json
            FROM runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    runs: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["seeds"] = json.loads(item.pop("seeds_json"))
        item["summary"] = json.loads(item.pop("summary_json"))
        runs.append(item)
    return runs


def recent_transactions(db_path: Path, limit: int = 30) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT t.id, t.run_id, e.agent, e.seed, t.season, t.phase, t.accepted, t.message, t.action_json
            FROM transactions t
            JOIN episodes e ON e.id = t.episode_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    transactions: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["accepted"] = bool(item["accepted"])
        item["action"] = json.loads(item.pop("action_json"))
        transactions.append(item)
    return transactions


def run_from_request(request: dict[str, Any], db_path: Path) -> dict[str, Any]:
    mode = request.get("mode", "run")
    seasons = int(request.get("seasons", 1))
    seeds = _parse_seeds(str(request.get("seeds", "1")))
    if seasons < 1 or seasons > 10:
        raise ValueError("seasons must be between 1 and 10")
    if len(seeds) > 20:
        raise ValueError("at most 20 seeds are allowed from the GUI")

    if mode == "run":
        agent_name = str(request.get("agent", "value"))
        if agent_name not in AGENTS:
            raise ValueError(f"unknown agent: {agent_name}")
        payload = run_many(AGENTS[agent_name](), seeds=seeds, seasons=seasons)
    elif mode == "compare":
        names = request.get("agents") or sorted(AGENTS)
        if not isinstance(names, list):
            raise ValueError("agents must be a list")
        payload = []
        for name in names:
            if name not in AGENTS:
                raise ValueError(f"unknown agent: {name}")
            payload.append(run_many(AGENTS[name](), seeds=seeds, seasons=seasons))
    elif mode == "evaluate":
        agent_name = str(request.get("agent", "value"))
        baselines = request.get("baselines") or ["random", "conservative", "win-now", "rebuild"]
        if agent_name not in AGENTS:
            raise ValueError(f"unknown agent: {agent_name}")
        if not isinstance(baselines, list) or any(name not in AGENTS for name in baselines):
            raise ValueError("baselines must be known built-in agents")
        payload = evaluate_against_baselines(AGENTS[agent_name](), seeds=seeds, seasons=seasons, baseline_names=baselines)
    else:
        raise ValueError("mode must be run, compare, or evaluate")

    run_id = log_payload(mode, payload, db_path)
    return {"run_id": run_id, "result": payload, "dashboard": dashboard_payload(db_path)}


def _parse_seeds(value: str) -> list[int]:
    seeds: list[int] = []
    for part in value.replace(" ", ",").split(","):
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            seeds.extend(range(int(start), int(end) + 1))
        else:
            seeds.append(int(part))
    if not seeds:
        raise ValueError("provide at least one seed")
    return seeds


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gm-bench-gui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args(argv)
    serve(args.host, args.port, args.db)


if __name__ == "__main__":
    main()

