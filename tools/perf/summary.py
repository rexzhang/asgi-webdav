"""Run-dir layout, meta files, summary and compare-report serialization."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.common.env import REPO_ROOT
from tools.common.error import ToolError
from tools.perf.bench import BenchSample
from tools.perf.interpreters import Interpreter
from tools.perf.settings import Settings

SCHEMA_VERSION = 1


def _collect_project_info() -> dict[str, Any]:
    """Best-effort project identity: package version + git state.

    Every field degrades to None outside a git checkout (VM tarball copies,
    release archives) — meta writing must never fail because of this.
    """
    project_version: str | None
    try:
        from asgi_webdav import __version__

        project_version = str(__version__)
    except Exception:
        project_version = None

    def _git(argv: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *argv],
                cwd=str(REPO_ROOT),
                timeout=10,
                text=True,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    git_commit = _git(["rev-parse", "HEAD"])
    # distinguish "clean checkout" (rc 0, empty output) from "no git"
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            timeout=10,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        git_dirty = None
    else:
        git_dirty = (
            None if status_result.returncode != 0 else bool(status_result.stdout)
        )
    return {
        "project_version": project_version,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "git_describe": _git(["describe", "--always", "--dirty"]),
    }


def create_run_dir(settings: Settings, run_dir_opt: str | None) -> Path:
    if run_dir_opt:
        run_dir = Path(run_dir_opt)
        if not run_dir.is_absolute():
            run_dir = REPO_ROOT / run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir
    return settings.log_dir / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _build_meta(settings: Settings, interpreters: list[Interpreter]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        # timezone-aware local time (e.g. 2026-10-11T15:49:24+08:00)
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platform": sys.platform,
        "python_of_tool": sys.version.split()[0],
        "project": _collect_project_info(),
        "settings": {
            "loadgen": settings.loadgen,
            "duration": settings.duration,
            "repeats": settings.repeats,
            "warmup": settings.warmup,
            "concurrencies": list(settings.concurrencies),
        },
        "interpreters": [i.to_meta() for i in interpreters],
    }


def write_meta(
    run_dir: Path,
    settings: Settings,
    interpreters: list[Interpreter],
    extra: dict[str, Any] | None = None,
) -> None:
    meta = _build_meta(settings, interpreters)
    if extra:
        meta.update(extra)
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )


def load_or_init_meta(run_dir: Path, settings: Settings) -> dict[str, Any]:
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        return dict(json.loads(meta_path.read_text(encoding="utf-8")))
    meta = _build_meta(settings, [])
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def collect_bench_samples(run_dir: Path) -> list[BenchSample]:
    samples: list[BenchSample] = []
    for path in sorted((run_dir / "bench").rglob("sample*.json")):
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            samples.append(BenchSample.from_dict(data))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"warning: skipping unreadable sample {path}: {e}", file=sys.stderr)
    return samples


def write_bench_summary(run_dir: Path, samples: list[BenchSample]) -> None:
    summary = {
        "schema_version": SCHEMA_VERSION,
        "samples": [s.to_dict() for s in samples],
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "| interpreter | variant | workload | c | median rps | p99 ms | server cpu/sample | errors | unstable |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for sample in sorted(samples, key=lambda s: s.key):
        lines.append(
            f"| {sample.interpreter} | {sample.variant} | {sample.workload} "
            f"| {sample.concurrency} | {sample.rps:.1f} | {sample.lat_ms_p99:.2f} "
            f"| {sample.server_cpu_s:.3f} s | {sample.errors} "
            f"| {'yes' if sample.unstable else ''} |"
        )
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_summary(run_dir: Path) -> list[BenchSample]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        msg = f"no summary.json under {run_dir}; run the bench first"
        raise ToolError(msg)
    data: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    return [BenchSample.from_dict(item) for item in data["samples"]]


def write_canonical_json(path: Path, data: Any) -> None:
    """Stable serialization for committed artifacts (sorted keys, 2-space
    indent, trailing newline) — repeated promotes produce minimal git diffs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# compare reports (cross-version comparison, self-contained and archivable)

# metric direction: True when a higher value means better (rps), False when
# a lower value means better (p99, cpu_per_req)
METRIC_IMPROVES_WITH_HIGHER: dict[str, bool] = {
    "rps": True,
    "p99": False,
    "cpu_per_req": False,
}


def _load_meta_summary(run_dir: Path) -> dict[str, Any]:
    """Lightweight side description for compare reports (tolerant)."""
    meta_path = run_dir / "meta.json"
    side: dict[str, Any] = {"source": str(run_dir)}
    if not meta_path.exists():
        return side
    try:
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return side
    side["timestamp"] = meta.get("timestamp")
    side["platform"] = meta.get("platform")
    side["project"] = meta.get("project")
    settings = meta.get("settings")
    if isinstance(settings, dict):
        side["settings"] = {
            k: settings.get(k) for k in ("loadgen", "duration", "repeats", "warmup")
        }
    return side


def build_compare_report(
    run_dir_a: Path,
    run_dir_b: Path,
    *,
    metric: str,
    rows: list[dict[str, Any]],
    highlight_threshold: float,
    fail_threshold: float | None,
) -> dict[str, Any]:
    """Assemble the self-contained cross-version comparison report."""
    improves_with_higher = METRIC_IMPROVES_WITH_HIGHER[metric]
    improved = 0
    regressed = 0
    flat = 0
    for row in rows:
        ratio = row["ratio_b_over_a"]
        if abs(ratio - 1.0) <= highlight_threshold:
            flat += 1
        elif (ratio > 1.0) == improves_with_higher:
            improved += 1
        else:
            regressed += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "metric": metric,
        "thresholds": {
            "highlight": highlight_threshold,
            "fail": fail_threshold,
        },
        "a": _load_meta_summary(run_dir_a),
        "b": _load_meta_summary(run_dir_b),
        "rows": rows,
        "summary": {
            "improved": improved,
            "regressed": regressed,
            "flat": flat,
            "shared_keys": len(rows),
        },
    }


def render_compare_markdown(report: dict[str, Any]) -> str:
    """Render the report as a self-contained, archivable markdown file."""

    def _side_line(tag: str, side: dict[str, Any]) -> str:
        project = side.get("project") or {}
        identity = (
            f"v{project.get('project_version')}"
            if project.get("project_version")
            else "v?"
        )
        git = project.get("git_describe") or project.get("git_commit") or "(no git)"
        dirty = "+" if project.get("git_dirty") else ""
        return (
            f"- **{tag}**: {side.get('source')}  |  {identity} git:{git}{dirty}"
            f"  |  {side.get('timestamp') or '?'}  |  platform: {side.get('platform') or '?'}"
        )

    summary = report["summary"]
    threshold = report["thresholds"]["highlight"]
    lines = [
        "# Performance comparison report",
        "",
        f"- generated: {report['generated_at']}  |  metric: `{report['metric']}`"
        f"  |  highlight threshold: {threshold:.0%}",
        _side_line("A (baseline)", report["a"]),
        _side_line("B (current)", report["b"]),
        "",
        f"**B vs A: {summary['improved']} improved, "
        f"{summary['regressed']} regressed, {summary['flat']} flat "
        f"(of {summary['shared_keys']} shared keys)**",
        "",
        "| key | A | B | B/A | verdict |",
        "|---|---:|---:|---:|---|",
    ]
    improves_with_higher = METRIC_IMPROVES_WITH_HIGHER[report["metric"]]
    fail_threshold = report["thresholds"]["fail"]
    for row in report["rows"]:
        ratio = row["ratio_b_over_a"]
        if abs(ratio - 1.0) <= threshold:
            verdict = "flat"
        elif (ratio > 1.0) == improves_with_higher:
            verdict = "improved"
        else:
            verdict = "regressed"
        if fail_threshold is not None and abs(ratio - 1.0) > fail_threshold:
            verdict += " FAIL"
        key_info = row["key"]
        name = (
            f"{key_info['interpreter']}/{key_info['variant']}/"
            f"{key_info['workload']}/c{key_info['concurrency']}"
        )
        lines.append(f"| {name} | {row['a']} | {row['b']} | {ratio} | {verdict} |")
    if report["a"].get("platform") != report["b"].get("platform"):
        lines += [
            "",
            "> WARNING: the two sides were measured on different platforms — "
            "the comparison is indicative only.",
        ]
    lines += [
        "",
        "Comparison is only meaningful with identical load, fixtures and "
        "machine state.",
    ]
    return "\n".join(lines) + "\n"
