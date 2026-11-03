"""Integrated performance trend report generation.

One invocation writes a self-contained ``report-<stamp>.html`` (KPI
summary, per-view inline SVG sections, methodology) plus per-view
attachments under ``report-<stamp>-res/``. Every successful generation is
kept (stamped filenames); the underlying data stays in the run/baseline
stores.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.perf.baseline import baselines_root
from tools.perf.settings import Settings
from tools.perf.trend import (
    REPORT_CSS,
    collect_trend,
    render_trend_markdown,
    render_trend_svg,
)


def identity_from_meta(meta: dict[str, Any]) -> str:
    """``<project_version>[-<short hash>]`` — the hash appears only when the
    snapshot is not a clean release state (dirty tree, or HEAD has distance
    from the version tag)."""
    project = meta.get("project") or {}
    version = str(
        project.get("project_version") or meta.get("project_version") or "unknown"
    )
    describe = str(project.get("git_describe") or meta.get("git_describe") or "")
    dirty = bool(project.get("git_dirty") or meta.get("git_dirty"))
    short = str(project.get("git_commit") or meta.get("git_commit") or "")[:7]
    if not (dirty or describe != f"v{version}"):
        return version
    return f"{version}-{short}" if short else version


def _latest_baseline_meta(settings: Settings) -> dict[str, Any]:
    """Meta of the newest saved baseline in the output store (by timestamp)."""
    best: tuple[str, dict[str, Any]] = ("", {})
    for meta_path in baselines_root(settings).glob("*/meta.json"):
        try:
            meta = dict(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        stamp = str(meta.get("timestamp") or "")
        if stamp > best[0]:
            best = (stamp, meta)
    return best[1]


_RATIO_IMPROVED = 1.05
_RATIO_REGRESSED = 0.95


@dataclass(frozen=True)
class ChartView:
    name: str
    title: str
    blurb: str
    metric: str
    workloads: tuple[str, ...]  # empty tuple = every workload


CHART_VIEWS: tuple[ChartView, ...] = (
    ChartView(
        name="full-rps",
        title="全部组合吞吐",
        metric="rps",
        workloads=(),
        blurb="全部 workload × 解释器 × 并发的吞吐趋势,完整矩阵一览。",
    ),
    ChartView(
        name="propfind-rps",
        title="PROPFIND 吞吐",
        metric="rps",
        workloads=("propfind-0", "propfind-1-10", "propfind-1-100", "propfind-1-1000"),
        blurb=(
            "macOS 腿 propfind-1-* 的台阶来自响应渲染器重写;lima 腿走平,"
            "瓶颈在枚举层(每条目一次线程池往返),属后续任务。"
        ),
    ),
    ChartView(
        name="propfind-p99",
        title="PROPFIND 尾延迟",
        metric="p99",
        workloads=("propfind-1-100", "propfind-1-1000"),
        blurb="越低越好;macOS 侧随吞吐提升同步下降。",
    ),
    ChartView(
        name="core-rps",
        title="核心方法吞吐",
        metric="rps",
        workloads=("get-4k", "head-4k", "options", "put-4k"),
        blurb=(
            "回归观察面:get/head/options 应走平;put-4k macOS 的台阶为中间提交"
            "(f806bf6)引入的 temp+rename 开销,与 propfind 改动无关。"
        ),
    ),
)


@dataclass(frozen=True)
class KpiSpec:
    view: str  # ChartView.name
    key: str  # "<workload>|<interpreter>|<concurrency>"
    label: str
    lower_is_better: bool = False


KPI_SPECS: tuple[KpiSpec, ...] = (
    KpiSpec(
        "propfind-rps", "propfind-1-1000|py314|16", "propfind-1-1000 吞吐 (py314 c16)"
    ),
    KpiSpec(
        "propfind-rps", "propfind-1-100|py315|16", "propfind-1-100 吞吐 (py315 c16)"
    ),
    KpiSpec(
        "propfind-p99",
        "propfind-1-1000|py314|16",
        "propfind-1-1000 p99 (py314 c16)",
        lower_is_better=True,
    ),
    KpiSpec("core-rps", "put-4k|py315|1", "put-4k 吞吐 (py315 c1)"),
    KpiSpec(
        "propfind-rps",
        "propfind-1-1000|py315-lima|16",
        "propfind-1-1000 吞吐 (lima c16)",
    ),
)

_STATUS_TEXT = {"improved": "提升", "regressed": "回退", "flat": "持平", "na": "无数据"}


def _fmt_value(metric: str, value: float) -> str:
    return f"{value:.1f}" if metric == "rps" else f"{value:.2f}"


def _ratio_status(ratio: float, lower_is_better: bool) -> str:
    improved = (
        ratio <= _RATIO_REGRESSED if lower_is_better else ratio >= _RATIO_IMPROVED
    )
    regressed = (
        ratio >= _RATIO_IMPROVED if lower_is_better else ratio <= _RATIO_REGRESSED
    )
    if improved:
        return "improved"
    if regressed:
        return "regressed"
    return "flat"


def collect_kpis(views: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive KPI tiles from collected trend data; missing combos degrade to n/a."""
    kpis: list[dict[str, Any]] = []
    for spec in KPI_SPECS:
        trend = views.get(spec.view)
        metric = (trend or {}).get("metric", "rps")
        series = (trend or {}).get("series", {}).get(spec.key)
        tile: dict[str, Any] = {
            "label": spec.label,
            "first": None,
            "last": None,
            "ratio": None,
            "status": "na",
        }
        if series:
            present = [v for v in series if v is not None]
            if present:
                first, last = present[0], present[-1]
                ratio = last / first if first else None
                tile["first"] = _fmt_value(metric, first)
                tile["last"] = _fmt_value(metric, last)
                tile["ratio"] = None if ratio is None else f"{ratio:.2f}x"
                tile["status"] = (
                    "na"
                    if ratio is None
                    else _ratio_status(ratio, spec.lower_is_better)
                )
        kpis.append(tile)
    return kpis


def build_report(
    trend_dir: Path, views: dict[str, dict[str, Any]], identity: str
) -> Path:
    """Write trend-<identity>-<date>-<time>.html plus its res attachments."""
    kpis = collect_kpis(views)
    now = dt.datetime.now()
    base = trend_dir / f"trend-{identity}-{now:%Y%m%d}-{now:%H%M%S}"
    main_path = trend_dir / f"{base.name}.html"
    main_path.write_text(
        render_report_html(now.strftime("%Y%m%d-%H%M%S"), views, kpis), encoding="utf-8"
    )

    res_dir = trend_dir / (base.name + "-res")
    res_dir.mkdir(parents=True, exist_ok=True)
    for view in CHART_VIEWS:
        trend = views.get(view.name)
        if trend is None:
            continue
        svg = render_trend_svg(trend)
        if svg:
            (res_dir / f"{view.name}.svg").write_text(svg, encoding="utf-8")
        (res_dir / f"{view.name}.md").write_text(
            render_trend_markdown(trend), encoding="utf-8"
        )
    return main_path


def _collect_views(settings: Settings) -> dict[str, dict[str, Any]]:
    return {
        view.name: collect_trend(
            settings,
            metric=view.metric,
            interpreter_filter=(),
            workload_filter=view.workloads,
            concs=(),
        )
        for view in CHART_VIEWS
    }


def write_report(trend_dir: Path, settings: Settings) -> Path:
    """Collect every chart view and write the integrated report + attachments."""
    views = _collect_views(settings)
    identity = identity_from_meta(_latest_baseline_meta(settings))
    return build_report(trend_dir, views, identity)


def render_report_html(
    stamp: str, views: dict[str, dict[str, Any]], kpis: list[dict[str, Any]]
) -> str:
    """Render the integrated single-file report (full HTML skeleton)."""
    full = views.get("full-rps", {})
    baselines: list[dict[str, Any]] = full.get("baselines", [])
    baseline_rows = "".join(
        f"<tr><td>{i + 1}</td><td>{html.escape(str(b['name']))}</td>"
        f"<td>{html.escape(str(b.get('saved_at', '')))}</td>"
        f"<td>{html.escape(str(b.get('project_version', '')))}</td>"
        f"<td>{html.escape(str(b.get('git_describe', '')))}</td></tr>"
        for i, b in enumerate(baselines)
    )
    tiles = "".join(
        f'<div class="tile {t["status"]}">'
        f'<div class="label">{html.escape(t["label"])}</div>'
        f'<div class="value">{t["first"] or "n/a"} → {t["last"] or "n/a"}</div>'
        f'<div class="delta">{t["ratio"] or "n/a"} · {_STATUS_TEXT[t["status"]]}</div>'
        f"</div>"
        for t in kpis
    )
    sections = ""
    attachments: list[str] = []
    for view in CHART_VIEWS:
        trend = views.get(view.name)
        svg = render_trend_svg(trend) if trend else ""
        plate = svg or "<p>无数据(基线不足)</p>"
        section_links = ""
        if svg:
            for ext in ("svg", "md"):
                name = f"trend-{stamp}-{view.name}.{ext}"
                section_links += f' <a href="{name}">.{ext}</a>'
                attachments.append(name)
        sections += (
            f'<section id="{html.escape(view.name)}">'
            f"<h2>{html.escape(view.title)} · {view.name}</h2>"
            f'<p class="section-note">{html.escape(view.blurb)}</p>'
            f'<figure><div class="plate">{plate}</div>'
            f"<figcaption>图例编号对应基线序号(见数据与方法),悬停折线数据点可读值。"
            f"{section_links}</figcaption></figure></section>"
        )
    attachment_items = "".join(
        f'<li><a href="{html.escape(a)}">{html.escape(a)}</a></li>' for a in attachments
    )
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>asgi-webdav 性能趋势 {stamp}</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<main>
<h1>asgi-webdav 性能趋势</h1>
<p class="meta">基线 {len(baselines)} 个 · {html.escape(str(full.get("metric_label", "")))} · 生成于 {generated} · 报告号 {stamp}</p>

<h2 id="kpi">关键结论</h2>
<nav class="tiles">{tiles}</nav>

<nav class="toc">
{"".join(f'<a href="#{html.escape(v.name)}">{html.escape(v.title)}</a>' for v in CHART_VIEWS)}
<a href="#method">数据与方法</a>
<a href="#attachments">附属文件</a>
</nav>

{sections}

<h2 id="method">数据与方法</h2>
<div class="scroll">
<table>
<tr><th>#</th><th>基线</th><th>保存时间</th><th>版本</th><th>git</th></tr>
{baseline_rows}
</table>
</div>
<p class="section-note">折线图例编号对应上表序号;组合在某个基线缺失时折线断开,不做插值。</p>
<pre>python -m tools.perf run                    # 全量测量(macOS 腿)
python -m tools.perf vm compat             # VM 兼容腿
python -m tools.perf vm bench              # VM 基准腿
python -m tools.perf baseline save &lt;run_dir&gt; --name &lt;name&gt;
python -m tools.perf report                # 生成本报告并刷新 index.html</pre>

<h2 id="attachments">附属文件</h2>
<ul class="attachments">{attachment_items}</ul>

<footer>由 python -m tools.perf report 生成 · 报告号 {stamp}</footer>
</main>
</body>
</html>
"""
