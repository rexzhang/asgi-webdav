"""Cross-baseline trend rendering: line charts over all saved baselines.

Self-contained by design — the SVG (static image) and the HTML (interactive
wrapper around the same SVG) are generated with the stdlib only; no chart
library and no JavaScript framework. Missing data points break the polyline
instead of being interpolated.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.common.error import ToolError
from tools.perf.bench import BenchSample
from tools.perf.settings import Settings

# higher value = better? used for the "lower is better" annotations
METRIC_IMPROVES_WITH_HIGHER: dict[str, bool] = {
    "rps": True,
    "p99": False,
    "cpu_per_req": False,
}

METRIC_LABEL: dict[str, str] = {
    "rps": "throughput (rps, higher is better)",
    "p99": "p99 latency (ms, lower is better)",
    "cpu_per_req": "server cpu per request (ms, lower is better)",
}

PALETTE = (
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
    "#bcbd22",
    "#7f7f7f",
)


def metric_value(sample: BenchSample, metric: str) -> float:
    if metric == "rps":
        return sample.rps
    if metric == "p99":
        return sample.lat_ms_p99
    requests = sample.requests or 1
    return sample.server_cpu_s / requests * 1000.0


def collect_trend(
    settings: Settings,
    *,
    metric: str,
    interpreter_filter: tuple[str, ...],
    workload_filter: tuple[str, ...],
    concs: tuple[int, ...],
) -> dict[str, Any]:
    """Aggregate every saved baseline into a time-ordered trend dataset."""
    from tools.perf.baseline import baseline_dir, list_baselines

    def _saved_at_key(entry: dict[str, Any]) -> tuple[int, str]:
        # old baselines have naive stamps, new ones carry the tz offset —
        # parse and normalize so mixed formats still order correctly
        raw = str(entry.get("saved_at") or "")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return (0, raw)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return (1, parsed.astimezone().isoformat())

    entries = sorted(list_baselines(settings), key=_saved_at_key)
    if len(entries) < 2:
        msg = (
            f"need at least 2 baselines for a trend, found {len(entries)}; "
            "run a measurement first (baselines save automatically)"
        )
        raise ToolError(msg)

    baselines: list[dict[str, Any]] = []
    per_baseline: list[dict[str, float]] = []
    workload_order: list[str] = []
    interpreter_order: list[str] = []
    conc_order: list[int] = []

    for entry in entries:
        name = str(entry["name"])
        project = entry.get("project") or {}
        baselines.append(
            {
                "name": name,
                "saved_at": entry.get("saved_at"),
                "project_version": project.get("project_version"),
                "git_describe": project.get("git_describe"),
            }
        )
        measured: dict[str, float] = {}
        for sample in load_summary_tolerant(baseline_dir(settings, name)):
            if interpreter_filter and sample.interpreter not in interpreter_filter:
                continue
            if workload_filter and sample.workload not in workload_filter:
                continue
            if concs and sample.concurrency not in concs:
                continue
            if sample.interpreter not in interpreter_order:
                interpreter_order.append(sample.interpreter)
            if sample.workload not in workload_order:
                workload_order.append(sample.workload)
            if sample.concurrency not in conc_order:
                conc_order.append(sample.concurrency)
            key = f"{sample.workload}|{sample.interpreter}|{sample.concurrency}"
            measured[key] = metric_value(sample, metric)
        per_baseline.append(measured)

    # align: every combo key gets one slot per baseline, None where that
    # baseline did not measure it (a combo first appearing later is padded)
    all_keys: list[str] = []
    for measured in per_baseline:
        for key in measured:
            if key not in all_keys:
                all_keys.append(key)
    values: dict[str, list[float | None]] = {
        key: [measured.get(key) for measured in per_baseline] for key in all_keys
    }

    return {
        "metric": metric,
        "metric_label": METRIC_LABEL[metric],
        "baselines": baselines,
        "workloads": workload_order,
        "interpreters": interpreter_order,
        "concs": sorted(conc_order),
        "series": values,
    }


def load_summary_tolerant(baseline_path: Path) -> list[BenchSample]:
    from tools.perf.summary import load_summary

    try:
        return load_summary(baseline_path)
    except (ToolError, json.JSONDecodeError):
        return []


def _fmt_value(metric: str, value: float) -> str:
    return f"{value:.1f}" if metric == "rps" else f"{value:.2f}"


def render_trend_svg(trend: dict[str, Any]) -> str:
    """Faceted line chart as a standalone SVG (no scripts, no dependencies)."""
    workloads = trend["workloads"]
    interpreters = trend["interpreters"]
    concs = trend["concs"]
    n_baselines = len(trend["baselines"])
    if not workloads or n_baselines < 2:
        return ""

    cols = min(len(workloads), 3)
    rows = -(-len(workloads) // cols)
    panel_w, panel_h = 430, 240
    margin_l, margin_b, margin_t = 62, 34, 30
    header_h = 34  # keep the chart title clear of the first row's titles
    width = cols * panel_w + margin_l
    # the baseline-order legend wraps to fit the canvas width
    order_text = "  ".join(
        f"{i + 1}={b['name']}" for i, b in enumerate(trend["baselines"])
    )
    usable = max(200, width - margin_l - 10)
    order_lines = textwrap.wrap(order_text, width=int(usable / 6.6)) or [""]

    # bottom layout, strictly sequential: panels -> line legend -> order
    legend_entries = len(interpreters) * len(concs)
    legend_rows = -(-legend_entries // 4)
    content_bottom = header_h + rows * panel_h + margin_b
    legend_title_y = content_bottom + 30  # below the per-panel x-tick numbers
    legend_first_y = legend_title_y + 14
    order_title_y = legend_first_y + (legend_rows - 1) * 14 + 16
    order_first_y = order_title_y + 16
    height = order_first_y + (len(order_lines) - 1) * 13 + 12

    def x_pos(i: int, left: int) -> int:
        return (
            left + int((i + 0.5) * (panel_w - margin_l - 16) / max(1, n_baselines)) + 8
        )

    def y_pos(panel_top: int, value: float, vmax: float) -> int:
        top = panel_top + margin_t
        bottom = panel_top + panel_h - margin_b
        span = max(vmax, 1e-9)
        return int(bottom - (value / span) * (bottom - top))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="monospace" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="{margin_l}" y="18" font-size="13" font-weight="bold">'
        f"asgi-webdav trend — {trend['metric_label']}</text>",
    ]

    for index, workload in enumerate(workloads):
        col = index % cols
        row = index // cols
        left = margin_l + col * panel_w
        top = header_h + row * panel_h + 24
        right = left + panel_w - 16
        bottom = top + panel_h - margin_b

        # per-panel y-max across its series
        panel_max = 0.0
        for interpreter in interpreters:
            for c in concs:
                key = f"{workload}|{interpreter}|{c}"
                if key not in trend["series"]:
                    continue
                panel_max = max(
                    panel_max, *(v for v in trend["series"][key] if v is not None)
                )
        panel_max = panel_max * 1.15 if panel_max > 0 else 1.0

        parts.append(
            f'<text x="{left}" y="{top - 8}" font-weight="bold">{workload}</text>'
        )
        # axes
        parts.append(
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#333"/>'
        )
        parts.append(
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#333"/>'
        )
        # y ticks (3)
        for tick in range(1, 4):
            value = panel_max * tick / 3
            y = y_pos(top, value, panel_max)
            parts.append(
                f'<line x1="{left - 3}" y1="{y}" x2="{right}" y2="{y}" '
                f'stroke="#ddd" stroke-dasharray="2,2"/>'
            )
            parts.append(
                f'<text x="{left - 6}" y="{y + 3}" text-anchor="end" fill="#666">'
                f"{value:.0f}</text>"
            )
        # x ticks: baseline index
        for i in range(n_baselines):
            x = x_pos(i, left)
            parts.append(
                f'<line x1="{x}" y1="{bottom}" x2="{x}" y2="{bottom + 3}" stroke="#333"/>'
            )
            parts.append(
                f'<text x="{x}" y="{bottom + 13}" text-anchor="middle" fill="#666">'
                f"{i + 1}</text>"
            )

        color_j = 0
        for interpreter in interpreters:
            for c in concs:
                key = f"{workload}|{interpreter}|{c}"
                if key not in trend["series"]:
                    continue
                color = PALETTE[color_j % len(PALETTE)]
                color_j += 1
                series = trend["series"][key]
                segments: list[list[tuple[int, int, float]]] = []
                current: list[tuple[int, int, float]] = []
                for i, value in enumerate(series):
                    if value is None:
                        if current:
                            segments.append(current)
                            current = []
                        continue
                    current.append(
                        (x_pos(i, left), y_pos(top, value, panel_max), value)
                    )
                if current:
                    segments.append(current)
                for segment in segments:
                    points = " ".join(f"{x},{y}" for x, y, _ in segment)
                    parts.append(
                        f'<polyline points="{points}" fill="none" stroke="{color}" '
                        f'stroke-width="2"/>'
                    )
                for segment in segments:
                    for x, y, value in segment:
                        parts.append(
                            f'<circle cx="{x}" cy="{y}" r="3" fill="{color}">'
                            f"<title>{interpreter} c{c} — {value:.1f}</title></circle>"
                        )

    # legend: one entry per line (interpreter x concurrency); column width
    # adapts to the longest label so long FT names never collide
    legend_labels = [f"{i} c{c}" for i in interpreters for c in concs]
    legend_col_w = max(150, int(max(len(s) for s in legend_labels) * 6.6) + 34)
    parts.append(f'<text x="{margin_l}" y="{legend_title_y}" fill="#333">lines:</text>')
    j = 0
    for interpreter in interpreters:
        for c in concs:
            color = PALETTE[j % len(PALETTE)]
            x = margin_l + (j % 4) * legend_col_w
            y = legend_first_y + (j // 4) * 14
            parts.append(
                f'<line x1="{x}" y1="{y - 3}" x2="{x + 18}" y2="{y - 3}" '
                f'stroke="{color}" stroke-width="2"/>'
            )
            parts.append(f'<text x="{x + 22}" y="{y}">{interpreter} c{c}</text>')
            j += 1

    # legend: baseline order (wrapped to the canvas width)
    parts.append(
        f'<text x="{margin_l}" y="{order_title_y}" fill="#333">'
        "baselines (x order):</text>"
    )
    for li, line in enumerate(order_lines):
        parts.append(
            f'<text x="{margin_l}" y="{order_first_y + li * 13}" fill="#666">'
            f"{line}</text>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def render_trend_html(trend: dict[str, Any], svg: str) -> str:
    baselines_rows = "\n".join(
        f"<tr><td>{i + 1}</td><td>{b['name']}</td><td>{b.get('saved_at') or ''}</td>"
        f"<td>{b.get('project_version') or ''}</td>"
        f"<td>{b.get('git_describe') or ''}</td></tr>"
        for i, b in enumerate(trend["baselines"])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>asgi-webdav performance trend</title>
<style>
  body {{ font-family: monospace; margin: 16px auto; max-width: 1400px; }}
  table {{ border-collapse: collapse; margin: 12px 0; }}
  td, th {{ border: 1px solid #ccc; padding: 2px 8px; text-align: left; }}
  .svg-box {{ overflow-x: auto; }}
  h1 {{ font-size: 18px; }} h2 {{ font-size: 15px; }}
</style>
</head>
<body>
<h1>asgi-webdav performance trend — {trend['metric_label']}</h1>
<p>Hover a point for the exact value. Missing points are baselines where the
combo was not measured.</p>
<div class="svg-box">
{svg}
</div>
<h2>Baselines (x order)</h2>
<table>
<tr><th>#</th><th>name</th><th>saved at</th><th>version</th><th>git</th></tr>
{baselines_rows}
</table>
</body>
</html>
"""


def render_trend_markdown(trend: dict[str, Any]) -> str:
    names = [b["name"] for b in trend["baselines"]]
    lines = [
        f"# performance trend — {trend['metric_label']}",
        "",
    ]
    for workload in trend["workloads"]:
        lines += [f"## {workload}", ""]
        header = "| interpreter | c | " + " | ".join(names) + " | vs first |"
        lines += [header, "|---" * (3 + len(names)) + "|"]
        first_values: dict[str, float] = {}
        for interpreter in trend["interpreters"]:
            for c in trend["concs"]:
                key = f"{workload}|{interpreter}|{c}"
                series = trend["series"].get(key)
                if not series:
                    continue
                cells = [
                    _fmt_value(trend["metric"], v) if v is not None else "-"
                    for v in series
                ]
                first = next((v for v in series if v is not None), None)
                last = next((v for v in reversed(series) if v is not None), None)
                if first and last:
                    first_values[key] = first
                    ratio = last / first
                    vs = f"{ratio:.2f}x"
                else:
                    vs = "-"
                lines.append(
                    f"| {interpreter} | {c} | " + " | ".join(cells) + f" | {vs} |"
                )
        lines.append("")
    lines += [
        "vs first = last-baseline value / first-baseline value "
        "(higher rps is better; lower p99/cpu is better).",
        "",
    ]
    return "\n".join(lines)
