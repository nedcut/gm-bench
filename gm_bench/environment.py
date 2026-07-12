"""Minimal local environment-file loading without a runtime dependency."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_environment_files(directory: str | Path | None = None) -> list[Path]:
    """Load `.env.local`, then `.env`, without overriding the process env.

    The local file wins over the shared file, while values explicitly exported
    by the caller win over both. Values are never printed or returned.
    """
    root = Path(directory) if directory is not None else Path.cwd()
    loaded: list[Path] = []
    for name in (".env.local", ".env"):
        path = root / name
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        loaded.append(path)
        for line in lines:
            parsed = _parse_env_line(line)
            if parsed is not None:
                key, value = parsed
                os.environ.setdefault(key, value)
    return loaded


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[7:].lstrip()
    if "=" not in text:
        return None
    key, value = text.split("=", 1)
    key = key.strip()
    if not _ENV_NAME.fullmatch(key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value
