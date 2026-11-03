"""Python-version comparison charts for asgi-webdav from existing measurements.

"Version" means the execution-mode matrix {3.14, 3.15} x {gil, nogil,
nogil+jit}. Only part of the matrix was measured, so comparisons run on two
same-OS planes (never cross-OS):

- version axis (macOS): 3.14 gil vs 3.15 gil
- execution-mode axis (Linux/lima): 3.15 gil vs nogil vs nogil+jit

Reads (no new measurements, no repo code changes):
- bench samples: the repo baseline's summary.json (+ meta.json / compat/*.json
  for interpreter metadata; dependency versions from the venvs)
- a pinned-deps 3.14 retest run (version axis; falls back to the baseline
  when absent)
- micro benches: <micro-run-dir>/micro/{py314,py315}.json (panel omitted with
  a note when missing)

Writes per-metric svg files plus html/md/pdf under the output dir (default
``output/perf/report/py-versions/``). Rendering is stdlib-only SVG following
tools/perf/trend.py precedents; the pdf prints the svgs via headless Chrome
(best effort, skipped with a note when no Chrome/Chromium is found). Invoke:

    .venv/bin/python -m tools.perf py-versions
"""

from __future__ import annotations

import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.common.env import REPO_ROOT
from tools.perf.baseline import REPO_BASELINE_NAME, repo_baselines_root
from tools.perf.bench import BenchSample
from tools.perf.report import identity_from_meta
from tools.perf.summary import load_summary
from tools.perf.trend import (
    METRIC_IMPROVES_WITH_HIGHER,
    METRIC_LABEL,
    PALETTE,
    REPORT_CSS,
    metric_value,
)
from tools.perf.workloads import DEFAULT_WORKLOADS


@dataclass(frozen=True)
class PyVersionsInputs:
    """Input locations for the comparison charts (all defaultable)."""

    baseline_dir: Path
    # retest of the 3.14 leg with dependency versions pinned to the 3.15
    # venv's releases (uvloop 0.23.0 / httptools 0.9.0) — removes the
    # dependency confound; the py315 leg stays from the original campaign,
    # so the version axis is a cross-day comparison (disclosed in outputs)
    repin_run_dir: Path
    micro_run_dir: Path
    output_dir: Path


def default_inputs() -> PyVersionsInputs:
    return PyVersionsInputs(
        baseline_dir=repo_baselines_root() / REPO_BASELINE_NAME,
        repin_run_dir=REPO_ROOT / "output" / "perf" / "repin314",
        micro_run_dir=REPO_ROOT / "output" / "perf" / "run-20261013-141839",
        output_dir=REPO_ROOT / "output" / "perf" / "report" / "py-versions",
    )


METRICS: tuple[str, ...] = ("rps", "p99", "cpu_per_req")
SVG_STEM: dict[str, str] = {"rps": "rps", "p99": "p99", "cpu_per_req": "cpu"}

# version matrix: label -> (version-axis name, color); entity-stable hues
# validated for CVD (blue/red pair; red/orange/purple trio — green fails)
OLD_LABEL = "py314"  # 3.14 gil (macOS)
NEW_LABEL = "py315"  # 3.15 gil (macOS)
LIMA_FLAVORS: tuple[tuple[str, str], ...] = (
    ("py315-lima", "gil"),
    ("py315t-lima", "nogil"),
    ("py315tjit-lima", "nogil+jit"),
)
NOJIT_LABEL = "py315tjit-lima-nojit"

COLOR_314_GIL = PALETTE[0]  # #1f77b4
COLOR_315_GIL = PALETTE[1]  # #d62728 — same entity, same hue on both axes
COLOR_315_NOGIL = PALETTE[3]  # #ff7f0e
COLOR_315_NOGIL_JIT = PALETTE[4]  # #9467bd
COLOR_FASTER = PALETTE[2]  # micro: ratio < 1
COLOR_SLOWER = PALETTE[1]  # micro: ratio > 1
INK, INK_2, INK_3, GRID = "#333333", "#666666", "#999999", "#dddddd"

UNSTABLE_MARK = " *"
PANEL_W, PANEL_H = 430, 240
MARGIN_L, MARGIN_B = 62, 34
COLS = 3
MATRIX_NOTE = (
    "measured matrix — 3.14 gil: macOS only · 3.15 gil: macOS + Linux · "
    "3.15 nogil / nogil+jit: Linux only (macOS has no free-threaded build; "
    "3.14 nogil/jit never measured)"
)


@dataclass(frozen=True)
class Flavor:
    label: str
    short: str
    version: str


@dataclass(frozen=True)
class PairRow:
    old: BenchSample
    new: BenchSample


@dataclass(frozen=True)
class MicroBench:
    name: str
    old_us: float
    new_us: float

    @property
    def ratio(self) -> float:
        return self.new_us / self.old_us if self.old_us else 0.0


@dataclass(frozen=True)
class MicroData:
    old_version: str
    new_version: str
    benches: tuple[MicroBench, ...]


@dataclass(frozen=True)
class VersionsData:
    old_flavor: Flavor
    new_flavor: Flavor
    lima_version: str
    platform: str
    source: str
    pair_source: str
    pair_saved: str
    source_run: str
    saved_at: str
    project_line: str
    sample_total: int
    old_deps: str
    new_deps: str
    workloads: tuple[str, ...]
    concs: tuple[int, ...]
    pairs: dict[tuple[str, int], PairRow]
    lima: dict[tuple[str, int], dict[str, BenchSample]]
    micro: MicroData | None
    micro_note: str
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# metric helpers


def _fmt_value(metric: str, value: float) -> str:
    if metric == "rps":
        return f"{value:.1f}"
    if metric == "p99":
        return f"{value:.2f}"
    return f"{value:.3f}"


def _fmt_tick(value: float) -> str:
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _pair_ratio(pair: PairRow, metric: str) -> float:
    old = metric_value(pair.old, metric)
    return metric_value(pair.new, metric) / old if old else 0.0


def _headline(data: VersionsData, metric: str) -> str:
    """One-line 3.14-gil vs 3.15-gil aggregate for the version axis."""
    ratios = [_pair_ratio(p, metric) for p in data.pairs.values()]
    if not ratios:
        return ""
    median = statistics.median(ratios)
    higher_better = METRIC_IMPROVES_WITH_HIGHER[metric]
    better = (
        sum(r > 1.0 for r in ratios) if higher_better else sum(r < 1.0 for r in ratios)
    )
    return (
        f"median 3.15/3.14 = {median:.3f} — {better}/{len(ratios)} cells better "
        f"on 3.15, {len(ratios) - better} worse"
    )


# ---------------------------------------------------------------------------
# data loading


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _flavor_short(free_threaded: bool, jit_build: Any) -> str:
    if free_threaded and jit_build:
        return "nogil+jit"
    return "nogil" if free_threaded else "gil"


def _load_flavors(baseline_dir: Path) -> dict[str, Flavor]:
    """label -> flavor; meta.json interpreters first, compat probe fallback
    (the lima flavors only appear in the baseline's compat/*.json probes)."""
    flavors: dict[str, Flavor] = {}
    meta = _load_json(baseline_dir / "meta.json")
    for entry in meta.get("interpreters", []):
        label = str(entry.get("label") or "")
        flavors[label] = Flavor(
            label=label,
            short=_flavor_short(
                bool(entry.get("free_threaded")), entry.get("jit_build")
            ),
            version=str(entry.get("version") or ""),
        )
    for label, _ in LIMA_FLAVORS:
        if flavors.get(label) and flavors[label].version:
            continue
        probe = _load_json(baseline_dir / "compat" / f"{label}.json").get("probe", {})
        flavors[label] = Flavor(
            label=label,
            short=_flavor_short(
                bool(probe.get("free_threaded")), probe.get("jit_build")
            ),
            version=str(probe.get("version") or ""),
        )
    return flavors


def _dep_versions(python_path: str) -> str:
    """Read installed uvloop/httptools versions from the interpreter's venv.

    The baseline probes only record booleans; the actual package versions
    matter because the two macOS venvs are not pinned to the same releases.
    """
    py = Path(python_path)
    if not py.is_absolute():
        py = REPO_ROOT / py
    lib_root = py.parent.parent / "lib"
    uv = ht = "unknown"
    for dist in sorted(lib_root.glob("python3.*/site-packages/uvloop-*.dist-info")):
        uv = dist.name.removeprefix("uvloop-").removesuffix(".dist-info")
    for dist in sorted(lib_root.glob("python3.*/site-packages/httptools-*.dist-info")):
        ht = dist.name.removeprefix("httptools-").removesuffix(".dist-info")
    return f"uvloop {uv} / httptools {ht}"


def _load_micro(micro_run_dir: Path) -> tuple[MicroData | None, str]:
    paths = (
        micro_run_dir / "micro" / f"{OLD_LABEL}.json",
        micro_run_dir / "micro" / f"{NEW_LABEL}.json",
    )
    if not all(p.exists() for p in paths):
        return None, (
            f"micro panel omitted: no {OLD_LABEL}/{NEW_LABEL} micro json under "
            f"{micro_run_dir / 'micro'} (micro data is not copied into the baseline store)"
        )
    old = _load_json(paths[0])
    new = _load_json(paths[1])
    old_ops: dict[str, float] = old.get("bench_us_per_op", {})
    new_ops: dict[str, float] = new.get("bench_us_per_op", {})
    names = sorted(set(old_ops) & set(new_ops))
    benches = tuple(
        MicroBench(name=n, old_us=float(old_ops[n]), new_us=float(new_ops[n]))
        for n in names
    )
    return (
        MicroData(
            old_version=str(old.get("python") or ""),
            new_version=str(new.get("python") or ""),
            benches=benches,
        ),
        "",
    )


def collect(inputs: PyVersionsInputs) -> VersionsData:
    flavors = _load_flavors(inputs.baseline_dir)
    manifest = _load_json(inputs.baseline_dir / "baseline.json")
    meta = _load_json(inputs.baseline_dir / "meta.json")
    baseline_samples = load_summary(inputs.baseline_dir)

    # version-axis source: the pinned-deps 3.14 retest when present, else the
    # baseline itself; the mode axis always reads the baseline
    pair_samples = [
        s for s in baseline_samples if s.interpreter in (OLD_LABEL, NEW_LABEL)
    ]
    pair_source = str(inputs.baseline_dir.relative_to(REPO_ROOT))
    pair_saved = str(manifest.get("saved_at") or "")
    pair_meta = meta
    repin = (
        inputs.repin_run_dir.exists()
        and (inputs.repin_run_dir / "summary.json").exists()
    )
    if repin:
        pair_samples = load_summary(inputs.repin_run_dir)
        pair_source = str(inputs.repin_run_dir.relative_to(REPO_ROOT))
        pair_meta = _load_json(inputs.repin_run_dir / "meta.json")
        pair_saved = str(pair_meta.get("timestamp") or "")

    warnings: list[str] = []
    pair_cells: dict[tuple[str, int], dict[str, BenchSample]] = {}
    lima_cells: dict[tuple[str, int], dict[str, BenchSample]] = {}
    lima_labels = {label for label, _ in LIMA_FLAVORS}
    non_base = 0
    nojit = 0
    for s in baseline_samples:
        if s.interpreter in (OLD_LABEL, NEW_LABEL):
            if repin and s.interpreter == OLD_LABEL:
                continue  # 3.14 comes from the pinned-deps retest
            if s.variant != "base":
                non_base += 1
                continue
            pair_cells.setdefault((s.workload, s.concurrency), {})[s.interpreter] = s
            continue
        if s.variant != "base":
            non_base += 1
            continue
        if s.interpreter == NOJIT_LABEL:
            nojit += 1  # JIT A/B control leg — out of scope for this chart
            continue
        if s.interpreter in lima_labels:
            lima_cells.setdefault((s.workload, s.concurrency), {})[s.interpreter] = s
    # the retest run covers only the retested 3.14 leg
    for s in pair_samples:
        if s.interpreter != OLD_LABEL:
            continue
        if s.variant != "base":
            non_base += 1
            continue
        pair_cells.setdefault((s.workload, s.concurrency), {})[s.interpreter] = s
    if non_base:
        warnings.append(f"{non_base} non-base variant sample(s) ignored")
    if nojit:
        warnings.append(
            f"{nojit} {NOJIT_LABEL} sample(s) excluded (JIT on/off control; use compare)"
        )
    if repin:
        warnings.append(
            "version axis is a cross-day comparison: 3.14 retested with pinned "
            f"deps ({pair_source}, {pair_saved}) vs 3.15 from the "
            f"{manifest.get('saved_at')} campaign"
        )

    pairs: dict[tuple[str, int], PairRow] = {}
    for key, cell in pair_cells.items():
        if OLD_LABEL in cell and NEW_LABEL in cell:
            pairs[key] = PairRow(old=cell[OLD_LABEL], new=cell[NEW_LABEL])
    for key, cell in lima_cells.items():
        missing = lima_labels - set(cell)
        if missing:
            warnings.append(f"lima cell {key[0]} c{key[1]} missing {sorted(missing)}")

    concs = tuple(sorted({c for _, c in pairs}))
    present = {w for w, _ in pairs}
    workloads = tuple(w for w in DEFAULT_WORKLOADS if w in present)

    micro, micro_note = _load_micro(inputs.micro_run_dir)

    paths = {
        str(i.get("label")): str(i.get("path") or "")
        for i in pair_meta.get("interpreters", [])
    }
    project = manifest.get("project") or {}
    commit = str(project.get("git_commit") or "")[:7]
    platform = {"darwin": "macOS", "linux": "Linux"}.get(
        str(meta.get("platform")), str(meta.get("platform"))
    )
    old_path = paths.get(OLD_LABEL) or next(
        str(i.get("path") or "")
        for i in meta.get("interpreters", [])
        if str(i.get("label")) == OLD_LABEL
    )
    new_path = next(
        str(i.get("path") or "")
        for i in meta.get("interpreters", [])
        if str(i.get("label")) == NEW_LABEL
    )
    total = len(baseline_samples) + (len(pair_samples) if repin else 0)
    return VersionsData(
        old_flavor=flavors[OLD_LABEL],
        new_flavor=flavors[NEW_LABEL],
        lima_version=flavors[LIMA_FLAVORS[0][0]].version,
        platform=platform,
        source=str(inputs.baseline_dir.relative_to(REPO_ROOT)),
        pair_source=pair_source,
        pair_saved=pair_saved,
        source_run=str(manifest.get("source_run") or ""),
        saved_at=str(manifest.get("saved_at") or ""),
        project_line=f"{project.get('project_version')} @ {commit}",
        sample_total=total,
        old_deps=_dep_versions(old_path),
        new_deps=_dep_versions(new_path),
        workloads=workloads,
        concs=concs,
        pairs=pairs,
        lima=lima_cells,
        micro=micro,
        micro_note=micro_note,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# svg primitives (trend.py idioms: monospace, dashed grid, <title> tooltips)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bar_path(x: float, y_top: float, y_bottom: float, w: float) -> str:
    """Vertical bar, rounded top corners (data-end), flat baseline anchor."""
    h = y_bottom - y_top
    if h <= 0.5:
        return ""
    r = min(4.0, h / 2, w / 2)
    return (
        f"M{x:.1f},{y_bottom:.1f} L{x:.1f},{y_top + r:.1f} "
        f"Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} "
        f"L{x + w - r:.1f},{y_top:.1f} "
        f"Q{x + w:.1f},{y_top:.1f} {x + w:.1f},{y_top + r:.1f} "
        f"L{x + w:.1f},{y_bottom:.1f} Z"
    )


def _hbar_path(
    x_left: float, x_right: float, y: float, h: float, round_right: bool
) -> str:
    """Horizontal bar anchored flat at the parity edge, rounded outer end."""
    r = 3.0 if round_right else 0.0
    r = min(r, h / 2, x_right - x_left)
    if r <= 0:
        w = x_right - x_left
        return f"M{x_left:.1f},{y:.1f} h{w:.1f} v{h:.1f} h{-w:.1f} Z"
    yc, yt = y + h / 2, y
    return (
        f"M{x_left:.1f},{yt:.1f} L{x_right - r:.1f},{yt:.1f} "
        f"Q{x_right:.1f},{yt:.1f} {x_right:.1f},{yc:.1f} "
        f"Q{x_right:.1f},{yt + h:.1f} {x_right - r:.1f},{yt + h:.1f} "
        f"L{x_left:.1f},{yt + h:.1f} Z"
    )


def _text(
    x: float,
    y: float,
    body: str,
    *,
    fill: str = INK,
    size: int = 11,
    anchor: str = "start",
    weight: str = "normal",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{_esc(body)}</text>'
    )


def _legend(
    parts: list[str], y: float, entries: list[tuple[str, str]], x: float
) -> None:
    cx = x
    for color, label in entries:
        parts.append(
            f'<rect x="{cx:.1f}" y="{y - 10:.1f}" width="12" height="12" fill="{color}"/>'
        )
        parts.append(_text(cx + 17, y + 1, label))
        cx += 17 + len(label) * 6.6 + 26


def _section_header(
    parts: list[str], cursor: float, title: str, subtitle: str
) -> float:
    parts.append(_text(MARGIN_L, cursor + 18, title, size=13, weight="bold"))
    parts.append(_text(MARGIN_L, cursor + 34, subtitle, fill=INK_2))
    return cursor + 34  # grid_top0


def _draw_grid(
    parts: list[str],
    top0: float,
    workloads: tuple[str, ...],
    concs: tuple[int, ...],
    series: tuple[tuple[str, str], ...],
    bar_w: int,
    gap: int,
    value_fmt: Callable[[float], str],
    values_of: Callable[[str, int], list[tuple[float, bool]] | None],
    annotate_of: Callable[[str, int], str] | None,
) -> float:
    """rows x cols grouped-bar grid (trend.py geometry); returns legend y."""
    rows = -(-len(workloads) // COLS)

    for index, workload in enumerate(workloads):
        col, row = index % COLS, index // COLS
        left = MARGIN_L + col * PANEL_W
        top = top0 + row * PANEL_H + 24
        right = left + PANEL_W - 16
        bottom = top + PANEL_H - MARGIN_B

        panel_max = 0.0
        for c in concs:
            for value, _ in values_of(workload, c) or []:
                panel_max = max(panel_max, value)
        panel_max = panel_max * 1.15 if panel_max > 0 else 1.0

        parts.append(_text(left, top - 8, workload, weight="bold"))
        parts.append(
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{INK}"/>'
        )
        parts.append(
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{INK}"/>'
        )
        for tick in range(1, 4):
            value = panel_max * tick / 3
            y = bottom - value / panel_max * (bottom - top)
            parts.append(
                f'<line x1="{left - 3}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
                f'stroke="{GRID}" stroke-dasharray="2,2"/>'
            )
            parts.append(
                _text(left - 6, y + 3, _fmt_tick(value), fill=INK_2, anchor="end")
            )

        slot_w = (right - left) / len(concs)
        total_w = len(series) * bar_w + (len(series) - 1) * gap
        for gi, c in enumerate(concs):
            values = values_of(workload, c)
            center = left + slot_w * (gi + 0.5)
            parts.append(
                _text(center, bottom + 13, f"c{c}", fill=INK_2, anchor="middle")
            )
            if values is None:
                parts.append(
                    _text(
                        center,
                        (top + bottom) / 2,
                        "no data",
                        fill=INK_3,
                        anchor="middle",
                    )
                )
                continue
            y_tops = [
                bottom - value / panel_max * (bottom - top) for value, _ in values
            ]
            x = center - total_w / 2
            for (value, unstable), (name, color), y_top in zip(values, series, y_tops):
                path = _bar_path(x, y_top, bottom, bar_w)
                suffix = " (unstable)" if unstable else ""
                parts.append(
                    f'<path d="{path}" fill="{color}"><title>'
                    f"{_esc(name)} c{c} — {value_fmt(value)}{_esc(suffix)}"
                    "</title></path>"
                )
                x += bar_w + gap
            if annotate_of is not None:
                tallest = min(y_tops)
                parts.append(
                    _text(
                        center,
                        tallest - 6,
                        annotate_of(workload, c),
                        fill=INK_2,
                        size=10,
                        anchor="middle",
                    )
                )

    legend_y = top0 + rows * PANEL_H + 24
    _legend(parts, legend_y, [(color, name) for name, color in series], MARGIN_L)
    return legend_y + 16


def _footer(parts: list[str], cursor: float, notes: list[str]) -> float:
    cursor += 6
    for note in notes:
        parts.append(_text(MARGIN_L, cursor, f"- {note}", fill=INK_2, size=10))
        cursor += 13
    return cursor


def _svg_doc(parts: list[str], height: int) -> str:
    width = COLS * PANEL_W + MARGIN_L
    placeholder = "__HEIGHT__"
    header = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{placeholder}" viewBox="0 0 {width} {placeholder}" '
        'font-family="monospace" font-size="11">'
    )
    body = [
        header,
        f'<rect width="{width}" height="{placeholder}" fill="white"/>',
        *parts,
    ]
    return "\n".join(body).replace(placeholder, str(height)) + "\n</svg>\n"


# ---------------------------------------------------------------------------
# per-metric svg (two comparison planes)


def render_metric_svg(data: VersionsData, metric: str) -> str:
    parts: list[str] = []

    def value_fmt(v: float) -> str:
        return _fmt_value(metric, v)

    # plane 1 — version axis on macOS: 3.14 gil vs 3.15 gil
    top0 = _section_header(
        parts,
        0,
        f"version axis ({data.platform}) — {METRIC_LABEL[metric]}",
        f"3.14 gil (CPython {data.old_flavor.version}) vs 3.15 gil "
        f"(CPython {data.new_flavor.version}) · {_headline(data, metric)}",
    )

    def a_values(w: str, c: int) -> list[tuple[float, bool]] | None:
        pair = data.pairs.get((w, c))
        if pair is None:
            return None
        return [
            (metric_value(pair.old, metric), pair.old.unstable),
            (metric_value(pair.new, metric), pair.new.unstable),
        ]

    def a_annotate(w: str, c: int) -> str:
        pair = data.pairs[(w, c)]
        ratio = _pair_ratio(pair, metric)
        mark = UNSTABLE_MARK if pair.old.unstable or pair.new.unstable else ""
        return f"{(ratio - 1.0) * 100.0:+.1f}%{mark}"

    cursor = _draw_grid(
        parts,
        top0,
        data.workloads,
        data.concs,
        (("3.14 gil", COLOR_314_GIL), ("3.15 gil", COLOR_315_GIL)),
        bar_w=30,
        gap=6,
        value_fmt=value_fmt,
        values_of=a_values,
        annotate_of=a_annotate,
    )
    parts.append(
        _text(
            MARGIN_L,
            cursor + 4,
            f"{UNSTABLE_MARK} unstable sample (median MAD > 5%)",
            fill=INK_2,
        )
    )
    cursor += 22

    # plane 2 — execution-mode axis on Linux: 3.15 gil vs nogil vs nogil+jit
    top0 = _section_header(
        parts,
        cursor,
        f"execution-mode axis (Linux/lima) — CPython {data.lima_version}",
        "3.15 gil vs nogil vs nogil+jit · no 3.14 nogil/jit data exists — "
        "planes are never compared cross-OS",
    )

    def b_values(w: str, c: int) -> list[tuple[float, bool]] | None:
        cell = data.lima.get((w, c))
        if cell is None or any(label not in cell for label, _ in LIMA_FLAVORS):
            return None
        return [
            (metric_value(cell[label], metric), cell[label].unstable)
            for label, _ in LIMA_FLAVORS
        ]

    cursor = _draw_grid(
        parts,
        top0,
        data.workloads,
        data.concs,
        (
            ("3.15 gil", COLOR_315_GIL),
            ("3.15 nogil", COLOR_315_NOGIL),
            ("3.15 nogil+jit", COLOR_315_NOGIL_JIT),
        ),
        bar_w=22,
        gap=4,
        value_fmt=value_fmt,
        values_of=b_values,
        annotate_of=None,
    )

    pinned = data.pair_source != data.source
    deps_note = (
        "pinned to the same releases in the 3.14 retest"
        if pinned
        else "not pinned: part of any end-to-end delta may come from these"
    )
    end = _footer(
        parts,
        cursor + 8,
        [
            MATRIX_NOTE,
            f"version axis source — 3.14: {data.pair_source} ({data.pair_saved}); "
            f"3.15: {data.source} ({data.saved_at})",
            f"macOS dependency versions — 3.14: {data.old_deps}; "
            f"3.15: {data.new_deps} ({deps_note})",
            "per-panel y-scales are independent — compare the % annotations / md "
            "ratios, not bar heights across panels",
            *data.warnings,
        ],
    )
    return _svg_doc(parts, int(end + 10))


def render_release_metric_svgs(report: dict[str, Any]) -> list[tuple[str, str]]:
    """A/B grouped-bar charts for a compare report — one svg per
    interpreter/variant plane. Returns ``[(plane name, svg)]``.

    The compare report carries one metric (``report["metric"]``) with rows
    keyed by interpreter/variant/workload/concurrency; the two bar series
    are the report's A and B sides."""
    metric = str(report["metric"])
    sides = report["a"], report["b"]

    def side_version(side: dict[str, Any]) -> str:
        project = side.get("project") or {}
        return str(project.get("project_version") or "?")

    a_label = f"A: v{side_version(sides[0])}"
    b_label = f"B: v{side_version(sides[1])}"

    planes: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    order: list[str] = []
    for row in report["rows"]:
        key = row["key"]
        plane = f"{key['interpreter']}/{key['variant']}"
        if plane not in planes:
            planes[plane] = {}
            order.append(plane)
        planes[plane][(key["workload"], key["concurrency"])] = row

    workloads = list(DEFAULT_WORKLOADS)
    for plane_cells in planes.values():
        for workload, _ in plane_cells:
            if workload not in workloads:
                workloads.append(workload)
    concs: tuple[int, ...] = tuple(
        sorted({int(c) for cells in planes.values() for _, c in cells})
    )

    charts: list[tuple[str, str]] = []
    for plane in order:
        cells: dict[tuple[str, int], dict[str, Any]] = planes[plane]
        parts: list[str] = []

        def value_fmt(v: float) -> str:
            return _fmt_value(metric, v)

        def values_of(
            w: str, c: int, cells: dict[tuple[str, int], dict[str, Any]] = cells
        ) -> list[tuple[float, bool]] | None:
            row = cells.get((w, c))
            if row is None:
                return None
            return [(float(row["a"]), False), (float(row["b"]), False)]

        def annotate_of(
            w: str, c: int, cells: dict[tuple[str, int], dict[str, Any]] = cells
        ) -> str:
            row = cells[(w, c)]
            return f"{(row['ratio_b_over_a'] - 1.0) * 100.0:+.1f}%"

        top0 = _section_header(
            parts,
            0,
            f"{plane} — {METRIC_LABEL[metric]}",
            f"{a_label} vs {b_label}",
        )
        cursor = _draw_grid(
            parts,
            top0,
            tuple(workloads),
            concs,
            ((a_label, COLOR_314_GIL), (b_label, COLOR_315_GIL)),
            bar_w=30,
            gap=6,
            value_fmt=value_fmt,
            values_of=values_of,
            annotate_of=annotate_of,
        )
        end = _footer(
            parts,
            cursor + 8,
            [
                f"A source: {sides[0].get('source')} ({sides[0].get('timestamp')}); "
                f"B source: {sides[1].get('source')} ({sides[1].get('timestamp')})",
                "per-panel y-scales are independent — compare the % annotations, "
                "not bar heights across panels",
            ],
        )
        charts.append((plane, _svg_doc(parts, int(end + 10))))
    return charts


# ---------------------------------------------------------------------------
# micro svg


def render_micro_svg(data: VersionsData) -> str:
    parts: list[str] = []
    micro = data.micro
    if micro is None:
        parts.append(
            _text(MARGIN_L, 18, "micro benchmarks — omitted", size=13, weight="bold")
        )
        parts.append(_text(MARGIN_L, 34, data.micro_note, fill=INK_2))
        return _svg_doc(parts, 60)

    parts.append(
        _text(
            MARGIN_L,
            18,
            "micro benchmarks — us/op ratio (3.15 gil / 3.14 gil, lower is better)",
            size=13,
            weight="bold",
        )
    )
    parts.append(
        _text(
            MARGIN_L,
            34,
            f"CPython {micro.old_version} vs {micro.new_version} — same macOS "
            "run · pure-stdlib hot paths (no uvloop/httptools): the cleanest "
            "interpreter-only signal",
            fill=INK_2,
        )
    )
    # legend on the title row: the parity-line label owns the subtitle row
    _legend(
        parts,
        20,
        [(COLOR_FASTER, "3.15 faster"), (COLOR_SLOWER, "3.15 slower")],
        COLS * PANEL_W + MARGIN_L - 260,
    )

    label_right, x0 = 254.0, 276.0
    x1 = float(COLS * PANEL_W + MARGIN_L - 90)
    bars_top = 52.0
    pitch, bar_h = 26.0, 16.0
    benches = sorted(micro.benches, key=lambda b: b.ratio, reverse=True)

    ratios = [b.ratio for b in benches] or [1.0]
    lo = min(min(ratios), 1.0) - 0.02
    hi = max(max(ratios), 1.0) + 0.02

    def x_of(v: float) -> float:
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    bottom = bars_top + len(benches) * pitch
    for i, bench in enumerate(benches):
        y = bars_top + i * pitch
        parts.append(_text(label_right, y + bar_h - 4, bench.name, anchor="end"))
        xp = x_of(1.0)
        xr = x_of(bench.ratio)
        if bench.ratio < 1.0:
            path = _hbar_path(xr, xp, y, bar_h, round_right=False)
            color, tip_x, tip_anchor = COLOR_FASTER, xr - 6, "end"
        else:
            path = _hbar_path(xp, xr, y, bar_h, round_right=True)
            color, tip_x, tip_anchor = COLOR_SLOWER, xr + 6, "start"
        parts.append(
            f'<path d="{path}" fill="{color}"><title>{_esc(bench.name)} — '
            f"py314 {bench.old_us:.3f}us -&gt; py315 {bench.new_us:.3f}us "
            f"({bench.ratio:.3f}x)</title></path>"
        )
        parts.append(
            _text(tip_x, y + bar_h - 4, f"{bench.ratio:.2f}x", anchor=tip_anchor)
        )

    xp = x_of(1.0)
    parts.append(
        f'<line x1="{xp:.1f}" y1="{bars_top - 8:.1f}" x2="{xp:.1f}" '
        f'y2="{bottom + 2:.1f}" stroke="{INK_3}" stroke-dasharray="3,3"/>'
    )
    parts.append(_text(xp, bars_top - 12, "1.00x", fill=INK, anchor="middle"))
    step = 0.05
    tick = math.ceil(lo / step) * step
    while tick <= hi:
        if abs(tick - 1.0) > 1e-6:
            parts.append(
                _text(
                    x_of(tick), bottom + 18, f"{tick:.2f}", fill=INK_2, anchor="middle"
                )
            )
        tick += step
    return _svg_doc(parts, int(bottom + 32))


# ---------------------------------------------------------------------------
# html + markdown + pdf


def render_html(data: VersionsData, sections: list[tuple[str, str, str]]) -> str:
    """sections: (metric-or-"micro", heading, svg) in page order.

    Trend-style skeleton: shared palette, KPI tiles for the headline
    medians, and every chart inside a figure.plate."""

    def _median_ratio(metric: str) -> float | None:
        ratios = sorted(_pair_ratio(pair, metric) for pair in data.pairs.values())
        return ratios[len(ratios) // 2] if ratios else None

    tiles = ""
    for metric, _, _ in sections:
        if metric not in METRICS:
            continue
        median = _median_ratio(metric)
        if median is None:
            continue
        higher_better = METRIC_IMPROVES_WITH_HIGHER[metric]
        status = (
            "improved"
            if (median > 1.0) == higher_better
            else "regressed" if median != 1.0 else "flat"
        )
        better = sum(
            1
            for pair in data.pairs.values()
            if _verdict_ratio(_pair_ratio(pair, metric), higher_better)
        )
        tiles += (
            f'<div class="tile {status}">'
            f'<div class="label">{METRIC_LABEL[metric]} — 3.15/3.14 中位</div>'
            f'<div class="value">{median:.3f}</div>'
            f'<div class="delta">{better}/{len(data.pairs)} cells better on 3.15 '
            f"· {status}</div>"
            "</div>"
        )
    if data.micro is not None and data.micro.benches:
        median = statistics.median(b.ratio for b in data.micro.benches)
        status = "improved" if median < 1.0 else "regressed"
        tiles += (
            f'<div class="tile {status}">'
            '<div class="label">micro benchmarks — us/op 比值中位</div>'
            f'<div class="value">{median:.3f}</div>'
            f'<div class="delta">{len(data.micro.benches)} benches · {status}</div>'
            "</div>"
        )

    body = "".join(
        f'<h2>{heading}</h2>\n<figure class="plate">\n{svg}\n</figure>\n'
        for _, heading, svg in sections
    )
    notes = [
        "Hover a bar for exact values. The * mark flags unstable samples "
        "(median MAD > 5%).",
        MATRIX_NOTE,
        "Micro benches avoid uvloop/httptools entirely — the cleanest "
        "interpreter-only signal.",
        *data.warnings,
    ]
    notes_html = "".join(f"<li>{n}</li>" for n in notes)
    rows_html = "".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>"
        for k, v in [
            ("data source", data.source),
            (
                "version axis source",
                f"3.14: {data.pair_source} ({data.pair_saved}); "
                f"3.15: {data.source} ({data.saved_at})",
            ),
            ("source run", data.source_run),
            ("baseline saved at", data.saved_at),
            ("platform", data.platform),
            ("project", data.project_line),
            (
                "version definition",
                "{3.14, 3.15} x {gil, nogil, nogil+jit}; "
                "compared within same-OS planes only",
            ),
            (
                "samples",
                f"{data.sample_total} ({len(data.pairs)} version pairs, "
                f"{len(data.lima)} lima cells, nojit control excluded)",
            ),
            ("dependency versions", f"3.14: {data.old_deps}; 3.15: {data.new_deps}"),
            *[
                (metric, _headline(data, metric))
                for metric, _, _ in sections
                if metric in METRICS
            ],
        ]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>asgi-webdav python version comparison</title>
<style>
{REPORT_CSS}
body {{ max-width: 1400px; font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<main>
<h1>asgi-webdav python version comparison</h1>
<nav class="tiles">{tiles}</nav>

<h2 id="meta">数据与方法</h2>
<div class="scroll">
<table>
{rows_html}
</table>
</div>

{body}

<h2 id="notes">Notes</h2>
<ul>
{notes_html}
</ul>
</main>
</body>
</html>
"""


def _verdict_ratio(ratio: float, higher_better: bool) -> bool:
    """True when the ratio favours 3.15 (the B/new side)."""
    return ratio > 1.0 if higher_better else ratio < 1.0


def _md_pair_table(data: VersionsData, metric: str, lines: list[str]) -> None:
    lines.append(
        f"### {metric} — {data.platform}: 3.14 gil vs 3.15 gil "
        f"({_headline(data, metric)})"
    )
    lines.append("")
    lines.append("| workload | c | 3.14 gil | 3.15 gil | 3.15/3.14 |")
    lines.append("|---|---|---:|---:|---:|")
    for w in data.workloads:
        for c in data.concs:
            pair = data.pairs.get((w, c))
            if pair is None:
                continue
            ratio = _pair_ratio(pair, metric)
            mark = UNSTABLE_MARK if pair.old.unstable or pair.new.unstable else ""
            lines.append(
                f"| {w} | {c} | {_fmt_value(metric, metric_value(pair.old, metric))} "
                f"| {_fmt_value(metric, metric_value(pair.new, metric))} "
                f"| {ratio:.3f}{mark} |"
            )
    better = "&gt;" if METRIC_IMPROVES_WITH_HIGHER[metric] else "&lt;"
    lines.append("")
    lines.append(f"ratio {better} 1 is better on 3.15")
    lines.append("")


def _md_lima_table(data: VersionsData, metric: str, lines: list[str]) -> None:
    lines.append(
        f"### {metric} — Linux (lima): CPython {data.lima_version} "
        "gil vs nogil vs nogil+jit"
    )
    lines.append("")
    lines.append(
        "| workload | c | gil | nogil | nogil+jit | nogil/gil | (nogil+jit)/gil |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for w in data.workloads:
        for c in data.concs:
            cell = data.lima.get((w, c))
            if cell is None or any(
                flavor_label not in cell for flavor_label, _ in LIMA_FLAVORS
            ):
                continue
            values = [
                metric_value(cell[flavor_label], metric)
                for flavor_label, _ in LIMA_FLAVORS
            ]
            marks = [
                UNSTABLE_MARK if cell[flavor_label].unstable else ""
                for flavor_label, _ in LIMA_FLAVORS
            ]
            lines.append(
                f"| {w} | {c} | {_fmt_value(metric, values[0])}{marks[0]} "
                f"| {_fmt_value(metric, values[1])}{marks[1]} "
                f"| {_fmt_value(metric, values[2])}{marks[2]} "
                f"| {values[1] / values[0]:.3f} | {values[2] / values[0]:.3f} |"
            )
    lines.append("")


def render_markdown(data: VersionsData, micro_svg_name: str) -> str:
    lines: list[str] = []
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    lines.append("# python version comparison — asgi-webdav")
    lines.append("")
    lines.append(
        "versions = {3.14, 3.15} x {gil, nogil, nogil+jit}; comparisons run "
        "within same-OS planes only"
    )
    lines.append("")
    lines.append(f"- source: {data.source} ({data.source_run}, saved {data.saved_at})")
    lines.append(
        f"- version axis: 3.14 from {data.pair_source} ({data.pair_saved}); "
        f"3.15 from {data.source} ({data.saved_at})"
    )
    lines.append(f"- project: {data.project_line} · platform: {data.platform}")
    lines.append(f"- generated: {generated}")
    lines.append(f"- matrix: {MATRIX_NOTE.removeprefix('measured matrix — ')}")
    pinned = data.pair_source != data.source
    deps_note = (
        "pinned to the same releases in the 3.14 retest"
        if pinned
        else "not pinned — part of any end-to-end delta may come from these"
    )
    lines.append(
        f"- macOS dependency versions: 3.14 {data.old_deps}; 3.15 {data.new_deps} "
        f"({deps_note})"
    )
    lines.append("")
    for metric in METRICS:
        _md_pair_table(data, metric, lines)
        _md_lima_table(data, metric, lines)
    if data.micro is not None:
        lines.append(
            f"### micro benchmarks — us per op, {data.micro.old_version} vs "
            f"{data.micro.new_version} (lower is better; pure stdlib, no "
            "uvloop/httptools — the cleanest interpreter-only signal)"
        )
        lines.append("")
        lines.append("| bench | py314 us | py315 us | 3.15/3.14 |")
        lines.append("|---|---:|---:|---:|")
        for bench in sorted(data.micro.benches, key=lambda b: b.name):
            lines.append(
                f"| {bench.name} | {bench.old_us:.3f} | {bench.new_us:.3f} "
                f"| {bench.ratio:.3f} |"
            )
        lines.append("")
    else:
        lines.append("### micro benchmarks — omitted")
        lines.append("")
        lines.append(data.micro_note)
        lines.append("")
    lines.append("## notes")
    lines.append("")
    lines.append(
        "- per-panel y-scales are independent; compare ratios and % "
        "annotations, not bar heights across panels"
    )
    lines.append(
        f"- charts: see {micro_svg_name.rsplit('-', 2)[0]}-*.svg "
        "and the html/pdf next to this file"
    )
    for warning in data.warnings:
        lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


def _find_chrome() -> str | None:
    """Locate a Chrome/Chromium binary for svg->pdf printing (best effort)."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for name in ("google-chrome", "google-chrome-stable", "chromium"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def write_pdf(svgs: list[str], pdf_path: Path) -> bool:
    """Print the svgs to one multi-page pdf via headless Chrome.

    The @page size matches the tallest svg's css-px dimensions (96 px per
    inch); each svg goes on its own page via page-break-before.
    """
    chrome = _find_chrome()
    if chrome is None:
        return False
    dims = []
    for svg in svgs:
        match = re.search(r'width="(\d+)" height="(\d+)"', svg)
        if match is None:
            return False
        dims.append((int(match.group(1)), int(match.group(2))))
    page_w = max(w for w, _ in dims) / 96 * 25.4
    page_h = max(h for _, h in dims) / 96 * 25.4 + 1.0  # 1mm slack vs rounding
    pages = []
    for index, svg in enumerate(svgs):
        style = "page-break-before: always;" if index else ""
        pages.append(f'<div style="{style}">{svg}</div>')
    wrapper = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"@page {{ size: {page_w:.2f}mm {page_h:.2f}mm; margin: 0; }}"
        "html, body { margin: 0; padding: 0; }"
        "svg { display: block; }"
        "</style></head><body>" + "\n".join(pages) + "</body></html>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "print.html"
        html_path.write_text(wrapper, encoding="utf-8")
        subprocess.run(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path.absolute()}",
                html_path.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    return pdf_path.exists()


def write_report(inputs: PyVersionsInputs) -> Path:
    """Render every artifact; return the main html path.

    Every successful generation is kept: ``py-versions-<stamp>.html`` plus
    a ``py-versions-<stamp>-res/`` directory (stamped filenames)."""
    data = collect(inputs)
    identity = identity_from_meta(dict(_load_json(inputs.baseline_dir / "meta.json")))
    now = datetime.now()
    base = inputs.output_dir / f"py-versions-{identity}-{now:%Y%m%d}-{now:%H%M%S}"
    res_dir = inputs.output_dir / (base.name + "-res")
    res_dir.mkdir(parents=True, exist_ok=True)

    pdf_svgs: list[str] = []
    sections: list[tuple[str, str, str]] = []
    for metric in METRICS:
        svg = render_metric_svg(data, metric)
        stem = SVG_STEM[metric]
        (res_dir / f"{stem}.svg").write_text(svg, encoding="utf-8")
        pdf_svgs.append(svg)
        sections.append((metric, f"{metric} — {METRIC_LABEL[metric]}", svg))
        print(f"{metric}: {_headline(data, metric)}")
    micro_svg = render_micro_svg(data)
    (res_dir / "micro.svg").write_text(micro_svg, encoding="utf-8")
    pdf_svgs.append(micro_svg)
    sections.append(("micro", "micro benchmarks (us/op ratio)", micro_svg))
    if data.micro is not None:
        print(
            f"micro: median {statistics.median(b.ratio for b in data.micro.benches):.3f}"
        )
    else:
        print(data.micro_note)

    (inputs.output_dir / f"{base.name}.html").write_text(
        render_html(data, sections), encoding="utf-8"
    )
    (res_dir / "py-versions.md").write_text(
        render_markdown(data, "micro.svg"), encoding="utf-8"
    )

    pdf_path = res_dir / "py-versions.pdf"
    if write_pdf(pdf_svgs, pdf_path):
        print(f"pdf written: {pdf_path}")
    else:
        print(
            "pdf skipped: no Chrome/Chromium binary found (convert the svgs manually)"
        )
    for path in sorted(res_dir.glob("*.svg")):
        print(f"svg written: {path}")
    html_path = inputs.output_dir / f"{base.name}.html"
    print(f"report written: {html_path}")
    return html_path
