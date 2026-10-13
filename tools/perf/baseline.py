"""Named baselines: archivable snapshots of a run for cross-version comparison.

Two stores exist:

- **Output store** (working set): ``<log_dir>/baselines/<name>/`` — timestamped
  auto-save snapshots plus manually named ones; feeds ``baseline plot`` trends.
- **Repo store** (committed archive): ``<package>/baselines/current/`` — a
  single rolling entry promoted manually via ``baseline promote``; measurement
  data only (JSON), history lives in git.

Typical workflow::

    python -m tools.perf baseline save output/perf/run-A --name pre-opt
    # ... apply the optimization, re-run the campaign ...
    python -m tools.perf compare --baseline pre-opt output/perf/run-B --output report.md
    # ... archive the new reference point in the repo ...
    python -m tools.perf baseline promote output/perf/run-B
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from tools.common.error import ToolError
from tools.perf.settings import Settings
from tools.perf.summary import (
    SCHEMA_VERSION,
    _collect_project_info,
    collect_bench_samples,
    load_summary,
    write_canonical_json,
)

# archivable artifacts copied into a baseline (lightweight JSON/markdown only)
_BASELINE_FILES = ("meta.json", "summary.json", "summary.md")

# repo store: one rolling entry, overwritten on every promote
REPO_BASELINE_NAME = "current"


def repo_baselines_root() -> Path:
    """Repo-committed baseline store root (next to the tool code).

    A repo-structure fact, deliberately NOT a TOOLS_PERF_* setting: machines
    must not diverge from what is committed, and the path must not depend on
    the environment or cwd.
    """
    return Path(__file__).resolve().parent / "baselines"


def auto_baseline_name() -> str:
    """Default baseline name: ``<version>-<timestamp>-<short git hash>``."""
    project = _collect_project_info()
    version = str(project.get("project_version") or "noversion")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    short_hash = str(project.get("git_describe") or "nogit")
    # git_describe may carry "-dirty"/distance suffixes; keep only the hash
    short_hash = short_hash.split("-g")[-1].replace("-dirty", "") or "nogit"
    return f"{version}-{stamp}-{short_hash}"


def baselines_root(settings: Settings) -> Path:
    return Path(settings.log_dir) / "baselines"


def baseline_dir(settings: Settings, name: str) -> Path:
    return baselines_root(settings) / name


def save_baseline(
    settings: Settings, run_dir: Path, name: str | None = None, *, force: bool
) -> tuple[Path, str]:
    if name is None:
        name = auto_baseline_name()
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        msg = f"no summary.json under {run_dir}; nothing to save as baseline"
        raise ToolError(msg)
    target = baseline_dir(settings, name)
    if target.exists():
        if not force:
            msg = f"baseline {name!r} already exists at {target}; use --force to overwrite"
            raise ToolError(msg)
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for item_name in _BASELINE_FILES:
        source = run_dir / item_name
        if source.exists():
            shutil.copy2(source, target / item_name)
    stall_dir = target / "stall"
    stall_dir.mkdir(exist_ok=True)
    for source in sorted(run_dir.glob("stall-*.json")):
        shutil.copy2(source, stall_dir / source.name)
    compat_dir = target / "compat"
    compat_dir.mkdir(exist_ok=True)
    for source in (
        sorted((run_dir / "compat").glob("*")) if (run_dir / "compat").exists() else []
    ):
        if source.is_file():
            shutil.copy2(source, compat_dir / source.name)

    samples = collect_bench_samples(run_dir)
    manifest = {
        "schema_version": 1,
        "name": name,
        "source_run": str(run_dir),
        # timezone-aware system-local time (e.g. 2026-10-11T18:03:10+08:00)
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project": _collect_project_info(),
        "samples_count": len(samples),
    }
    (target / "baseline.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return target, name


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        msg = f"unreadable {path}: {e}"
        raise ToolError(msg) from e


def promote_baseline(
    source_dir: Path, *, force: bool
) -> tuple[Path, dict[str, Any] | None]:
    """Filter-copy a run (or saved baseline) into the rolling repo store.

    Only measurement data is committed (JSON artifacts); server logs, compat
    configs and rendered markdown are excluded. Every file is re-serialized
    canonically (sorted keys) so repeated promotes produce minimal git diffs.

    Returns the store entry path and the replaced entry's manifest (None
    when the store was empty).
    """
    if not (source_dir / "summary.json").exists():
        msg = f"no summary.json under {source_dir}; nothing to promote"
        raise ToolError(msg)
    project_now = _collect_project_info()
    if project_now.get("git_dirty") and not force:
        # one gate, two failure modes: an uncommitted previous promote would
        # be silently lost, and the snapshot could not be pinned to a commit
        msg = (
            "git working tree is dirty; commit (or discard) changes first, "
            "or pass --force"
        )
        raise ToolError(msg)

    target = repo_baselines_root() / REPO_BASELINE_NAME
    old_manifest: dict[str, Any] | None = None
    old_manifest_path = target / "baseline.json"
    if old_manifest_path.exists():
        try:
            old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old_manifest = None
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    source_meta_path = source_dir / "meta.json"
    if source_meta_path.exists():
        write_canonical_json(target / "meta.json", _load_json_file(source_meta_path))
    write_canonical_json(
        target / "summary.json", _load_json_file(source_dir / "summary.json")
    )
    for source in sorted(source_dir.glob("stall-*.json")):
        write_canonical_json(target / "stall" / source.name, _load_json_file(source))
    source_compat_dir = source_dir / "compat"
    if source_compat_dir.exists():
        # JSON only: excludes server logs, compat-config tomls and summary.md
        for source in sorted(source_compat_dir.glob("*.json")):
            write_canonical_json(
                target / "compat" / source.name, _load_json_file(source)
            )

    # the manifest keeps the fingerprint of the code that produced the
    # numbers (source meta / source manifest), never the promote-time state;
    # source_run is chained through when promoting an output baseline
    project: Any = None
    source_run = str(source_dir)
    source_manifest_path = source_dir / "baseline.json"
    if source_meta_path.exists():
        project = _load_json_file(source_meta_path).get("project")
    if source_manifest_path.exists():
        source_manifest = _load_json_file(source_manifest_path)
        source_run = str(source_manifest.get("source_run") or source_dir)
        if project is None:
            project = source_manifest.get("project")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": REPO_BASELINE_NAME,
        "source_run": source_run,
        # timezone-aware system-local time (e.g. 2026-10-13T12:00:00+08:00)
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project": project if project is not None else project_now,
        "samples_count": len(load_summary(source_dir)),
    }
    write_canonical_json(target / "baseline.json", manifest)
    return target, old_manifest


def load_baseline_manifest(settings: Settings, name: str) -> dict[str, Any]:
    manifest_path = resolve_baseline_dir(settings, name) / "baseline.json"
    data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data


def list_baselines(settings: Settings) -> list[dict[str, Any]]:
    root = baselines_root(settings)
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/baseline.json")):
        try:
            data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["name"] = manifest_path.parent.name
        entries.append(data)
    return entries


def remove_baseline(settings: Settings, name: str) -> None:
    # raises ToolError for unknown names
    load_baseline_manifest(settings, name)
    shutil.rmtree(baseline_dir(settings, name))


def resolve_baseline_dir(settings: Settings, name: str) -> Path:
    """Locate a baseline by name: the repo store first, then the output
    store. Raises ToolError listing known names (with origin) if unknown.
    """
    repo_candidate = repo_baselines_root() / name
    if (repo_candidate / "baseline.json").exists():
        return repo_candidate
    output_candidate = baseline_dir(settings, name)
    if (output_candidate / "baseline.json").exists():
        return output_candidate
    known = (
        ", ".join(
            f"{entry.get('name')} ({entry.get('origin')})"
            for entry in list_all_baselines(settings)
        )
        or "(none)"
    )
    msg = f"unknown baseline {name!r}; known baselines: {known}"
    raise ToolError(msg)


def list_all_baselines(settings: Settings) -> list[dict[str, Any]]:
    """Merge both stores for display; entries gain ``origin``: repo|output.

    The repo entry is listed first and wins on name collisions (matching
    resolve_baseline_dir). Trend/plot deliberately keeps using list_baselines
    (output only): the repo entry is a byte-copy of one output baseline, so
    including it would duplicate a trend point.
    """
    entries: list[dict[str, Any]] = []
    repo_manifest_path = repo_baselines_root() / REPO_BASELINE_NAME / "baseline.json"
    if repo_manifest_path.exists():
        try:
            data: dict[str, Any] = json.loads(
                repo_manifest_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            data = {}
        data["name"] = REPO_BASELINE_NAME
        data["origin"] = "repo"
        entries.append(data)
    repo_names = {str(entry.get("name")) for entry in entries}
    for entry in list_baselines(settings):
        if entry.get("name") in repo_names:
            continue
        entry["origin"] = "output"
        entries.append(entry)
    return entries


def try_auto_save_baseline(run_dir: Path) -> None:
    """Best-effort baseline snapshot after a full test activity.

    Failures are reported but never fail the measurement itself.
    """
    name = auto_baseline_name()
    try:
        target, name = save_baseline(Settings.load(), run_dir, name, force=False)
        click.echo(f"baseline saved: {name!r} -> {target}")
    except (ToolError, OSError, json.JSONDecodeError) as e:
        # a failed save may leave a directory without baseline.json; remove
        # it so the next attempt does not hit the collision error
        half = baseline_dir(Settings.load(), name)
        shutil.rmtree(half, ignore_errors=True)
        click.echo(f"baseline auto-save failed (non-fatal): {e}")
