"""Click CLI for the perf tool (python -m tools.perf)."""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from tools.common.env import REPO_ROOT
from tools.common.error import ToolError
from tools.common.lima import vm_instance
from tools.common.proc import run_argv
from tools.perf.baseline import (
    REPO_BASELINE_NAME,
    baseline_dir,
    list_all_baselines,
    list_baselines,
    load_baseline_manifest,
    promote_baseline,
    remove_baseline,
    repo_baselines_root,
    resolve_baseline_dir,
    save_baseline,
    try_auto_save_baseline,
)
from tools.perf.bench import (
    BenchContext,
    BenchSample,
    run_bench_for_interpreter,
    run_stall_detection,
)
from tools.perf.compat import (
    collect_compat_entries,
    compat_pytest,
    compat_smoke,
    write_compat_summary,
)
from tools.perf.fixtures import ensure_fixtures
from tools.perf.interpreters import Interpreter, discover_interpreters
from tools.perf.loadgen import resolve_loadgen
from tools.perf.profile import run_profile
from tools.perf.settings import PROBE_TIMEOUT, Settings, scrub_child_env
from tools.perf.summary import (
    build_compare_report,
    collect_bench_samples,
    create_run_dir,
    load_or_init_meta,
    load_summary,
    render_compare_markdown,
    write_bench_summary,
    write_meta,
)
from tools.perf.trend import (
    collect_trend,
    render_trend_html,
    render_trend_markdown,
    render_trend_svg,
)
from tools.perf.vm import vm
from tools.perf.workloads import (
    DEFAULT_WORKLOADS,
    QUICK_WORKLOADS,
    WORKLOAD_TABLE,
    Workload,
)


@click.group()
def cli() -> None:
    """Performance and compatibility measurement for ASGI-WebDAV."""


@cli.command()
@click.option("-p", "--interpreter", "labels", multiple=True)
def preflight(labels: tuple[str, ...]) -> None:
    """Probe the matrix and print what would run vs be skipped."""
    settings = Settings.load()
    interpreters = discover_interpreters(settings, labels or None)
    click.echo(f"loadgen: {resolve_loadgen(settings, 'auto')}")
    for interp in interpreters:
        state = "READY" if interp.available else "SKIP"
        reason = f" ({interp.reason})" if interp.reason else ""
        jit = " jit" if interp.jit_build else ""
        ft = " ft" if interp.free_threaded else ""
        sampling = ""
        if interp.available and interp.profiling_pkg:
            sampling = (
                ""
                if _tachyon_run_ok(interp)
                else "  sampling=DENIED (flamegraphs via lima)"
            )
        click.echo(
            f"  [{state}] {interp.label:8s} {interp.version:10s}{ft}{jit}"
            f"{sampling}{reason}"
        )
    found = vm_instance(settings.vm_name, timeout=PROBE_TIMEOUT)
    click.echo(f"  vm {settings.vm_name}: {found[1] if found else 'not created'}")


def _tachyon_run_ok(interp: Interpreter) -> bool:
    """One-second Tachyon run against a sleep child: permission smoke."""
    result = run_argv(
        [
            str(interp.path),
            "-m",
            "profiling.sampling",
            "run",
            "-d",
            "1",
            "-c",
            "pass",
        ],
        timeout=30.0,
    )
    return result.returncode == 0 and "Permission Error" not in result.stdout


@cli.command()
@click.option("--recreate", is_flag=True, default=False)
def fixtures(recreate: bool) -> None:
    """Generate the benchmark fixture tree."""
    settings = Settings.load()
    fs_dir = ensure_fixtures(settings.fixtures_dir, recreate=recreate)
    click.echo(f"fixtures ready: {fs_dir}")


@cli.command()
@click.option("-p", "--interpreter", "labels", multiple=True)
@click.option("-w", "--workload", "workload_names", multiple=True)
@click.option("-c", "--concurrency", "concs", multiple=True, type=int)
@click.option("-v", "--variant", "variants", multiple=True)
@click.option("--repeat", "repeats", type=int, default=None)
@click.option("--duration", type=float, default=None)
@click.option("--loadgen", type=click.Choice(["auto", "oha", "driver"]), default="auto")
@click.option("--quick", is_flag=True, default=False)
@click.option(
    "--stall", is_flag=True, default=False, help="asyncio-debug stall detection"
)
@click.option("--run-dir", default=None)
def bench(
    labels: tuple[str, ...],
    workload_names: tuple[str, ...],
    concs: tuple[int, ...],
    variants: tuple[str, ...],
    repeats: int | None,
    duration: float | None,
    loadgen: str,
    quick: bool,
    stall: bool,
    run_dir: str | None,
) -> None:
    """Run the HTTP throughput matrix."""
    settings = Settings.load()
    ensure_fixtures(settings.fixtures_dir)
    the_run_dir = create_run_dir(settings, run_dir)
    the_run_dir.mkdir(parents=True, exist_ok=True)
    the_duration = (
        2.0 if quick else (duration if duration is not None else settings.duration)
    )
    the_repeats = 1 if quick else (repeats if repeats is not None else settings.repeats)
    the_warmup = 0 if quick else settings.warmup
    the_concs = concs or ((1,) if quick else settings.concurrencies)
    the_variants = variants or ("base",)
    chosen_names = workload_names or (QUICK_WORKLOADS if quick else DEFAULT_WORKLOADS)
    the_workloads: list[Workload] = []
    for name in chosen_names:
        workload = WORKLOAD_TABLE.get(name)
        if workload is None:
            raise ToolError(f"unknown workload {name!r}")
        the_workloads.append(workload)
    the_labels = labels or ("py314", "py315")
    interpreters = discover_interpreters(settings, the_labels)
    loadgen_resolved = resolve_loadgen(settings, loadgen)
    ctx = BenchContext(
        settings=settings,
        run_dir=the_run_dir,
        loadgen=loadgen_resolved,
        samples=[],
    )

    write_meta(the_run_dir, settings, interpreters)
    click.echo(f"run dir: {the_run_dir}  loadgen: {loadgen_resolved}")

    for interp in interpreters:
        if not interp.available:
            click.echo(f"skip {interp.label}: {interp.reason}")
            continue
        click.echo(f"bench {interp.label} ({interp.version})")
        run_bench_for_interpreter(
            ctx,
            interp,
            the_variants,
            the_workloads,
            the_concs,
            duration=the_duration,
            repeats=the_repeats,
            warmup=the_warmup,
        )
        if stall:
            run_stall_detection(ctx, interp, duration=the_duration)

    all_samples = collect_bench_samples(the_run_dir)
    write_bench_summary(the_run_dir, all_samples)
    click.echo(f"summary: {the_run_dir / 'summary.md'}")


@cli.command()
@click.option("-p", "--interpreter", "labels", multiple=True)
@click.option("--quick", is_flag=True, default=False)
@click.option("--run-dir", default=None)
@click.pass_context
def compat(
    ctx: click.Context, labels: tuple[str, ...], quick: bool, run_dir: str | None
) -> int:
    """Compatibility check: pytest suite + smoke load + env collection."""
    settings = Settings.load()
    ensure_fixtures(settings.fixtures_dir)
    the_run_dir = create_run_dir(settings, run_dir)
    the_run_dir.mkdir(parents=True, exist_ok=True)
    interpreters = discover_interpreters(settings, labels or None)
    bench_ctx = BenchContext(
        settings=settings, run_dir=the_run_dir, loadgen="driver", samples=[]
    )
    load_or_init_meta(the_run_dir, settings)
    per_workload = 2.0 if quick else 5.0

    failures = 0
    for interp in interpreters:
        if not interp.available:
            click.echo(f"skip {interp.label}: {interp.reason}")
            (the_run_dir / "compat").mkdir(parents=True, exist_ok=True)
            (the_run_dir / "compat" / f"{interp.label}.json").write_text(
                json.dumps(
                    {"probe": interp.to_meta(), "skipped": interp.reason}, indent=2
                )
                + "\n",
                encoding="utf-8",
            )
            continue
        click.echo(f"compat {interp.label} ({interp.version})")
        pytest_result = compat_pytest(interp)
        smoke_result = compat_smoke(bench_ctx, interp, per_workload=per_workload)
        (the_run_dir / "compat").mkdir(parents=True, exist_ok=True)
        (the_run_dir / "compat" / f"{interp.label}.json").write_text(
            json.dumps(
                {
                    "probe": interp.to_meta(),
                    "pytest": pytest_result,
                    "smoke": smoke_result,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if pytest_result["exit_code"] != 0:
            failures += 1
    write_compat_summary(the_run_dir, collect_compat_entries(the_run_dir))
    click.echo(f"compat summary: {the_run_dir / 'compat' / 'summary.md'}")
    return failures


@cli.command()
@click.option("-p", "--interpreter", "label", required=True)
@click.option("-w", "--workload", "workload_name", default="propfind-1-100")
@click.option("--mode", type=click.Choice(["wall", "cpu", "gil"]), default="wall")
@click.option("--rate", "sampling_rate", default=None)
@click.option("--duration", type=float, default=None)
@click.option("--native/--no-native", default=True)
@click.option("--opcodes", is_flag=True, default=False)
@click.option("--async-aware/--no-async-aware", default=True)
@click.option("--run-dir", default=None)
def profile(
    label: str,
    workload_name: str,
    mode: str,
    sampling_rate: str | None,
    duration: float | None,
    native: bool,
    opcodes: bool,
    async_aware: bool,
    run_dir: str | None,
) -> None:
    """Sample-profile the server under load (Tachyon run mode)."""
    settings = Settings.load()
    ensure_fixtures(settings.fixtures_dir)
    the_run_dir = create_run_dir(settings, run_dir)
    the_run_dir.mkdir(parents=True, exist_ok=True)
    if sampling_rate:
        settings = dataclasses.replace(settings, sampling_rate=sampling_rate)
    if duration is not None:
        settings = dataclasses.replace(settings, profile_duration=duration)
    interp = discover_interpreters(settings, (label,))[0]
    if not interp.available:
        raise ToolError(f"interpreter unavailable: {interp.reason}")
    workload = WORKLOAD_TABLE.get(workload_name)
    if workload is None:
        raise ToolError(f"unknown workload {workload_name!r}")
    load_or_init_meta(the_run_dir, settings)
    run_profile(
        settings,
        the_run_dir,
        interp,
        workload,
        mode=mode,
        duration=settings.profile_duration,
        native=native,
        opcodes=opcodes,
        async_aware=async_aware,
    )


@cli.command()
@click.option("-p", "--interpreter", "labels", multiple=True)
@click.option("--trace", is_flag=True, default=False)
@click.option("--run-dir", default=None)
def micro(labels: tuple[str, ...], trace: bool, run_dir: str | None) -> None:
    """Micro-benchmarks (timeit) under each target interpreter."""
    settings = Settings.load()
    the_run_dir = create_run_dir(settings, run_dir)
    (the_run_dir / "micro").mkdir(parents=True, exist_ok=True)
    interpreters = discover_interpreters(settings, labels or None)
    write_meta(the_run_dir, settings, interpreters)
    argv_tail = ["-m", "tools.perf.tasks.micro", "--json"]
    if trace:
        argv_tail.append("--trace")
    for interp in interpreters:
        if not interp.available:
            click.echo(f"skip {interp.label}: {interp.reason}")
            continue
        result = run_argv(
            [str(interp.path), *argv_tail],
            timeout=900.0,
            cwd=REPO_ROOT,
            env=scrub_child_env(),
        )
        out_path = the_run_dir / "micro" / f"{interp.label}.json"
        out_path.write_text(result.stdout, encoding="utf-8")
        click.echo(f"micro {interp.label}: exit {result.returncode} -> {out_path}")


@cli.command()
@click.option("-p", "--interpreter", "labels", multiple=True)
@click.option("--requests", "requests_n", type=int, default=1000)
@click.option("--workload", "workload", default="all")
@click.option("--cprofile", "cprofile_flag", is_flag=True, default=False)
@click.option("--run-dir", default=None)
def inproc(
    labels: tuple[str, ...],
    requests_n: int,
    workload: str,
    cprofile_flag: bool,
    run_dir: str | None,
) -> None:
    """In-process ASGI cost (no network) under each target interpreter."""
    settings = Settings.load()
    ensure_fixtures(settings.fixtures_dir)
    the_run_dir = create_run_dir(settings, run_dir)
    (the_run_dir / "inproc").mkdir(parents=True, exist_ok=True)
    interpreters = discover_interpreters(settings, labels or None)
    write_meta(the_run_dir, settings, interpreters)
    for interp in interpreters:
        if not interp.available:
            click.echo(f"skip {interp.label}: {interp.reason}")
            continue
        argv_tail = [
            "-m",
            "tools.perf.tasks.inproc",
            "--requests",
            str(requests_n),
            "--workload",
            workload,
            "--fs-dir",
            str(settings.fixtures_dir / "fs"),
            "--json",
        ]
        out_path = the_run_dir / "inproc" / f"{interp.label}.json"
        if cprofile_flag:
            argv_tail += ["--cprofile-out", str(out_path.with_suffix(".pstats"))]
        result = run_argv(
            [str(interp.path), *argv_tail],
            timeout=1800.0,
            cwd=REPO_ROOT,
            env=scrub_child_env(),
        )
        out_path.write_text(
            result.stdout if result.returncode == 0 else result.stdout[-2000:],
            encoding="utf-8",
        )
        click.echo(f"inproc {interp.label}: exit {result.returncode} -> {out_path}")


@cli.command()
@click.argument("run_dir_a", type=click.Path(exists=True), required=False)
@click.argument("run_dir_b", type=click.Path(exists=True), required=False)
@click.option(
    "--metric", type=click.Choice(["rps", "p99", "cpu_per_req"]), default="rps"
)
@click.option("--highlight-threshold", type=float, default=0.10)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
)
@click.option("--fail-threshold", type=float, default=None)
@click.option(
    "--baseline",
    "baseline_name",
    default=None,
    help="Resolve RUN_DIR_A as a named baseline (A=old, B=current).",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write the comparison report here (default: <RUN_DIR_B>/compare-report.*).",
)
def compare(
    run_dir_a: str,
    run_dir_b: str,
    metric: str,
    highlight_threshold: float,
    output_format: str,
    fail_threshold: float | None,
    baseline_name: str | None,
    output_path: str | None,
) -> None:
    """Compare a run against another run or a named baseline.

    Forms: compare RUN_A RUN_B  |  compare --baseline NAME RUN_B  |
    compare RUN_B (A defaults to the repo baseline 'current').
    """
    if baseline_name is not None:
        if run_dir_a is not None and run_dir_b is not None:
            raise click.UsageError(
                "pass either RUN_A RUN_B or --baseline NAME RUN_B, not all three"
            )
        if run_dir_b is None:
            if run_dir_a is None:
                raise click.UsageError(
                    "--baseline NAME requires the RUN_DIR_B positional"
                )
            run_dir_b = run_dir_a
        settings = Settings.load()
        run_dir_a = str(resolve_baseline_dir(settings, baseline_name))
    elif run_dir_b is None:
        if run_dir_a is None:
            raise click.UsageError(
                "provide RUN_DIR_A and RUN_DIR_B, a single RUN_DIR_B (compared "
                "against the repo baseline), or --baseline NAME RUN_B"
            )
        # single positional: A defaults to the repo's rolling baseline
        run_dir_b = run_dir_a
        run_dir_a = str(resolve_baseline_dir(Settings.load(), REPO_BASELINE_NAME))
    path_a = Path(run_dir_a)
    path_b = Path(run_dir_b)
    # the repo store stays data-only: never archive reports into it
    if output_path is None and path_b.resolve().is_relative_to(
        repo_baselines_root().resolve()
    ):
        raise click.UsageError(
            "--output is required when RUN_DIR_B is the repo baseline"
        )
    samples_a = {s.key: s for s in load_summary(path_a)}
    samples_b = {s.key: s for s in load_summary(path_b)}
    shared = sorted(set(samples_a) & set(samples_b))
    if not shared:
        raise click.UsageError(
            "no shared result keys between the two runs; nothing to compare"
        )

    def metric_value(sample: BenchSample) -> float:
        if metric == "rps":
            return sample.rps
        if metric == "p99":
            return sample.lat_ms_p99
        requests = sample.requests or 1
        return sample.server_cpu_s / requests * 1000.0

    rows: list[dict[str, Any]] = []
    for key in shared:
        value_a = metric_value(samples_a[key])
        value_b = metric_value(samples_b[key])
        ratio = value_b / value_a if value_a else 0.0
        rows.append(
            {
                "key": {
                    "interpreter": key[0],
                    "variant": key[1],
                    "workload": key[2],
                    "concurrency": key[3],
                },
                "a": round(value_a, 3),
                "b": round(value_b, 3),
                "ratio_b_over_a": round(ratio, 4),
            }
        )
    report = build_compare_report(
        path_a,
        path_b,
        metric=metric,
        rows=rows,
        highlight_threshold=highlight_threshold,
        fail_threshold=fail_threshold,
    )

    # archive the report: explicit --output wins, otherwise store both
    # formats next to the "current" (B) run
    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "json":
            out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        else:
            out.write_text(render_compare_markdown(report), encoding="utf-8")
        click.echo(f"report written: {out}")
    else:
        path_b.mkdir(parents=True, exist_ok=True)
        (path_b / "compare-report.md").write_text(
            render_compare_markdown(report), encoding="utf-8"
        )
        (path_b / "compare-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        click.echo(f"report written: {path_b / 'compare-report.md'}")

    # the fail gate is direction-aware: a big IMPROVEMENT must not fail CI
    improves_with_higher = {"rps": True, "p99": False, "cpu_per_req": False}[metric]
    exceeded = False
    for row in rows:
        row["verdict"] = "flat"
        ratio = row["ratio_b_over_a"]
        if abs(ratio - 1.0) > highlight_threshold:
            row["verdict"] = (
                "improved" if (ratio > 1.0) == improves_with_higher else "regressed"
            )
        if fail_threshold is not None and row["verdict"] == "regressed":
            exceeded = True
            row["verdict"] += " FAIL"

    if output_format == "json":
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo("| key | A | B | B/A | verdict |")
        click.echo("|---|---:|---:|---:|---|")
        for row in rows:
            ratio = row["ratio_b_over_a"]
            flag = " (diff)" if row["verdict"] != "flat" else ""
            key_info = row["key"]
            name = (
                f"{key_info['interpreter']}/{key_info['variant']}/"
                f"{key_info['workload']}/c{key_info['concurrency']}"
            )
            verdict = row["verdict"]
            click.echo(
                f"| {name} | {row['a']} | {row['b']} | {ratio} | {verdict}{flag} |"
            )
        click.echo(
            "\ncompare across runs is only meaningful with identical load "
            "and machine state"
        )
    if fail_threshold is not None and exceeded:
        sys.exit(1)


@cli.command()
@click.option("--quick", is_flag=True, default=False)
@click.option("--run-dir", default=None)
@click.pass_context
def run(ctx: click.Context, quick: bool, run_dir: str | None) -> None:
    """One-shot macOS campaign: compat -> bench -> micro -> inproc -> profile."""
    settings = Settings.load()
    the_run_dir = create_run_dir(settings, run_dir)
    the_run_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"campaign run dir: {the_run_dir}")
    compat_labels: tuple[str, ...] = ("py315",) if quick else ()
    compat_failures = ctx.invoke(
        compat, labels=compat_labels, quick=quick, run_dir=str(the_run_dir)
    )
    ctx.invoke(
        bench,
        labels=("py315",) if quick else (),
        workload_names=(),
        concs=(),
        variants=(),
        repeats=None,
        duration=None,
        loadgen="auto",
        quick=quick,
        stall=not quick,
        run_dir=str(the_run_dir),
    )
    ctx.invoke(micro, labels=compat_labels, trace=False, run_dir=str(the_run_dir))
    ctx.invoke(
        inproc,
        labels=compat_labels,
        requests_n=1000,
        workload="all",
        cprofile_flag=False,
        run_dir=str(the_run_dir),
    )
    if not quick:
        try:
            ctx.invoke(
                profile,
                label="py315",
                workload_name="propfind-1-1000",
                mode="wall",
                sampling_rate=None,
                duration=None,
                native=True,
                opcodes=False,
                async_aware=True,
                run_dir=str(the_run_dir),
            )
        except ToolError as e:
            # zero-intervention degradation: macOS sampling permission can be
            # denied; flame graphs are then produced on the lima leg instead
            click.echo(f"profile skipped (degraded): {e}")
    click.echo(f"campaign complete: {the_run_dir}")
    try_auto_save_baseline(the_run_dir)
    if compat_failures:
        sys.exit(f"campaign finished with {compat_failures} compat failure(s)")


# ---------------------------------------------------------------------------
# vm group (independent, deletable module for the Linux leg)


def main() -> int:
    try:
        cli(standalone_mode=False)
    except ToolError as e:
        click.echo(f"tool error: {e}", err=True)
        return 2
    except click.exceptions.Abort:
        return 130
    except click.exceptions.UsageError as e:
        click.echo(f"usage: {e}", err=True)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


cli.add_command(vm)

# ---------------------------------------------------------------------------
# baseline: named snapshots of a run for cross-version comparison


@cli.group()
def baseline() -> None:
    """Manage named performance baselines for cross-version comparison."""


@baseline.command("save")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--name",
    default=None,
    metavar="NAME",
    help="Baseline name (default: <version>-<timestamp>-<short git hash>).",
)
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite existing baseline."
)
def baseline_save(run_dir: str, name: str | None, force: bool) -> None:
    """Save a run's summary as a named baseline."""
    settings = Settings.load()
    target, resolved = save_baseline(settings, Path(run_dir), name, force=force)
    click.echo(f"baseline saved: {resolved!r} -> {target}")


def _resolve_promote_source(source: str, settings: Settings) -> Path:
    """SOURCE order: existing run/baseline dir with summary.json, then an
    output-baseline name (a saved baseline dir has the same top-level
    layout, so both shapes share the filter-copy code path)."""
    source_path = Path(source)
    if (source_path / "summary.json").exists():
        return source_path
    output_candidate = baseline_dir(settings, source)
    if (output_candidate / "baseline.json").exists():
        return output_candidate
    known = (
        ", ".join(str(entry.get("name")) for entry in list_baselines(settings))
        or "(none)"
    )
    raise click.UsageError(
        f"cannot promote {source!r}: no such run dir or output baseline "
        f"(known baselines: {known})"
    )


@baseline.command("promote")
@click.argument("source", metavar="SOURCE")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Promote even when the git working tree is dirty.",
)
def baseline_promote(source: str, force: bool) -> None:
    """Promote a run (or saved baseline) into the repo baseline store.

    SOURCE is a run-dir path, a saved-baseline path, or an output-baseline
    name. The repo store keeps a single rolling entry 'current' with
    measurement data only; overwrite is normal, history lives in git.
    """
    settings = Settings.load()
    source_dir = _resolve_promote_source(source, settings)
    target, old_manifest = promote_baseline(source_dir, force=force)
    if old_manifest is not None:
        old_project = old_manifest.get("project") or {}
        click.echo(
            f"repo baseline replaced: {old_manifest.get('saved_at')} "
            f"({old_project.get('git_describe') or '?'})"
        )
    click.echo(f"repo baseline promoted: {target}")
    click.echo(
        "commit it to archive the snapshot: git add tools/perf/baselines && git commit"
    )


@baseline.command("list")
def baseline_list() -> None:
    """List saved baselines (repo store first, then the output store)."""
    settings = Settings.load()
    entries = list_all_baselines(settings)
    if not entries:
        click.echo("(no baselines)")
        return
    click.echo("| origin | name | saved at | version | git | samples |")
    click.echo("|---|---|---|---|---|---:|")
    for entry in entries:
        project = entry.get("project") or {}
        click.echo(
            f"| {entry.get('origin')} | {entry.get('name')} | {entry.get('saved_at')} "
            f"| {project.get('project_version') or '?'} "
            f"| {project.get('git_describe') or '?'} "
            f"| {entry.get('samples_count')} |"
        )


@baseline.command("show")
@click.argument("name")
def baseline_show(name: str) -> None:
    """Show a baseline's identity and its summary table."""
    settings = Settings.load()
    baseline_path = resolve_baseline_dir(settings, name)
    manifest = load_baseline_manifest(settings, name)
    click.echo(json.dumps(manifest, indent=2))
    summary_md = baseline_path / "summary.md"
    if summary_md.exists():
        click.echo()
        click.echo(summary_md.read_text(encoding="utf-8"))
    else:
        # repo-store entries carry data only
        click.echo()
        click.echo(
            "(no summary.md — this baseline stores data only; "
            "use compare or see the source run)"
        )


@baseline.command("remove")
@click.argument("name")
@click.option(
    "--yes", is_flag=True, default=False, help="Skip the confirmation prompt."
)
def baseline_remove(name: str, yes: bool) -> None:
    """Delete a named baseline."""
    settings = Settings.load()
    baseline_path = resolve_baseline_dir(settings, name)
    if baseline_path.resolve().is_relative_to(repo_baselines_root().resolve()):
        raise ToolError(
            f"baseline {name!r} lives in the repo store "
            f"({repo_baselines_root()}); remove it with git"
        )
    if not yes:
        click.confirm(f"Delete baseline {name!r}?", abort=True)
    remove_baseline(settings, name)
    click.echo(f"baseline removed: {name!r}")


@baseline.command("plot")
@click.option(
    "--metric", type=click.Choice(["rps", "p99", "cpu_per_req"]), default="rps"
)
@click.option("-p", "--interpreter", "interpreter_filter", multiple=True)
@click.option("-w", "--workload", "workload_filter", multiple=True)
@click.option("-c", "--concurrency", "concs", multiple=True, type=int)
@click.option(
    "--output",
    "output_base",
    default=None,
    metavar="PATH",
    help="Output base name (default: output/perf/trend-<timestamp>; writes .html/.svg/.md).",
)
def baseline_plot(
    metric: str,
    interpreter_filter: tuple[str, ...],
    workload_filter: tuple[str, ...],
    concs: tuple[int, ...],
    output_base: str | None,
) -> None:
    """Plot the performance trend across ALL saved baselines."""
    settings = Settings.load()
    trend = collect_trend(
        settings,
        metric=metric,
        interpreter_filter=interpreter_filter,
        workload_filter=workload_filter,
        concs=concs,
    )
    if output_base:
        base = Path(output_base)
        if not base.is_absolute():
            base = REPO_ROOT / base
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = settings.log_dir / "trend" / f"trend-{stamp}"
    base.parent.mkdir(parents=True, exist_ok=True)

    svg = render_trend_svg(trend)
    (base.with_suffix(".svg")).write_text(svg, encoding="utf-8")
    base.with_suffix(".html").write_text(
        render_trend_html(trend, svg), encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render_trend_markdown(trend), encoding="utf-8")
    for suffix in (".html", ".svg", ".md"):
        click.echo(f"trend written: {base.with_suffix(suffix)}")


cli.add_command(baseline)
