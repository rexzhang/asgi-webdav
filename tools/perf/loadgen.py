"""Load generators: the stdlib driver subprocess and oha."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.common.error import ToolError
from tools.common.proc import run_argv
from tools.perf.settings import PROBE_TIMEOUT, Settings, scrub_child_env
from tools.perf.workloads import Workload


def _json_get(data: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in data:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    return default


def normalize_loadgen_output(raw: dict[str, Any], loadgen: str) -> dict[str, Any]:
    """Map oha/driver JSON onto one shape (tolerant to version drift)."""
    if loadgen == "oha":
        # oha >= 1.16 nests the numbers under "summary"; older versions put
        # them at the top level — read both
        summary = raw.get("summary", raw)
        status = raw.get("statusCodeDistribution", {})
        errors_4xx_up = sum(
            int(v) for k, v in status.items() if str(k).isdigit() and int(k) >= 400
        )
        percentiles = raw.get("latencyPercentiles", {})
        # oha 1.16 has no request count field: derive it from the status
        # distribution, falling back to rps * duration
        total_requests = sum(int(v) for v in status.values() if str(v).isdigit())
        if total_requests == 0:
            total_requests = int(
                _json_get(summary, "requestsPerSec") * _json_get(summary, "total")
            )
        success_rate = _json_get(summary, "successRate", default=1.0)
        errors_total = int(round(total_requests * (1.0 - min(1.0, success_rate))))
        # oha reports latencies in seconds; we standardize on milliseconds
        return {
            "loadgen": "oha",
            "requests": total_requests,
            "errors": max(errors_total, errors_4xx_up),
            "rps": _json_get(summary, "requestsPerSec"),
            "lat_ms_p50": _json_get(percentiles, "p50") * 1000.0,
            "lat_ms_p99": _json_get(percentiles, "p99") * 1000.0,
            "duration": _json_get(summary, "total"),
            "status_counts": {str(k): int(v) for k, v in status.items()},
            "raw": raw,
        }
    return {"loadgen": "driver", **raw}


def run_driver_load(
    workload: Workload,
    port: int,
    concurrency: int,
    *,
    duration: float,
    count: int | None,
    env_extra: dict[str, str] | None = None,
    extra_headers: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    argv = [
        sys.executable,
        str(Path(__file__).resolve().parent / "tasks" / "driver.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--method",
        workload.method,
        "--path",
        workload.path,
        "-c",
        str(concurrency),
        "--auth",
        "username:password",
        "--timeout",
        "30",
    ]
    if count is not None:
        argv += ["--requests", str(count)]
    else:
        argv += ["--duration", f"{duration}"]
    if workload.body is not None:
        argv += ["--body", workload.body]
    for key, value in (*workload.headers, *extra_headers):
        argv += ["--header", f"{key}: {value}"]
    result = run_argv(
        argv,
        timeout=max(120.0, (duration + 60.0) * 4),
        env={**scrub_child_env(), **(env_extra or {})},
    )
    if result.returncode != 0:
        msg = f"driver failed: {result.stdout[-500:]}"
        raise ToolError(msg)
    data: dict[str, Any] = json.loads(result.stdout)
    return normalize_loadgen_output(data, "driver")


def run_oha_load(
    workload: Workload,
    port: int,
    concurrency: int,
    *,
    duration: float,
    count: int | None,
) -> dict[str, Any]:
    argv = [
        "oha",
        "-m",
        workload.method,
        "-c",
        str(concurrency),
        "--output-format",
        "json",
        "-a",
        "username:password",
        "-H",
        "Accept-Encoding: gzip, deflate",
    ]
    if count is not None:
        argv += ["-n", str(count)]
    else:
        argv += ["-z", f"{duration}s"]
    if workload.body is not None:
        argv += ["-d", workload.body, "-T", workload.content_type or "text/plain"]
    for key, value in workload.headers:
        argv += ["-H", f"{key}: {value}"]
    argv.append(f"http://127.0.0.1:{port}{workload.path}")
    result = run_argv(argv, timeout=max(120.0, (duration + 60.0) * 4))
    if result.returncode != 0:
        msg = f"oha failed: {result.stdout[-500:]}"
        raise ToolError(msg)
    try:
        data: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        msg = f"oha output not JSON: {e}: {result.stdout[:200]}"
        raise ToolError(msg) from None
    return normalize_loadgen_output(data, "oha")


def resolve_loadgen(settings: Settings, requested: str) -> str:
    if requested != "auto":
        return requested
    if settings.loadgen != "auto":
        return settings.loadgen
    try:
        probe = run_argv(["oha", "--version"], timeout=PROBE_TIMEOUT)
    except ToolError:
        return "driver"
    return "oha" if probe.returncode == 0 else "driver"


# ---------------------------------------------------------------------------
# run dirs / meta / summaries
