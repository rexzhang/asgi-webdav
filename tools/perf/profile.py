"""Tachyon (profiling.sampling) run-mode orchestration."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import click

from tools.common.env import REPO_ROOT
from tools.common.error import ToolError
from tools.common.proc import run_argv
from tools.perf.config_gen import build_config_dict, config_to_toml, fs_uri_for
from tools.perf.interpreters import Interpreter
from tools.perf.loadgen import run_driver_load
from tools.perf.server import READY_TIMEOUT, _free_port, _probe_ready
from tools.perf.settings import Settings, scrub_child_env
from tools.perf.workloads import Workload


def _kill_port_listeners(port: int) -> None:
    """Best-effort cleanup of processes left listening on the port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"], timeout=15, text=True, capture_output=True
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for pid_text in result.stdout.split():
        try:
            os.kill(int(pid_text), 15)
        except (ValueError, ProcessLookupError, PermissionError):
            continue


def run_profile(
    settings: Settings,
    run_dir: Path,
    interp: Interpreter,
    workload: Workload,
    *,
    mode: str,
    duration: float,
    native: bool,
    opcodes: bool,
    async_aware: bool,
) -> Path:

    if not interp.profiling_pkg:
        msg = f"{interp.label} has no profiling.sampling (need 3.15+)"
        raise ToolError(msg)
    if interp.free_threaded and mode == "gil":
        msg = "gil mode is not applicable to free-threaded builds"
        raise ToolError(msg)

    out_dir = run_dir / f"profile-{mode}-{workload.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    binary_path = out_dir / "profile.bin"
    config = build_config_dict(
        "base", fixtures_fs_uri=fs_uri_for(settings.fixtures_dir)
    )
    config_path = out_dir / "config-base.toml"
    config_path.write_text(config_to_toml(config), encoding="utf-8")

    # the profiler launches the profiled server itself; the port must be
    # known up-front so the load driver can find it
    def _sample(flags: list[str], out_file: Path, log_name: str) -> bool:
        port = _free_port()
        argv = [
            str(interp.path),
            "-m",
            "profiling.sampling",
            "run",
            "-m",
            "--mode",
            mode,
            "-r",
            settings.sampling_rate,
            "-d",
            f"{int(duration)}",
            *flags,
            "-o",
            str(out_file),
            "asgi_webdav",
            "-c",
            str(config_path),
            "-H",
            "127.0.0.1",
            "-P",
            str(port),
        ]
        env = scrub_child_env()
        env.update(interp.env_extra)
        profiler_log = (out_dir / log_name).open("w", encoding="utf-8")
        process = subprocess.Popen(
            argv,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=profiler_log,
            stderr=subprocess.STDOUT,
        )
        profiler_log.close()
        try:
            deadline = time.monotonic() + READY_TIMEOUT
            while time.monotonic() < deadline and not _probe_ready(port):
                if process.poll() is not None:
                    break
                time.sleep(0.2)
            if process.poll() is None:
                run_driver_load(workload, port, 4, duration=duration + 5.0, count=None)
            process.wait(timeout=duration + 180.0)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
            _kill_port_listeners(port)
        return process.returncode == 0 and out_file.exists()

    main_flags = ["-a", "--binary"]
    if native:
        main_flags.append("--native")
    if opcodes:
        main_flags.append("--opcodes")
    # NOTE: --async-aware is incompatible with --binary/--native/-a in the
    # 3.15 implementation, so it runs as a separate collapsed-only pass
    if not _sample(main_flags, binary_path, "profiler.log"):
        msg = (
            f"profiler failed, see {out_dir / 'profiler.log'}; "
            "on macOS this is usually the sampling permission"
        )
        raise ToolError(msg)
    if async_aware:
        _sample(
            ["--async-aware", "--collapsed"],
            out_dir / "collapsed-async.txt",
            "profiler-async.log",
        )

    for out_flag, name in (
        ("--collapsed", "collapsed.txt"),
        ("--flamegraph", "flamegraph.html"),
        ("--pstats", "pstats.txt"),
    ):
        run_argv(
            [
                str(interp.path),
                "-m",
                "profiling.sampling",
                "replay",
                out_flag,
                "-o",
                str(out_dir / name),
                str(binary_path),
            ],
            timeout=300.0,
        )
    click.echo(f"profile written: {out_dir}")
    return out_dir
