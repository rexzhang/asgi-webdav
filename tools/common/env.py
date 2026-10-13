"""Repo paths and the shared dotenv-backed environment reader.

Precedence for every reader: ``.env`` file > process environment > default.
Each tool passes its own prefix (``TOOLS_PERF_`` / ``TOOLS_LITMUS_``); pass
an empty prefix to read a full key directly (litmus per-target overrides).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

from tools.common.error import ToolError

REPO_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = REPO_ROOT / ".env"

_DOTENV: Mapping[str, str | None] | None = None


def _dotenv() -> Mapping[str, str | None]:
    global _DOTENV
    if _DOTENV is None:
        _DOTENV = dotenv_values(DOTENV_PATH) if DOTENV_PATH.exists() else {}
    return _DOTENV


def env_str(prefix: str, name: str, default: str = "") -> str:
    value = _dotenv().get(f"{prefix}{name}")
    if value is None:
        value = os.environ.get(f"{prefix}{name}")
    return default if value is None else value


def env_int(prefix: str, name: str, default: int) -> int:
    raw = env_str(prefix, name, str(default))
    try:
        return int(raw)
    except ValueError:
        msg = f"env var {prefix + name!r} must be an integer, got {raw!r}"
        raise ToolError(msg) from None


def env_float(prefix: str, name: str, default: float) -> float:
    raw = env_str(prefix, name, str(default))
    try:
        return float(raw)
    except ValueError:
        msg = f"env var {prefix + name!r} must be a number, got {raw!r}"
        raise ToolError(msg) from None


def env_list(prefix: str, name: str, default: str = "") -> tuple[str, ...]:
    raw = env_str(prefix, name, default)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def env_int_list(prefix: str, name: str, default_csv: str) -> tuple[int, ...]:
    raw = env_str(prefix, name, default_csv)
    values: list[int] = []
    for part in (piece.strip() for piece in raw.split(",")):
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            msg = f"env var {prefix + name!r} must be csv integers, got {raw!r}"
            raise ToolError(msg) from None
    return tuple(values)
