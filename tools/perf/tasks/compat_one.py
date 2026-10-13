"""Run the compat suite for ONE interpreter inside the lima VM.

Invoked by the ``vm compat`` shell script under the target venv python::

    python -m tools.perf.tasks.compat_one venv-py315t py315t-lima [--quick]

Reuses the host-side helpers (probe / pytest / smoke) from the perf package;
results land in ``vm-results/compat/<label>.json`` and are fetched back by
the CLI and merged into the run dir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.perf.bench import BenchContext
from tools.perf.compat import compat_pytest, compat_smoke
from tools.perf.interpreters import probe_interpreter
from tools.perf.settings import Settings


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m tools.perf.tasks.compat_one VENV_NAME LABEL [--quick]")
        return 2
    label = argv[2]
    quick = "--quick" in argv[3:]

    settings = Settings.load()
    interp = probe_interpreter(label, sys.executable)
    results: dict[str, object] = {"probe": interp.to_meta()}
    if not interp.available:
        results["skipped"] = interp.reason
    else:
        results["pytest"] = compat_pytest(interp)
        bench_ctx = BenchContext(
            settings=settings,
            run_dir=Path("vm-results/compat"),
            loadgen="driver",
            samples=[],
        )
        results["smoke"] = compat_smoke(
            bench_ctx, interp, per_workload=2.0 if quick else 5.0
        )

    out_dir = Path("vm-results/compat")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{label}.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(f"compat_one wrote {out_dir / f'{label}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
