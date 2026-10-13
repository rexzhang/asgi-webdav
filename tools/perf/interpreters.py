"""Interpreter discovery and JIT/free-threading probing."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.common.env import REPO_ROOT
from tools.common.error import ToolError
from tools.common.proc import run_argv
from tools.perf.settings import PROBE_TIMEOUT, Settings, scrub_child_env


@dataclass
class Interpreter:
    label: str
    path: Path
    available: bool
    version: str = ""
    free_threaded: bool = False
    gil_enabled: bool | None = None
    uvloop: bool = False
    httptools: bool = False
    profiling_pkg: bool = False
    jit_build: bool = False
    env_extra: dict[str, str] = field(default_factory=dict)
    reason: str = ""

    def to_meta(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "path": str(self.path),
            "available": self.available,
            "version": self.version,
            "free_threaded": self.free_threaded,
            "gil_enabled": self.gil_enabled,
            "uvloop": self.uvloop,
            "httptools": self.httptools,
            "profiling_pkg": self.profiling_pkg,
            "jit_build": self.jit_build,
            "env_extra": self.env_extra,
            "reason": self.reason,
        }


_PROBE_SCRIPT = """
import json, sys, sysconfig
data = {
    "version": sys.version.split()[0],
    "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
}
try:
    data["gil_enabled"] = sys._is_gil_enabled()
except Exception:
    data["gil_enabled"] = None
try:
    # 3.15+: sys._jit exposes is_available()/is_enabled()/is_active()
    data["jit_enabled"] = bool(sys._jit.is_enabled())
except Exception:
    data["jit_enabled"] = None
for name in ("aiofiles", "uvloop", "httptools", "uvicorn", "profiling.sampling"):
    try:
        __import__(name)
        data[name.replace(".", "_")] = True
    except Exception:
        data[name.replace(".", "_")] = False
print(json.dumps(data))
"""


def probe_interpreter(
    label: str, raw_path: str, *, env_extra: dict[str, str] | None = None
) -> Interpreter:
    path = Path(raw_path) if Path(raw_path).is_absolute() else REPO_ROOT / raw_path
    interp = Interpreter(
        label=label, path=path, available=False, env_extra=env_extra or {}
    )
    if not raw_path:
        interp.reason = "not configured"
        return interp
    if not path.exists():
        interp.reason = f"interpreter not found: {path}"
        return interp
    result = run_argv(
        [str(path), "-c", _PROBE_SCRIPT],
        timeout=PROBE_TIMEOUT,
        env={**scrub_child_env(), **(env_extra or {})},
    )
    if result.returncode != 0:
        interp.reason = f"probe failed: {result.stdout[-200:]}"
        return interp
    try:
        data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as e:
        interp.reason = f"probe output unreadable: {e}"
        return interp
    interp.available = True
    interp.version = str(data.get("version", ""))
    interp.free_threaded = bool(data.get("free_threaded"))
    gil_enabled = data.get("gil_enabled")
    interp.gil_enabled = None if gil_enabled is None else bool(gil_enabled)
    interp.uvloop = bool(data.get("uvloop"))
    interp.httptools = bool(data.get("httptools"))
    interp.profiling_pkg = bool(data.get("profiling_sampling"))
    jit_from_probe = data.get("jit_enabled")
    if jit_from_probe is not None:
        interp.jit_build = bool(jit_from_probe)
    else:
        interp.jit_build = _detect_jit_build(interp)
    return interp


def _detect_jit_build(interp: Interpreter) -> bool:
    """Distinguish a JIT-enabled build by timing a loop with PYTHON_JIT on/off.

    On non-JIT builds both runs are equal; on JIT builds the flag changes the
    execution mode. Verified empirically and recorded in meta.
    """
    code = (
        "import time; s = 0; t0 = time.perf_counter(); "
        "for i in range(600_000): s += i * i; "
        "print(f'{time.perf_counter() - t0:.4f}')"
    )
    base_env = {**scrub_child_env(), **interp.env_extra}
    timings: list[float] = []
    for flag in ("0", "1"):
        best = float("inf")
        for _ in range(2):
            env = {**base_env, "PYTHON_JIT": flag}
            result = run_argv([str(interp.path), "-c", code], timeout=60, env=env)
            if result.returncode != 0:
                return False
            try:
                best = min(best, float(result.stdout.strip().splitlines()[-1]))
            except (ValueError, IndexError):
                return False
        timings.append(best)
    if timings[0] <= 0:
        return False
    return timings[0] / timings[1] > 1.05


def discover_interpreters(
    settings: Settings, labels: Sequence[str] | None = None
) -> list[Interpreter]:
    wanted = tuple(labels) if labels else ("py314", "py315", "py315t")
    env_map = {
        "py314": settings.python_314,
        "py315": settings.python_315,
        "py315t": settings.python_315t,
    }
    found: list[Interpreter] = []
    for label in wanted:
        raw = env_map.get(label)
        if raw is None:
            msg = (
                f"unknown interpreter label {label!r}, expected one of {tuple(env_map)}"
            )
            raise ToolError(msg)
        found.append(probe_interpreter(label, raw))
    return found
