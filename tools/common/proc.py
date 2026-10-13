"""Subprocess helpers shared by the developer tools."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

from tools.common.error import ToolError


def run_argv(
    argv: list[str],
    *,
    timeout: float | None = None,
    passthrough: bool = False,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            timeout=timeout,
            text=True,
            cwd=None if cwd is None else str(cwd),
            env=env,
            stdout=None if passthrough else subprocess.PIPE,
            stderr=None if passthrough else subprocess.STDOUT,
        )
    except FileNotFoundError as e:
        msg = f"command not found: {argv[0]}"
        raise ToolError(msg) from e
    except subprocess.TimeoutExpired as e:
        msg = f"command timed out after {timeout}s: {shlex.join(argv)}"
        raise ToolError(msg) from e


def guest_argv(vm_name: str, args: Sequence[str]) -> list[str]:
    # limactl forwards each arg verbatim to the guest command — no guest
    # shell re-parses the line, so args must NOT be quoted here.
    return ["limactl", "shell", vm_name, "--", *args]
