"""Tests for tools.perf.baseline: repo-store promote and dual-store resolution."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from tools.common.error import ToolError
from tools.perf import baseline as baseline_mod
from tools.perf.baseline import (
    REPO_BASELINE_NAME,
    list_all_baselines,
    promote_baseline,
    resolve_baseline_dir,
    save_baseline,
)
from tools.perf.bench import BenchSample
from tools.perf.settings import Settings
from tools.perf.summary import load_summary

FAKE_PROJECT: dict[str, Any] = {
    "project_version": "2.0.2",
    "git_commit": "0" * 40,
    "git_dirty": False,
    "git_describe": "v2.0.2",
}


def _sample(workload: str, rps: float) -> BenchSample:
    return BenchSample(
        interpreter="py315",
        variant="base",
        workload=workload,
        concurrency=1,
        rps=rps,
        lat_ms_p50=1.0,
        lat_ms_p99=2.0,
        requests=100,
        errors=0,
        duration=10.0,
        server_cpu_s=1.5,
        loadgen="driver",
    )


def _make_run(root: Path, *, marker: str, rps: float) -> Path:
    """A fake run dir: promotable data files plus the decoys to exclude."""
    run_dir = root / f"run-{marker}"
    compat = run_dir / "compat"
    compat.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {"schema_version": 1, "samples": [_sample("get-4k", rps).to_dict()]}
        ),
        encoding="utf-8",
    )
    (run_dir / "meta.json").write_text(
        json.dumps(
            {"schema_version": 1, "platform": "darwin", "project": FAKE_PROJECT}
        ),
        encoding="utf-8",
    )
    (run_dir / f"stall-{marker}.json").write_text(
        json.dumps({"interpreter": "py315", "slow_callbacks": 0}),
        encoding="utf-8",
    )
    (compat / "py315.json").write_text(
        json.dumps({"probe": {}, "pytest": {"passed": 297, "failed": 0}}),
        encoding="utf-8",
    )
    # decoys: rendered markdown, regenerable config, server log
    (run_dir / "summary.md").write_text("# summary", encoding="utf-8")
    (compat / "summary.md").write_text("# compat", encoding="utf-8")
    (compat / "compat-config-py315.toml").write_text("[x]\n", encoding="utf-8")
    (compat / "compat-server-py315.log").write_text("log" * 100, encoding="utf-8")
    return run_dir


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Redirect both stores into tmp_path and pin the project fingerprint."""
    settings = dataclasses.replace(Settings.load(), log_dir=tmp_path / "output")
    monkeypatch.setattr(
        baseline_mod, "repo_baselines_root", lambda: tmp_path / "repo-baselines"
    )
    monkeypatch.setattr(
        baseline_mod, "_collect_project_info", lambda: dict(FAKE_PROJECT)
    )
    return settings


def _repo_current(env: Settings) -> Path:
    return baseline_mod.repo_baselines_root() / REPO_BASELINE_NAME


def _rel_files(target: Path) -> set[str]:
    return {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}


def test_promote_copies_data_only(env: Settings, tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, marker="a", rps=1234.5)
    target, old = promote_baseline(run_dir, force=False)
    assert old is None
    assert target == _repo_current(env)
    assert _rel_files(target) == {
        "baseline.json",
        "meta.json",
        "summary.json",
        "stall/stall-a.json",
        "compat/py315.json",
    }
    manifest = json.loads((target / "baseline.json").read_text(encoding="utf-8"))
    assert manifest["name"] == REPO_BASELINE_NAME
    assert manifest["source_run"] == str(run_dir)
    assert manifest["project"] == FAKE_PROJECT
    assert manifest["samples_count"] == 1


def test_promote_writes_canonical_json(env: Settings, tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, marker="a", rps=1234.5)
    target, _ = promote_baseline(run_dir, force=False)
    for path in sorted(target.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    # the round-trip preserves the measurement data
    samples = load_summary(target)
    assert len(samples) == 1
    assert samples[0].rps == 1234.5


def test_promote_requires_summary(env: Settings, tmp_path: Path) -> None:
    bare_dir = tmp_path / "bare"
    bare_dir.mkdir()
    (bare_dir / "meta.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ToolError, match="no summary.json"):
        promote_baseline(bare_dir, force=False)
    assert not _repo_current(env).exists()


def test_promote_dirty_tree_gate(
    env: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run(tmp_path, marker="a", rps=1.0)
    dirty = dict(FAKE_PROJECT, git_dirty=True)
    monkeypatch.setattr(baseline_mod, "_collect_project_info", lambda: dict(dirty))
    with pytest.raises(ToolError, match="working tree is dirty"):
        promote_baseline(run_dir, force=False)
    assert not _repo_current(env).exists()
    target, _ = promote_baseline(run_dir, force=True)
    assert target.exists()


def test_promote_is_rolling(env: Settings, tmp_path: Path) -> None:
    promote_baseline(_make_run(tmp_path, marker="a", rps=1.0), force=False)
    target, old = promote_baseline(
        _make_run(tmp_path, marker="b", rps=2.0), force=False
    )
    assert old is not None
    assert _rel_files(target) == {
        "baseline.json",
        "meta.json",
        "summary.json",
        "stall/stall-b.json",
        "compat/py315.json",
    }
    assert load_summary(target)[0].rps == 2.0


def test_promote_chains_source_run(env: Settings, tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, marker="a", rps=1.0)
    saved, name = save_baseline(env, run_dir, "snap", force=True)
    assert name == "snap"
    target, _ = promote_baseline(saved, force=False)
    manifest = json.loads((target / "baseline.json").read_text(encoding="utf-8"))
    assert manifest["source_run"] == str(run_dir)


def test_resolve_baseline_prefers_repo(env: Settings, tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="unknown baseline"):
        resolve_baseline_dir(env, "current")
    promote_baseline(_make_run(tmp_path, marker="a", rps=1.0), force=False)
    save_baseline(env, _make_run(tmp_path, marker="b", rps=2.0), "current", force=True)
    resolved = resolve_baseline_dir(env, "current")
    assert resolved == _repo_current(env)
    # a non-colliding output-only name resolves to the output store
    save_baseline(env, _make_run(tmp_path, marker="c", rps=3.0), "other", force=True)
    assert resolve_baseline_dir(env, "other") == env.log_dir / "baselines" / "other"


def test_list_all_baselines_merges_origins(env: Settings, tmp_path: Path) -> None:
    promote_baseline(_make_run(tmp_path, marker="a", rps=1.0), force=False)
    save_baseline(env, _make_run(tmp_path, marker="b", rps=2.0), "current", force=True)
    save_baseline(env, _make_run(tmp_path, marker="c", rps=3.0), "other", force=True)
    entries = list_all_baselines(env)
    origins = [(str(e.get("origin")), str(e.get("name"))) for e in entries]
    # repo entry first; the colliding output 'current' is deduped away
    assert origins == [("repo", "current"), ("output", "other")]
