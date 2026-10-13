"""Compatibility check: pytest suite + smoke load + env collection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.common.env import REPO_ROOT
from tools.common.proc import run_argv
from tools.perf.bench import BenchContext
from tools.perf.config_gen import build_config_dict, config_to_toml, fs_uri_for
from tools.perf.interpreters import Interpreter
from tools.perf.loadgen import run_driver_load
from tools.perf.server import ServerHandle
from tools.perf.settings import scrub_child_env
from tools.perf.workloads import PROPFIND_ALLPROP_BODY, Workload

PYTEST_TIMEOUT = 2400.0


def compat_pytest(interp: Interpreter) -> dict[str, Any]:
    result = run_argv(
        [
            str(interp.path),
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-q",
            # the bench venvs install core deps only; the webhdfs extra
            # (httpx + httpx-kerberos) is out of compat scope
            "--ignore=tests/test_provider_webhdfs.py",
        ],
        timeout=PYTEST_TIMEOUT,
        cwd=REPO_ROOT,
        env=scrub_child_env(),
    )
    text = result.stdout
    failed_match = re.search(r"(\d+) failed", text)
    passed_match = re.search(r"(\d+) passed", text)
    return {
        "exit_code": result.returncode,
        "failed": int(failed_match.group(1)) if failed_match else 0,
        "passed": int(passed_match.group(1)) if passed_match else 0,
        "tail": text[-400:],
    }


def compat_smoke(
    ctx: BenchContext, interp: Interpreter, *, per_workload: float
) -> dict[str, Any]:

    config = build_config_dict(
        "base", fixtures_fs_uri=fs_uri_for(ctx.settings.fixtures_dir)
    )
    config_path = ctx.run_dir / f"compat-config-{interp.label}.toml"
    config_path.write_text(config_to_toml(config), encoding="utf-8")
    server = ServerHandle(
        interp, config_path, ctx.run_dir / f"compat-server-{interp.label}.log"
    )
    results: dict[str, Any] = {}
    try:
        if not server.wait_ready():
            results["error"] = "server failed to start"
            return results
        smoke_workloads = (
            Workload("options", "OPTIONS", "/"),
            Workload("get-4k", "GET", "/fs/4k.bin"),
            Workload(
                "put-4k",
                "PUT",
                "/fs/put-4k.bin",
                body="a" * 4096,
                content_type="application/octet-stream",
            ),
            Workload(
                "propfind-1-100",
                "PROPFIND",
                "/fs/dir-100",
                body=PROPFIND_ALLPROP_BODY,
                content_type="application/xml",
            ),
            # free-threading stress: concurrent writes into one file path
            Workload(
                "put-stress",
                "PUT",
                "/fs/put-stress.bin",
                body="b" * 4096,
                content_type="application/octet-stream",
            ),
        )
        for workload in smoke_workloads:
            raw = run_driver_load(
                workload, server.port, 4, duration=per_workload, count=None
            )
            results[workload.name] = {
                "requests": int(raw.get("requests", 0)),
                "errors": int(raw.get("errors", 0)),
                "status_counts": raw.get("status_counts", {}),
            }
        # uvicorn prefers uvloop when importable; the warning-level banner
        # does not name the loop, so record the inferred one
        results["event_loop"] = "uvloop" if interp.uvloop else "asyncio"
    finally:
        server.stop()
    return results


def collect_compat_entries(run_dir: Path) -> dict[str, dict[str, Any]]:
    compat_dir = run_dir / "compat"
    entries: dict[str, dict[str, Any]] = {}
    if compat_dir.exists():
        for path in sorted(compat_dir.glob("*.json")):
            try:
                entries[path.stem] = dict(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    return entries


def write_compat_summary(run_dir: Path, entries: dict[str, dict[str, Any]]) -> None:
    lines = [
        "| interpreter | pytest | smoke errors | loop | FT | gil_enabled | jit_build |",
        "|---|---|---:|---|---|---|---|",
    ]
    for label, data in entries.items():
        pytest_part = data.get("pytest", {})
        smoke = data.get("smoke", {})
        smoke_errors = sum(
            int(v.get("errors", 0))
            for k, v in smoke.items()
            if isinstance(v, dict) and k != "event_loop"
        )
        meta = data.get("probe", {})
        pytest_cell = (
            "n/a"
            if "exit_code" not in pytest_part
            else (
                "ok"
                if pytest_part["exit_code"] == 0
                else f"FAILED({pytest_part.get('failed', '?')})"
            )
        )
        lines.append(
            f"| {label} | {pytest_cell} | {smoke_errors} "
            f"| {smoke.get('event_loop', '?')} | {meta.get('free_threaded', '?')} "
            f"| {meta.get('gil_enabled', '?')} | {meta.get('jit_build', '?')} |"
        )
    (run_dir / "compat").mkdir(parents=True, exist_ok=True)
    (run_dir / "compat" / "summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# profile (Tachyon run mode)
