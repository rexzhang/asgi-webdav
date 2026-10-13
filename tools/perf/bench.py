"""Throughput matrix execution (bench combos and stall detection)."""

from __future__ import annotations

import json
import re
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from tools.perf.config_gen import build_config_dict, config_to_toml, fs_uri_for
from tools.perf.interpreters import Interpreter
from tools.perf.loadgen import run_driver_load, run_oha_load
from tools.perf.server import ServerHandle
from tools.perf.settings import Settings
from tools.perf.workloads import WORKLOAD_TABLE, Workload


@dataclass
class BenchSample:
    interpreter: str
    variant: str
    workload: str
    concurrency: int
    rps: float
    lat_ms_p50: float
    lat_ms_p99: float
    requests: int
    errors: int
    duration: float
    server_cpu_s: float  # server CPU seconds, per bench sample (per repeat)
    loadgen: str
    unstable: bool = False

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.interpreter, self.variant, self.workload, self.concurrency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpreter": self.interpreter,
            "variant": self.variant,
            "workload": self.workload,
            "concurrency": self.concurrency,
            "rps": round(self.rps, 2),
            "lat_ms_p50": round(self.lat_ms_p50, 3),
            "lat_ms_p99": round(self.lat_ms_p99, 3),
            "requests": self.requests,
            "errors": self.errors,
            "duration": round(self.duration, 3),
            "server_cpu_s": round(self.server_cpu_s, 3),
            "loadgen": self.loadgen,
            "unstable": self.unstable,
        }

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> BenchSample:
        return cls(
            interpreter=item["interpreter"],
            variant=item["variant"],
            workload=item["workload"],
            concurrency=int(item["concurrency"]),
            rps=float(item["rps"]),
            lat_ms_p50=float(item["lat_ms_p50"]),
            lat_ms_p99=float(item["lat_ms_p99"]),
            requests=int(item["requests"]),
            errors=int(item["errors"]),
            duration=float(item["duration"]),
            server_cpu_s=float(item["server_cpu_s"]),
            loadgen=item["loadgen"],
            unstable=bool(item.get("unstable", False)),
        )


@dataclass
class BenchContext:
    settings: Settings
    run_dir: Path
    loadgen: str
    samples: list[BenchSample]


def bench_one_combo(
    ctx: BenchContext,
    interp: Interpreter,
    server: ServerHandle,
    workload: Workload,
    concurrency: int,
    variant: str,
    *,
    duration: float,
    repeats: int,
    warmup: int,
) -> BenchSample:
    count = workload.count_mode
    loader: Callable[..., dict[str, Any]] = (
        run_oha_load if ctx.loadgen == "oha" else run_driver_load
    )
    combos_dir = (
        ctx.run_dir
        / "bench"
        / interp.label
        / variant
        / workload.name
        / f"c{concurrency}"
    )
    combos_dir.mkdir(parents=True, exist_ok=True)
    raws: list[dict[str, Any]] = []
    for index in range(warmup + repeats):
        raw = loader(workload, server.port, concurrency, duration=duration, count=count)
        raws.append(raw)
        (combos_dir / f"raw-{index}.json").write_text(
            json.dumps(raw.get("raw", raw), indent=2) + "\n", encoding="utf-8"
        )
    # measure the CPU delta AFTER the warmup so server_cpu_s covers only the
    # counted repeats (warmup samples are discarded from rps/p99 as well)
    cpu_before = server.cpu_seconds()
    for index in range(repeats):
        raw = loader(workload, server.port, concurrency, duration=duration, count=count)
        raws.append(raw)
        (combos_dir / f"raw-warm-{index}.json").write_text(
            json.dumps(raw.get("raw", raw), indent=2) + "\n", encoding="utf-8"
        )
    cpu_per_repeat = max(0.0, server.cpu_seconds() - cpu_before) / max(1, repeats)

    effective = raws[warmup:]
    rps_list = [item["rps"] for item in effective]
    median_rps = statistics.median(rps_list)
    mad = (
        statistics.median([abs(r - median_rps) for r in rps_list]) / median_rps
        if median_rps > 0
        else 0.0
    )
    median = min(effective, key=lambda item: abs(item["rps"] - median_rps))
    sample = BenchSample(
        interpreter=interp.label,
        variant=variant,
        workload=workload.name,
        concurrency=concurrency,
        rps=median_rps,
        lat_ms_p50=median.get("lat_ms_p50", 0.0),
        lat_ms_p99=median.get("lat_ms_p99", 0.0),
        requests=int(median.get("requests", 0)),
        errors=int(median.get("errors", 0)),
        duration=median.get("duration", 0.0),
        server_cpu_s=cpu_per_repeat,
        loadgen=ctx.loadgen,
        unstable=mad > 0.05,
    )
    (combos_dir / "sample.json").write_text(
        json.dumps(sample.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return sample


def run_bench_for_interpreter(
    ctx: BenchContext,
    interp: Interpreter,
    variants: Sequence[str],
    workloads: Sequence[Workload],
    concurrencies: Sequence[int],
    *,
    duration: float,
    repeats: int,
    warmup: int,
) -> None:

    for variant in variants:
        config = build_config_dict(
            variant, fixtures_fs_uri=fs_uri_for(ctx.settings.fixtures_dir)
        )
        config_path = ctx.run_dir / f"config-{interp.label}-{variant}.toml"
        config_path.write_text(config_to_toml(config), encoding="utf-8")
        server = ServerHandle(
            interp, config_path, ctx.run_dir / f"server-{interp.label}-{variant}.log"
        )
        try:
            if not server.wait_ready():
                tail = ""
                if server.log_path.exists():
                    tail = server.log_path.read_text(
                        encoding="utf-8", errors="replace"
                    )[-500:]
                click.echo(
                    f"  server failed to start ({interp.label}/{variant}): {tail}"
                )
                return
            for workload in workloads:
                for concurrency in concurrencies:
                    sample = bench_one_combo(
                        ctx,
                        interp,
                        server,
                        workload,
                        concurrency,
                        variant,
                        duration=duration,
                        repeats=repeats,
                        warmup=warmup,
                    )
                    ctx.samples.append(sample)
                    click.echo(
                        f"  {interp.label}/{variant}/{workload.name}/c{concurrency}: "
                        f"{sample.rps:.1f} rps, p99 {sample.lat_ms_p99:.1f} ms"
                        f"{', UNSTABLE' if sample.unstable else ''}"
                    )
                    time.sleep(ctx.settings.cooldown)
        finally:
            server.stop()
            # base variant keeps per-request INFO logging ON PURPOSE (it is
            # one of the measured hot spots); a full matrix then produces
            # hundreds of MB of request lines. Keep the head (uvicorn banner,
            # event-loop evidence) and the tail, drop the middle.
            _truncate_server_log(server.log_path)


def _truncate_server_log(
    log_path: Path, keep_head: int = 30, keep_tail: int = 100
) -> None:
    if not log_path.exists() or log_path.stat().st_size < 200_000:
        return
    with log_path.open("rb") as f:
        head = b"".join(f.readline() for _ in range(keep_head))
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - keep_tail * 80))
        tail = f.read()[-keep_tail * 120 :]
    log_path.write_bytes(
        head + b"\n... [truncated after bench: request log lines] ...\n" + tail
    )


# ---------------------------------------------------------------------------
# stall detection (asyncio debug)


_STALL_RE = re.compile(r"took (\d+\.\d+) seconds")


def run_stall_detection(
    ctx: BenchContext, interp: Interpreter, *, duration: float
) -> None:
    """PYTHONASYNCIODEBUG=1 server + COPY/PROPFIND; grep slow-callback lines."""

    config = build_config_dict(
        "base", fixtures_fs_uri=fs_uri_for(ctx.settings.fixtures_dir)
    )
    config_path = ctx.run_dir / f"config-{interp.label}-stall.toml"
    config_path.write_text(config_to_toml(config), encoding="utf-8")
    log_path = ctx.run_dir / f"server-{interp.label}-stall.log"
    server = ServerHandle(
        interp, config_path, log_path, env_extra={"PYTHONASYNCIODEBUG": "1"}
    )
    try:
        if not server.wait_ready():
            click.echo(f"  stall: server failed to start ({interp.label})")
            return
        destination = f"http://127.0.0.1:{server.port}/fs/copy-dst.bin"
        # a 4KB copy finishes well under the 100ms asyncio-debug threshold;
        # the 64MB payload makes the blocking shutil.* visible
        run_driver_load(
            Workload("copy-64m", "COPY", "/fs/64m.bin"),
            server.port,
            1,
            duration=duration,
            count=None,
            extra_headers=(("Destination", destination),),
        )
        run_driver_load(
            WORKLOAD_TABLE["propfind-1-100"],
            server.port,
            1,
            duration=duration,
            count=None,
        )
    finally:
        server.stop()

    slow_lines: list[float] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _STALL_RE.search(line)
            if match:
                slow_lines.append(float(match.group(1)))
    worst = max(slow_lines, default=0.0)
    out_path = ctx.run_dir / f"stall-{interp.label}.json"
    out_path.write_text(
        json.dumps(
            {
                "interpreter": interp.label,
                "slow_callbacks": len(slow_lines),
                "worst_callback_s": worst,
                "verdict": "blocking calls suspected" if worst >= 0.1 else "clean",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    click.echo(
        f"  stall {interp.label}: {len(slow_lines)} slow callbacks, "
        f"worst {worst:.3f}s -> {out_path.name}"
    )
