"""Run the HTTP bench matrix for ONE interpreter inside the lima VM.

Invoked by the ``vm bench`` shell script under the target venv python::

    python -m tools.perf.tasks.bench_one venv-py315t py315t-lima [--quick]

For a JIT-enabled free-threaded build (label contains "tjit") an extra pass
with ``PYTHON_JIT=0`` is recorded under a ``-nojit`` label. Results land in
``vm-results/bench/`` as ``sample.json`` / ``raw-*.json`` files and are
fetched back by the CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.perf.bench import BenchContext, run_bench_for_interpreter
from tools.perf.fixtures import ensure_fixtures
from tools.perf.interpreters import probe_interpreter
from tools.perf.settings import Settings
from tools.perf.workloads import DEFAULT_WORKLOADS, QUICK_WORKLOADS, WORKLOAD_TABLE


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m tools.perf.tasks.bench_one VENV_NAME LABEL [--quick]")
        return 2
    label = argv[2]
    quick = "--quick" in argv[3:]

    settings = Settings.load()
    ensure_fixtures(settings.fixtures_dir)
    interp = probe_interpreter(label, sys.executable)
    if not interp.available:
        print(f"bench_one: interpreter probe failed: {interp.reason}")
        return 1

    # bench.py appends the "bench" segment itself — pass the root here
    run_dir = Path("vm-results")
    ctx = BenchContext(settings=settings, run_dir=run_dir, loadgen="driver", samples=[])
    workload_names = QUICK_WORKLOADS if quick else DEFAULT_WORKLOADS
    workloads = [WORKLOAD_TABLE[name] for name in workload_names]
    concurrencies: tuple[int, ...] = (1,) if quick else settings.concurrencies
    duration = 2.0 if quick else settings.duration
    repeats = 1 if quick else settings.repeats
    warmup = 0 if quick else settings.warmup
    run_bench_for_interpreter(
        ctx,
        interp,
        variants=("base",),
        workloads=workloads,
        concurrencies=concurrencies,
        duration=duration,
        repeats=repeats,
        warmup=warmup,
    )

    # FT+JIT A/B: same build with the JIT switched off at runtime
    if interp.free_threaded and interp.jit_build and not quick:
        nojit = probe_interpreter(
            f"{label}-nojit", sys.executable, env_extra={"PYTHON_JIT": "0"}
        )
        if nojit.available:
            run_bench_for_interpreter(
                ctx,
                nojit,
                variants=("base",),
                workloads=workloads,
                concurrencies=concurrencies,
                duration=duration,
                repeats=repeats,
                warmup=warmup,
            )
        else:
            print(f"vm_bench_one: nojit probe failed: {nojit.reason}")

    print(f"bench_one: {len(ctx.samples)} samples written under {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
