"""SQLite persistence for GM-Bench runs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("data/gm_bench.sqlite")


def log_payload(command: str, payload: Any, db_path: str | Path = DEFAULT_DB_PATH) -> str:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    normalized_payloads = payload if isinstance(payload, list) else [payload]
    summary = _summary_for_payload(command, payload)

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        initialize(connection)
        connection.execute(
            """
            INSERT INTO runs (
                id, created_at, command, agent, seasons, seeds_json,
                summary_json, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                created_at,
                command,
                summary.get("agent"),
                summary.get("seasons"),
                json.dumps(summary.get("seeds", []), sort_keys=True),
                json.dumps(summary, sort_keys=True),
                json.dumps(payload, sort_keys=True),
            ),
        )
        for agent_payload in normalized_payloads:
            _insert_agent_payload(connection, run_id, agent_payload)
    return run_id


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            command TEXT NOT NULL,
            agent TEXT,
            seasons INTEGER,
            seeds_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            agent TEXT NOT NULL,
            seed INTEGER NOT NULL,
            seasons INTEGER NOT NULL,
            final_score REAL NOT NULL,
            wins INTEGER NOT NULL,
            championships INTEGER NOT NULL,
            illegal_actions INTEGER NOT NULL,
            season_summaries_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
            season INTEGER NOT NULL,
            phase TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            accepted INTEGER NOT NULL,
            message TEXT NOT NULL,
            action_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_episodes_agent ON episodes(agent);
        CREATE INDEX IF NOT EXISTS idx_episodes_score ON episodes(final_score);
        CREATE INDEX IF NOT EXISTS idx_transactions_run_id ON transactions(run_id);
        """
    )


def _insert_agent_payload(connection: sqlite3.Connection, run_id: str, payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for episode in payload.get("episodes", []):
        cursor = connection.execute(
            """
            INSERT INTO episodes (
                run_id, agent, seed, seasons, final_score, wins,
                championships, illegal_actions, season_summaries_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                episode.get("agent", payload.get("agent", "unknown")),
                episode.get("seed", 0),
                episode.get("seasons", payload.get("seasons", 0)),
                episode.get("final_score", 0.0),
                episode.get("wins", 0),
                episode.get("championships", 0),
                episode.get("illegal_actions", 0),
                json.dumps(episode.get("season_summaries", []), sort_keys=True),
            ),
        )
        episode_id = int(cursor.lastrowid)
        for transaction in episode.get("transactions", []):
            connection.execute(
                """
                INSERT INTO transactions (
                    run_id, episode_id, season, phase, team_id,
                    accepted, message, action_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    episode_id,
                    transaction.get("season", 0),
                    transaction.get("phase", ""),
                    transaction.get("team_id", 0),
                    1 if transaction.get("accepted") else 0,
                    transaction.get("message", ""),
                    json.dumps(transaction.get("action", {}), sort_keys=True),
                ),
            )


def _summary_for_payload(command: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if command == "evaluate" and "normalized" in payload:
            return {
                "agent": payload.get("agent"),
                "seasons": payload.get("seasons"),
                "seeds": payload.get("seeds", []),
                **payload.get("normalized", {}),
            }
        return {
            "agent": payload.get("agent"),
            "seasons": payload.get("seasons"),
            "seeds": payload.get("seeds", []),
            **payload.get("summary", {}),
        }
    if isinstance(payload, list):
        agents = [item.get("agent") for item in payload if isinstance(item, dict)]
        return {
            "agent": ",".join(agent for agent in agents if agent),
            "seasons": payload[0].get("seasons") if payload and isinstance(payload[0], dict) else None,
            "seeds": payload[0].get("seeds", []) if payload and isinstance(payload[0], dict) else [],
            "agents": agents,
        }
    return {"agent": None, "seasons": None, "seeds": []}

