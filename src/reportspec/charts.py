"""Chart renderer for ReportSpec v1alpha1 (DRAFT): resolved viz payload in, SVG out.

The seam with the rest of the implementation is the payload (src/reportspec/schemas/resolved-viz-v1alpha1.schema.json).
Nothing here sees bindings, templates or hosts, so EvalHub and ASAGO can share it.

  bar, line, heatmap, boxplot  Altair builds a Vega-Lite spec
  radar, radial, bundle,       a Vega spec with the geometry computed here
  parallel
  graph                        a Vega spec; Vega's own force transform does the layout (deterministic: same input, same SVG)

Every render goes through vl-convert with allowed_base_urls=[]: a spec can never fetch anything.
N/A (a null value) is never drawn as zero; it is labelled "N/A" in every chart (VISUAL-QA.md, VQA-3).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

import altair as alt
import vl_convert as vlc

from .fontset import SANS_STACK, register_with_vl_convert

register_with_vl_convert()
FONT = SANS_STACK  # Red Hat Text, embedded by the document; open fallbacks only
# Theme tokens. Specs state intent (palette, direction); only this module owns colors.
PASS, FAIL, NEUTRAL, NA_TEXT = "#3E8635", "#C9190B", "#0066CC", "#6A6E73"
INK, MUTED, GRID, NA_FILL, THRESHOLD = "#151515", "#6A6E73", "#D2D2D2", "#E0E0E0", "#8A4B00"
BOX_FILL = "#BEE1F4"

VEGA_LITE = "6.4"  # must be in vl_convert.get_vegalite_versions()
RADAR_AXES = (3, 12)
RADIAL_MAX = 8
GRAPH_MAX = (80, 200)  # nodes, links
BUNDLE_MAX = (120, 400)
PARALLEL_MAX = 8  # series: one palette color each
# Categorical colors for groups and series. No red or green: those mean FAIL and PASS everywhere else in a report.
CATEGORY = ["#0066CC", "#F0AB00", "#009596", "#5752D1", "#EC7A08", "#6A6E73", "#73BCF7", "#8A4B00"]
SHAPES = ["circle", "square", "diamond", "triangle-up", "cross", "triangle-down", "triangle-left", "triangle-right"]  # a second cue besides color
LABEL_LIMIT = 150


class ChartError(Exception):
    pass


@dataclass(frozen=True)
class Figure:
    svg: str
    alt: str
    note: str  # appended to the caption: threshold, direction, N/A count


# --- Helpers -------------------------------------------------------------------------------


def _na_count(p: dict[str, Any]) -> int:
    t = p["type"]
    if t == "heatmap":
        return sum(1 for r in p["matrix"]["rows"] for c in r["cells"] if c["value"] is None)
    if t == "boxplot":
        return sum(1 for s in p["samples"] if s["y"] is None)
    if t == "parallel":
        return sum(1 for sr in p["parallel"]["series"] for v in sr["values"] if v is None)
    if t in ("graph", "bundle"):
        return 0
    return sum(1 for q in p["points"] if q["value"] is None)


def _state(value: float | None, thr: float | None, direction: str | None) -> str:
    if value is None:
        return "na"
    if thr is None or direction not in ("higher_is_better", "lower_is_better"):
        return "neutral"
    ok = value <= thr if direction == "lower_is_better" else value >= thr
    return "pass" if ok else "fail"


def _values(p: dict[str, Any]) -> list[float]:
    t = p["type"]
    if t == "heatmap":
        return [c["value"] for r in p["matrix"]["rows"] for c in r["cells"] if c["value"] is not None]
    if t == "boxplot":
        return [s["y"] for s in p["samples"] if s["y"] is not None]
    return [q["value"] for q in p["points"] if q["value"] is not None]


def _domain(p: dict[str, Any], headroom: float = 0.0) -> tuple[float, float]:
    if p.get("range"):
        return float(p["range"][0]), float(p["range"][1])
    vals = _values(p) + ([p["threshold"]] if p.get("threshold") is not None else [])
    if not vals:
        return 0.0, 1.0
    lo, hi = min(0.0, min(vals)), max(vals)
    if hi == lo:
        hi = lo + 1.0
    return lo, hi + (hi - lo) * headroom


def _fmt(v: float, p: dict[str, Any], prec: int | None = None) -> str:
    d, prec = p.get("display"), prec if prec is not None else p.get("precision")
    if d == "percent":
        return f"{v * 100:.{1 if prec is None else prec}f}%"
    if d == "integer":
        return f"{round(v)}"
    return f"{v:.{prec}f}" if prec is not None else f"{v:.3f}".rstrip("0").rstrip(".")


def _axis_format(p: dict[str, Any]) -> str | None:
    return ".0%" if p.get("display") == "percent" else None


def _axis(title: str | None = None, **kw: Any) -> alt.Axis:
    """No title unless the spec gave one: Altair would otherwise print field names such as "value, t"."""
    return alt.Axis(title=title, **{k: v for k, v in kw.items() if v is not None})


def _short(s: str, n: int = 24) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _note_network(p: dict[str, Any]) -> str:
    t = p["type"]
    if t == "parallel":
        parts = ["Each axis has its own scale, shown at both ends."]
        if any(a["lower_is_better"] for a in p["parallel"]["axes"]):
            parts.append("Axes marked lower is better are flipped: up is always better.")
        n_na = _na_count(p)
        if n_na:
            parts.append(f"N/A: {n_na} value{'s' if n_na != 1 else ''} not available; the line breaks there and is not drawn through zero.")
        return " ".join(parts)
    g = p["graph"]
    parts = [f"{len(g['nodes'])} nodes, {len(g['links'])} links."]
    if t == "graph" and g["directed"]:
        parts.append("Arrows point to the target.")
    if t == "graph":
        parts.append("Layout is computed from the links; position carries no meaning.")
    if g["unresolved_nodes"]:
        n = g["unresolved_nodes"]
        parts.append(f"Hollow: {n} node{'s' if n != 1 else ''} named by a link but missing from the node list.")
    if g["skipped_links"]:
        n = g["skipped_links"]
        parts.append(f"Not drawn: {n} link{'s' if n != 1 else ''} with a missing end, the same node at both ends, or an unknown node.")
    return " ".join(parts)


def _note(p: dict[str, Any]) -> str:
    if p["type"] in ("graph", "bundle", "parallel"):
        return _note_network(p)
    parts: list[str] = []
    thr = p.get("threshold")
    if thr is not None:
        parts.append(f"Dashed line: threshold {_fmt(thr, p)}.")
    if p.get("direction") == "lower_is_better":
        parts.append("Lower is better.")
    elif p.get("direction") == "higher_is_better":
        parts.append("Higher is better.")
    if p["type"] in ("radar", "radial"):
        lo, hi = _domain(p)
        parts.append(f"Scale: {_fmt(lo, p)} at the center to {_fmt(hi, p)} at the outer ring." if p["type"] == "radar" else f"Full ring = {_fmt(hi, p)}.")
    n_na = _na_count(p)
    if n_na:
        parts.append(f"N/A: {n_na} value{'s' if n_na != 1 else ''} not available, not plotted as zero.")
    return " ".join(parts)


def _describe(p: dict[str, Any]) -> str:
    t, head = p["type"], p["title"]
    if t == "heatmap":
        cols = p["matrix"]["columns"]
        rows = "; ".join(
            f"{r['label']}: " + ", ".join(f"{c} {cell['text']}" for c, cell in zip(cols, r["cells"], strict=True))
            for r in p["matrix"]["rows"])
        return f"Heatmap, {head}. {rows}."
    if t == "boxplot":
        out = []
        for g, ys in _groups(p).items():
            out.append(f"{g}: n={len(ys)}, median {_fmt(statistics.median(ys), p)}, min {_fmt(min(ys), p)}, max {_fmt(max(ys), p)}"
                       if ys else f"{g}: no values")
        return f"Box plot, {head}. " + "; ".join(out) + "."
    if t in ("graph", "bundle"):
        g = p["graph"]
        lab = {n["id"]: n["label"] for n in g["nodes"]}
        links = "; ".join(f"{lab[x['source']]} to {lab[x['target']]}" for x in g["links"][:40])
        more = f"; and {len(g['links']) - 40} more" if len(g["links"]) > 40 else ""
        kind = "Force-directed graph" if t == "graph" else "Edge bundling diagram"
        groups = _group_order(g["nodes"])
        grp = f" Groups: {', '.join(groups)}." if groups else ""
        return f"{kind}, {head}. {len(g['nodes'])} nodes and {len(g['links'])} links.{grp} Links: {links or 'none'}{more}."[:2000]
    if t == "parallel":
        ax = p["parallel"]["axes"]
        rows = "; ".join(f"{sr['label']}: " + ", ".join(f"{a['label']} {x}" for a, x in zip(ax, sr["texts"], strict=True)) for sr in p["parallel"]["series"])
        return f"Parallel coordinates, {head}. Axes: {', '.join(a['label'] for a in ax)}. {rows}."[:2000]
    kind = {"bar": "Bar chart", "line": "Line chart", "radar": "Radar chart", "radial": "Radial bar chart"}[t]
    vals = ", ".join(f"{q['label']} {q['text']}" for q in p["points"])
    thr = f" Threshold {_fmt(p['threshold'], p)}." if p.get("threshold") is not None else ""
    return f"{kind}, {head}. {vals}.{thr}"


def _groups(p: dict[str, Any]) -> dict[str, list[float]]:
    g: dict[str, list[float]] = {}
    for s in p["samples"]:
        g.setdefault(s["x"], [])
        if s["y"] is not None:
            g[s["x"]].append(s["y"])
    return g


def _vl_svg(chart: alt.TopLevelMixin) -> str:
    chart = chart.configure(font=FONT).configure_view(stroke=None).configure_axis(
        labelFont=FONT, titleFont=FONT, labelColor=INK, titleColor=INK, gridColor="#EDEDED", domainColor=GRID, tickColor=GRID,
        labelFontSize=11, titleFontSize=11, titleFontWeight="normal").configure_legend(
        labelFont=FONT, titleFont=FONT, labelFontSize=10)
    # Pin the bundled Vega-Lite so output does not change when vl-convert upgrades (VQA-20). Rendering needs
    # no network either way: verified under a deny-network sandbox, the jsdelivr URLs in stack traces are
    # module names inside vl-convert's embedded snapshot, not downloads.
    return vlc.vegalite_to_svg(chart.to_dict(), vl_version=VEGA_LITE, allowed_base_urls=[])


def _vega_svg(spec: dict[str, Any]) -> str:
    try:
        return vlc.vega_to_svg(spec, allowed_base_urls=[])
    except ValueError as e:  # vl-convert reports Vega failures as ValueError with a JavaScript stack
        raise ChartError("the chart could not be drawn: " + str(e).splitlines()[1 if len(str(e).splitlines()) > 1 else 0][:160]) from e


def _placeholder(p: dict[str, Any], reason: str) -> Figure:
    """Degenerate data (VQA-15): a labelled placeholder, never a blank figure."""
    esc = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="520" height="90" viewBox="0 0 520 90">'
           f'<rect x="0.5" y="0.5" width="519" height="89" fill="none" stroke="{GRID}" stroke-dasharray="4 3"/>'
           f'<text x="260" y="50" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{NA_TEXT}">{esc}</text></svg>')
    return Figure(svg, f"{p['title']}: {reason}", "")


# --- Vega-Lite types (Altair) ----------------------------------------------------------------


def _bar(p: dict[str, Any]) -> str:
    horizontal = p["options"].get("orientation") == "horizontal"
    thr, direction = p.get("threshold"), p.get("direction")
    lo, hi = _domain(p, headroom=0.0)
    labels = [q["label"] for q in p["points"]]
    rows = []
    for q in p["points"]:
        st = _state(q["value"], thr, direction)
        suffix = {"pass": " · PASS", "fail": " · FAIL"}.get(st, "")
        rows.append({"label": q["label"], "value": q["value"], "text": q["text"] + suffix, "state": st})
    data = alt.Data(values=rows)
    colors = alt.Scale(domain=["pass", "fail", "neutral"], range=[PASS, FAIL, NEUTRAL])
    scale = alt.Scale(domain=[lo, hi], nice=False, clamp=True)
    val_axis = _axis(title=p["options"].get("y_label") if not horizontal else p["options"].get("x_label"),
                        format=_axis_format(p))
    cat_axis = _axis(title=p["options"].get("x_label") if not horizontal else p["options"].get("y_label"),
                        labelLimit=LABEL_LIMIT * 1.6, labelAngle=0 if horizontal else (-30 if max(map(len, labels)) > 8 else 0))
    n = len(rows)
    width, height = (480, max(60, 30 * n + 30)) if horizontal else (max(260, min(720, 64 * n + 80)), 240)
    pad = {"left": 6, "right": 116 if horizontal else (96 if thr is not None else 10), "top": 22 if thr is not None and horizontal else 10, "bottom": 8}
    cat, val = ("y", "x") if horizontal else ("x", "y")
    enc_cat = (alt.Y if horizontal else alt.X)("label:N", sort=labels, axis=cat_axis)
    enc_val = (alt.X if horizontal else alt.Y)("value:Q", scale=scale, axis=val_axis)
    base = alt.Chart(data)
    bars = base.transform_filter("datum.value !== null").mark_bar(size=18 if horizontal else 34).encode(
        **{cat: enc_cat, val: enc_val}, color=alt.Color("state:N", scale=colors, legend=None))
    if horizontal:
        # A column at the right edge: labels never sit on the threshold line or on a neighbouring bar.
        values = base.transform_filter("datum.value !== null").mark_text(font=FONT, fontSize=11, color=INK, align="left", baseline="middle", dx=10).encode(
            **{cat: enc_cat}, x=alt.value(width), text="text:N")
    else:
        values = base.transform_filter("datum.value !== null").mark_text(font=FONT, fontSize=11, color=INK, baseline="bottom", dy=-4).encode(
            **{cat: enc_cat, val: enc_val}, text="text:N")
    na_kw = {"align": "left", "dx": 4, "baseline": "middle"} if horizontal else {"baseline": "bottom", "dy": -4}
    na_pos = {"x": alt.value(2)} if horizontal else {"y": alt.value(height - 4)}
    na = base.transform_filter("datum.value === null").mark_text(
        font=FONT, fontSize=11, fontStyle="italic", color=NA_TEXT, text="N/A", **na_kw).encode(
        **{cat: enc_cat}, **na_pos)
    layers = [bars, values, na]
    if thr is not None:
        tdata = alt.Data(values=[{"t": thr, "label": f"threshold {_fmt(thr, p)}"}])
        rule_enc = {"x": alt.X("t:Q", scale=scale)} if horizontal else {"y": alt.Y("t:Q", scale=scale)}
        layers.append(alt.Chart(tdata).mark_rule(color=THRESHOLD, strokeDash=[5, 3], strokeWidth=1.5).encode(**rule_enc))
        lab_kw = {"align": "left", "dx": 3}
        lab_pos = {"x": alt.X("t:Q", scale=scale), "y": alt.value(-8)} if horizontal else {"y": alt.Y("t:Q", scale=scale), "x": alt.value(width + 2)}
        layers.append(alt.Chart(tdata).mark_text(font=FONT, fontSize=10, color=THRESHOLD, baseline="bottom", **lab_kw).encode(text="label:N", **lab_pos))
    return _vl_svg(alt.layer(*layers).properties(width=width, height=height, padding=pad))


def _line(p: dict[str, Any]) -> str:
    thr, direction = p.get("threshold"), p.get("direction")
    lo, hi = _domain(p, headroom=0.12)
    labels = [q["label"] for q in p["points"]]
    rows = [{"label": q["label"], "value": q["value"], "text": q["text"], "state": _state(q["value"], thr, direction)} for q in p["points"]]
    data = alt.Data(values=rows)
    scale = alt.Scale(domain=[lo, hi], nice=False, clamp=True)
    x = alt.X("label:N", sort=labels, axis=_axis(title=p["options"].get("x_label"), labelAngle=0 if max(map(len, labels)) <= 8 else -30, labelLimit=LABEL_LIMIT))
    y = alt.Y("value:Q", scale=scale, axis=_axis(title=p["options"].get("y_label"), format=_axis_format(p)))
    base = alt.Chart(data)
    colors = alt.Scale(domain=["pass", "fail", "neutral"], range=[PASS, FAIL, NEUTRAL])
    line = base.mark_line(color=NEUTRAL, strokeWidth=2, interpolate="linear").encode(x=x, y=y)
    pts = base.transform_filter("datum.value !== null").mark_point(filled=True, size=70, opacity=1).encode(
        x=x, y=y, color=alt.Color("state:N", scale=colors, legend=None))
    values = base.transform_filter("datum.value !== null").mark_text(font=FONT, fontSize=11, baseline="bottom", dy=-9, color=INK).encode(x=x, y=y, text="text:N")
    na = base.transform_filter("datum.value === null").mark_text(font=FONT, fontSize=11, fontStyle="italic", color=NA_TEXT, text="N/A", baseline="bottom").encode(
        x=x, y=alt.value(236))
    layers = [line, pts, values, na]
    if thr is not None:
        tdata = alt.Data(values=[{"t": thr, "label": f"threshold {_fmt(thr, p)}"}])
        layers.append(alt.Chart(tdata).mark_rule(color=THRESHOLD, strokeDash=[5, 3], strokeWidth=1.5).encode(y=alt.Y("t:Q", scale=scale)))
        layers.append(alt.Chart(tdata).mark_text(font=FONT, fontSize=10, color=THRESHOLD, baseline="middle", align="left", dx=4).encode(
            y=alt.Y("t:Q", scale=scale), x=alt.value(max(300, min(720, 80 * len(rows) + 80))), text="label:N"))
    return _vl_svg(alt.layer(*layers).properties(width=max(300, min(720, 80 * len(rows) + 80)), height=240,
                                                 padding={"left": 6, "right": 104 if thr is not None else 14, "top": 14, "bottom": 8}))


def _heatmap(p: dict[str, Any]) -> str:
    m = p["matrix"]
    cols = m["columns"]
    lo, hi = _domain(p)
    diverging = p["options"].get("palette") == "diverging"
    mid = p["options"].get("midpoint")
    worse_when_high = p.get("direction") == "lower_is_better"
    rows = []
    for r in m["rows"]:
        for c, cell in zip(cols, r["cells"], strict=True):
            v = cell["value"]
            frac = None if v is None else (min(max(v, lo), hi) - lo) / ((hi - lo) or 1)
            dark_bg = frac is not None and ((frac > 0.55) if not diverging else (frac < 0.12 or frac > 0.88))
            rows.append({"row": r["label"], "col": c, "value": v, "text": cell["text"], "dark": bool(dark_bg)})
    n_r, n_c = len(m["rows"]), len(cols)
    cell_w, cell_h = max(54, min(96, 560 // max(n_c, 1))), 32
    data = alt.Data(values=rows)
    x = alt.X("col:N", sort=cols, axis=_axis(title=p["options"].get("x_label"), orient="top", labelAngle=0 if max(map(len, cols)) <= 9 else -30, labelLimit=LABEL_LIMIT, ticks=False))
    y = alt.Y("row:N", sort=[r["label"] for r in m["rows"]], axis=_axis(title=p["options"].get("y_label"), labelLimit=LABEL_LIMIT * 1.6, ticks=False))
    if diverging:
        scale = alt.Scale(domain=[lo, hi], domainMid=mid if mid is not None else (lo + hi) / 2, scheme="redyellowgreen", reverse=worse_when_high)
    else:
        scale = alt.Scale(type="quantize", domain=[lo, hi], nice=False, zero=False,
                          scheme=alt.SchemeParams(name="oranges" if worse_when_high else "blues", count=5))
    # A discrete legend: WeasyPrint does not paint Vega's gradient legend (found by Visual QA, not by a failed render).
    legend = alt.Legend(title=None, orient="bottom", direction="horizontal", type="symbol", symbolType="square", symbolSize=160,
                        format=_axis_format(p) or ".2~f", labelFontSize=10)
    base = alt.Chart(data)
    cells = base.transform_filter("datum.value !== null").mark_rect(stroke="#FFFFFF", strokeWidth=1).encode(
        x=x, y=y, color=alt.Color("value:Q", scale=scale, legend=legend))
    na_rect = base.transform_filter("datum.value === null").mark_rect(stroke="#FFFFFF", strokeWidth=1, fill=NA_FILL).encode(x=x, y=y)
    na_txt = base.transform_filter("datum.value === null").mark_text(font=FONT, fontSize=10, fontStyle="italic", color=NA_TEXT, text="N/A").encode(x=x, y=y)
    layers = [cells, na_rect, na_txt]
    if p["options"].get("show_values", True):
        layers.append(base.transform_filter("datum.value !== null").mark_text(font=FONT, fontSize=10).encode(
            x=x, y=y, text="text:N", color=alt.condition("datum.dark", alt.value("#FFFFFF"), alt.value(INK))))
    return _vl_svg(alt.layer(*layers).properties(width=cell_w * n_c, height=cell_h * n_r, padding={"left": 6, "right": 8, "top": 6, "bottom": 6}))


def _boxplot(p: dict[str, Any]) -> str:
    groups = _groups(p)
    order = [f"{g} · n={len(ys)}" for g, ys in groups.items()]
    label_of = {g: f"{g} · n={len(ys)}" for g, ys in groups.items()}
    rows = [{"group": label_of[s["x"]], "y": s["y"]} for s in p["samples"] if s["y"] is not None]
    lo, hi = _domain(p, headroom=0.05)
    scale = alt.Scale(domain=[lo, hi], nice=False, clamp=True)
    x = alt.X("group:N", sort=order, axis=_axis(title=p["options"].get("x_label"), labelAngle=0, labelLimit=LABEL_LIMIT + 30))
    y = alt.Y("y:Q", scale=scale, axis=_axis(title=p["options"].get("y_label"), format=_axis_format(p)))
    box = alt.Chart(alt.Data(values=rows)).mark_boxplot(
        extent=1.5, size=46, box={"fill": BOX_FILL, "stroke": NEUTRAL}, median={"color": INK, "size": 46, "strokeWidth": 2},
        rule={"color": NEUTRAL}, ticks={"color": NEUTRAL, "size": 16}, outliers={"color": NEUTRAL, "size": 24}).encode(x=x, y=y)
    layers: list[Any] = [box]
    width = max(300, min(720, 130 * len(order) + 70))
    thr = p.get("threshold")
    if thr is not None:
        tdata = alt.Data(values=[{"t": thr, "label": f"threshold {_fmt(thr, p)}"}])
        layers.append(alt.Chart(tdata).mark_rule(color=THRESHOLD, strokeDash=[5, 3], strokeWidth=1.5).encode(y=alt.Y("t:Q", scale=scale)))
        layers.append(alt.Chart(tdata).mark_text(font=FONT, fontSize=10, color=THRESHOLD, baseline="middle", align="left", dx=4).encode(
            y=alt.Y("t:Q", scale=scale), x=alt.value(width), text="label:N"))
    return _vl_svg(alt.layer(*layers).properties(width=width, height=240, padding={"left": 6, "right": 104 if thr is not None else 14, "top": 14, "bottom": 8}))


# --- Vega types: geometry computed here ------------------------------------------------------------


def _text_mark(source: str, **enc: Any) -> dict[str, Any]:
    base = {"font": {"value": FONT}, "fontSize": {"value": 11}, "fill": {"field": "color"}, "limit": {"value": LABEL_LIMIT + 20}, "lineHeight": {"value": 13}}
    return {"type": "text", "from": {"data": source}, "encode": {"enter": base | enc}}


def _radar(p: dict[str, Any]) -> str:
    pts = p["points"]
    n = len(pts)
    if not RADAR_AXES[0] <= n <= RADAR_AXES[1]:
        raise ChartError(f"radar needs {RADAR_AXES[0]} to {RADAR_AXES[1]} axes, got {n}; use bar or heatmap")
    lo, hi = _domain(p)
    W, H, R = 540, 368, 125
    cx, cy = W / 2, H / 2
    thr, direction = p.get("threshold"), p.get("direction")

    def at(i: int, r: float) -> tuple[float, float]:
        th = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * math.cos(th), cy + r * math.sin(th)

    def radius(v: float) -> float:
        return R * min(max((v - lo) / ((hi - lo) or 1), 0.0), 1.0)

    rings = [{"ring": k, "x": at(i, R * k / 4)[0], "y": at(i, R * k / 4)[1]} for k in range(1, 5) for i in range(n)]
    # The outermost ring is not labelled (it would collide with the top axis label); the caption states the scale.
    ring_labels = [{"x": cx + 4, "y": cy - R * k / 4 - 1, "text": _fmt(lo + (hi - lo) * k / 4, p, 0 if p.get("display") == "percent" else None), "color": MUTED}
                   for k in range(1, 4)]
    spokes = [{"x": cx, "y": cy, "x2": at(i, R)[0], "y2": at(i, R)[1]} for i in range(n)]
    labels, dots = [], []
    for i, q in enumerate(pts):
        x, y = at(i, R + 14)
        c, s = math.cos(-math.pi / 2 + 2 * math.pi * i / n), math.sin(-math.pi / 2 + 2 * math.pi * i / n)
        na = q["value"] is None
        labels.append({"x": x, "y": y, "lines": [_short(q["label"], 26), "N/A" if na else q["text"]], "color": NA_TEXT if na else INK,
                       "align": "left" if c > 0.3 else "right" if c < -0.3 else "center",
                       "baseline": "top" if s > 0.3 else "bottom" if s < -0.3 else "middle"})
        if not na:
            px, py = at(i, radius(q["value"]))
            st = _state(q["value"], thr, direction)
            dots.append({"x": px, "y": py, "color": {"pass": PASS, "fail": FAIL}.get(st, NEUTRAL)})
    # Runs of consecutive defined axes (circular). A run is a polyline; with no N/A it is one closed polygon.
    has_na = any(q["value"] is None for q in pts)
    segs: list[list[int]] = []
    if not has_na:
        segs = [list(range(n))]
    else:
        start = next(i for i in range(n) if pts[i]["value"] is None)
        run: list[int] = []
        for k in range(1, n + 1):
            i = (start + k) % n
            if pts[i]["value"] is None:
                if run:
                    segs.append(run)
                run = []
            else:
                run.append(i)
        if run:
            segs.append(run)
    poly = [{"seg": si, "x": at(i, radius(pts[i]["value"]))[0], "y": at(i, radius(pts[i]["value"]))[1]} for si, run in enumerate(segs) for i in run]
    thr_poly = [{"x": at(i, radius(thr))[0], "y": at(i, radius(thr))[1]} for i in range(n)] if thr is not None else []
    stroke_none = {"value": None}
    grp = lambda data, name, mark: {"type": "group", "from": {"facet": {"data": data, "name": name, "groupby": "seg" if data == "poly" else "ring"}}, "marks": [mark(name)]}  # noqa: E731
    marks: list[dict[str, Any]] = [
        grp("rings", "r", lambda nm: {"type": "line", "from": {"data": nm}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "stroke": {"value": GRID}, "strokeWidth": {"value": 1}, "interpolate": {"value": "linear-closed"}}}}),
        {"type": "rule", "from": {"data": "spokes"}, "encode": {"enter": {"x": {"field": "x"}, "y": {"field": "y"}, "x2": {"field": "x2"}, "y2": {"field": "y2"}, "stroke": {"value": GRID}}}},
        _text_mark("ring_labels", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, fontSize={"value": 9}),
    ]
    if thr_poly:
        marks.append({"type": "line", "from": {"data": "thr"}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "stroke": {"value": THRESHOLD}, "strokeWidth": {"value": 1.5}, "strokeDash": {"value": [5, 3]},
            "interpolate": {"value": "linear-closed"}}}})
    marks.append(grp("poly", "s", lambda nm: {"type": "line", "from": {"data": nm}, "encode": {"enter": {
        "x": {"field": "x"}, "y": {"field": "y"}, "stroke": {"value": NEUTRAL}, "strokeWidth": {"value": 2.5},
        "fill": {"value": NEUTRAL} if not has_na else stroke_none, "fillOpacity": {"value": 0.12},
        "interpolate": {"value": "linear-closed" if not has_na else "linear"}}}}))
    marks += [
        {"type": "symbol", "from": {"data": "dots"}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "size": {"value": 90}, "fill": {"field": "color"}, "stroke": {"value": "#FFFFFF"}, "strokeWidth": {"value": 1.5}}}},
        _text_mark("labels", x={"field": "x"}, y={"field": "y"}, text={"field": "lines"}, align={"field": "align"}, baseline={"field": "baseline"}),
    ]
    spec = {"$schema": "https://vega.github.io/schema/vega/v5.json", "width": W, "height": H, "padding": 6, "autosize": "none",
            "data": [{"name": nm, "values": v} for nm, v in (("rings", rings), ("ring_labels", ring_labels), ("spokes", spokes), ("poly", poly), ("thr", thr_poly), ("dots", dots), ("labels", labels))],
            "marks": marks}
    return _vega_svg(spec)


def _radial(p: dict[str, Any]) -> str:
    pts = p["points"]
    n = len(pts)
    if n > RADIAL_MAX:
        raise ChartError(f"radial supports up to {RADIAL_MAX} items, got {n}; use bar")
    lo, hi = _domain(p)
    R, r0, gap, sweep = 140, 26, 5, 1.5 * math.pi
    cx, cy = 210, R + 12
    W, H = cx + R + 24, 2 * R + 24
    t = (R - r0) / n - gap
    thr, direction = p.get("threshold"), p.get("direction")
    tracks, vals, labels = [], [], []
    for i, q in enumerate(pts):
        outer = R - i * (t + gap)
        inner = outer - t
        tracks.append({"inner": inner, "outer": outer})
        na = q["value"] is None
        if not na:
            frac = min(max((q["value"] - lo) / ((hi - lo) or 1), 0.0), 1.0)
            st = _state(q["value"], thr, direction)
            vals.append({"inner": inner, "outer": outer, "end": sweep * frac, "color": {"pass": PASS, "fail": FAIL}.get(st, NEUTRAL)})
        suffix = "" if na else {"pass": " · PASS", "fail": " · FAIL"}.get(_state(q["value"], thr, direction), "")
        labels.append({"x": cx - 8, "y": cy - (inner + outer) / 2, "text": f"{_short(q['label'], 24)}   {'N/A' if na else q['text'] + suffix}", "color": NA_TEXT if na else INK})
    ticks = []
    if thr is not None:
        a = sweep * min(max((thr - lo) / ((hi - lo) or 1), 0.0), 1.0)
        sa, ca = math.sin(a), math.cos(a)
        ticks.append({"x": cx + (r0 - 4) * sa, "y": cy - (r0 - 4) * ca, "x2": cx + (R + 6) * sa, "y2": cy - (R + 6) * ca,
                      "lx": cx + (R + 12) * sa, "ly": cy - (R + 12) * ca, "text": f"threshold {_fmt(thr, p)}",
                      "align": "right" if sa < -0.3 else "left" if sa > 0.3 else "center", "baseline": "top" if ca < -0.3 else "bottom" if ca > 0.3 else "middle"})
    marks: list[dict[str, Any]] = [
        {"type": "arc", "from": {"data": "tracks"}, "encode": {"enter": {"x": {"value": cx}, "y": {"value": cy}, "innerRadius": {"field": "inner"}, "outerRadius": {"field": "outer"},
                                                                       "startAngle": {"value": 0}, "endAngle": {"value": sweep}, "fill": {"value": "#EDEDED"}}}},
        {"type": "arc", "from": {"data": "vals"}, "encode": {"enter": {"x": {"value": cx}, "y": {"value": cy}, "innerRadius": {"field": "inner"}, "outerRadius": {"field": "outer"},
                                                                     "startAngle": {"value": 0}, "endAngle": {"field": "end"}, "fill": {"field": "color"}}}},
        _text_mark("labels", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, align={"value": "right"}, baseline={"value": "middle"}),
    ]
    if ticks:
        marks += [
            {"type": "rule", "from": {"data": "ticks"}, "encode": {"enter": {"x": {"field": "x"}, "y": {"field": "y"}, "x2": {"field": "x2"}, "y2": {"field": "y2"},
                                                                           "stroke": {"value": THRESHOLD}, "strokeWidth": {"value": 1.5}, "strokeDash": {"value": [4, 3]}}}},
            {"type": "text", "from": {"data": "ticks"}, "encode": {"enter": {"x": {"field": "lx"}, "y": {"field": "ly"}, "text": {"field": "text"}, "font": {"value": FONT}, "fontSize": {"value": 10},
                                                                            "fill": {"value": THRESHOLD}, "align": {"field": "align"}, "baseline": {"field": "baseline"}}}},
        ]
    spec = {"$schema": "https://vega.github.io/schema/vega/v5.json", "width": W, "height": H, "padding": 6, "autosize": "none",
            "data": [{"name": nm, "values": v} for nm, v in (("tracks", tracks), ("vals", vals), ("labels", labels), ("ticks", ticks))], "marks": marks}
    return _vega_svg(spec)


# --- Network and multi-axis types: graph, bundle, parallel -----------------------------------------------


def _group_order(nodes: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for n in nodes:
        if n["group"] is not None and n["group"] not in seen:
            seen.append(n["group"])
    return seen


def _legend(entries: list[dict[str, Any]], width: float, y0: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """A legend laid out here, row by row. Vega would place its own outside the frame and lose it from the SVG bounds."""
    syms: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    x, y, row = 6.0, y0, 18.0
    for e in entries:
        label = _short(e["label"], 30)
        w = 20 + 6.3 * len(label) + 16
        if x + w > width and x > 6.0:
            x, y = 6.0, y + row
        hollow = e.get("hollow", False)
        syms.append({"x": x + 6, "y": y, "shape": e["shape"], "fill": "#FFFFFF" if hollow else e["color"],
                     "stroke": e["color"] if hollow else "#FFFFFF", "dash": [3, 2] if hollow else [1, 0]})
        texts.append({"x": x + 17, "y": y, "text": label, "color": INK})
        x += w
    return syms, texts, (y - y0) + row


def _legend_marks() -> list[dict[str, Any]]:
    return [
        {"type": "symbol", "from": {"data": "legend_sym"}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "shape": {"field": "shape"}, "size": {"value": 90}, "fill": {"field": "fill"},
            "stroke": {"field": "stroke"}, "strokeWidth": {"value": 1.5}, "strokeDash": {"field": "dash"}}}},
        _text_mark("legend_txt", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, fontSize={"value": 10}, baseline={"value": "middle"}, align={"value": "left"}),
    ]


def _group_legend(groups: list[str], extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [{"label": name, "color": CATEGORY[i], "shape": SHAPES[i]} for i, name in enumerate(groups)] + (extra or [])


def _check_groups(kind: str, groups: list[str]) -> None:
    if len(groups) > len(CATEGORY):
        raise ChartError(f"{kind} supports up to {len(CATEGORY)} groups, got {len(groups)}; merge groups or filter the records")


def _data(**sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": k, "values": v} for k, v in sets.items()]


def _force_layout(n: int, links: list[tuple[int, int]], w: float, h: float) -> list[tuple[float, float]]:
    """Positions from Vega's force transform (d3-force: deterministic, no random seed). The simulation runs once, to completion
    (static), and the node positions are read back from the scenegraph, so the drawing can be fitted to the frame afterwards:
    a force layout has no bounds of its own and spills far outside the frame from about 25 nodes."""
    spec = {"$schema": "https://vega.github.io/schema/vega/v5.json", "width": w, "height": h, "padding": 0, "autosize": "none",
            "data": _data(nodes_in=[{"cx": w / 2, "cy": h / 2} for _ in range(n)], links=[{"source": a, "target": b} for a, b in links]),
            "marks": [{"name": "nodes", "type": "symbol", "from": {"data": "nodes_in"}, "transform": [{
                "type": "force", "iterations": 300, "static": True, "forces": [
                    {"force": "center", "x": w / 2, "y": h / 2}, {"force": "x", "x": "datum.cx", "strength": 0.08}, {"force": "y", "y": "datum.cy", "strength": 0.12},
                    {"force": "collide", "radius": 34}, {"force": "nbody", "strength": -520}, {"force": "link", "links": "links", "distance": 105}]}]}]}
    try:
        graph = vlc.vega_to_scenegraph(spec, allowed_base_urls=[])
    except ValueError as e:
        raise ChartError("the graph layout failed: " + str(e).splitlines()[-1][:160]) from e
    stack = [graph]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get("name") == "nodes" and "items" in o:
                pts = [(float(it["x"]), float(it["y"])) for it in o["items"]]
                if len(pts) == n and all(math.isfinite(x) and math.isfinite(y) for x, y in pts):
                    return pts
                raise ChartError("the graph layout did not converge")
            stack += [v for v in o.values() if isinstance(v, dict | list)]
        elif isinstance(o, list):
            stack += [v for v in o if isinstance(v, dict | list)]
    raise ChartError("the graph layout produced no nodes")


def _graph(p: dict[str, Any]) -> str:
    g = p["graph"]
    nodes, links = g["nodes"], g["links"]
    if len(nodes) > GRAPH_MAX[0] or len(links) > GRAPH_MAX[1]:
        raise ChartError(f"graph supports up to {GRAPH_MAX[0]} nodes and {GRAPH_MAX[1]} links, got {len(nodes)} and {len(links)}; filter the records or use a table")
    groups = _group_order(nodes)
    _check_groups("graph", groups)
    gi = {name: i for i, name in enumerate(groups)}
    index = {n["id"]: i for i, n in enumerate(nodes)}
    W, H, LABEL = 680, 420, 170
    raw = _force_layout(len(nodes), [(index[x["source"]], index[x["target"]]) for x in links], W, H)
    xs, ys = [x for x, _ in raw], [y for _, y in raw]
    x0, y0 = min(xs), min(ys)
    bw, bh = max(max(xs) - x0, 1.0), max(max(ys) - y0, 1.0)
    pad_l, pad_t, avail_w, avail_h = 24.0, 20.0, W - 24.0 - LABEL, H - 40.0
    k = min(avail_w / bw, avail_h / bh, 1.5)  # one scale for both axes: distances keep their meaning
    ox, oy = pad_l + (avail_w - bw * k) / 2, pad_t + (avail_h - bh * k) / 2
    pos = [(ox + (x - x0) * k, oy + (y - y0) * k) for x, y in raw]
    small = len(nodes) > 30
    rows = []
    for n, (x, y) in zip(nodes, pos, strict=True):
        i = gi.get(n["group"], 0)
        color = CATEGORY[i] if n["resolved"] else NA_TEXT
        rows.append({"x": x, "y": y, "label": _short(n["label"], 30), "shape": SHAPES[i], "fill": color if n["resolved"] else "#FFFFFF",
                     "stroke": "#FFFFFF" if n["resolved"] else color, "sw": 1.2 if n["resolved"] else 1.8, "dash": [1, 0] if n["resolved"] else [3, 2]})
    lines, wings = [], []
    wc, ws = math.cos(math.radians(26)), math.sin(math.radians(26))
    for ln in links:
        (sx, sy), (tx, ty) = pos[index[ln["source"]]], pos[index[ln["target"]]]
        d = math.hypot(tx - sx, ty - sy)
        if not g["directed"] or d < 26:
            lines.append({"x": sx, "y": sy, "x2": tx, "y2": ty})
            continue
        ux, uy = (tx - sx) / d, (ty - sy) / d
        px, py = tx - 12 * ux, ty - 12 * uy  # the arrow tip, just outside the target node
        lines.append({"x": sx, "y": sy, "x2": px, "y2": py})
        for sg in (1, -1):
            wings.append({"x": px, "y": py, "x2": px - 8 * (ux * wc - sg * ws * uy), "y2": py - 8 * (sg * ws * ux + uy * wc)})
    extra = [{"label": "not in node list", "color": NA_TEXT, "shape": "circle", "hollow": True}] if g["unresolved_nodes"] else []
    entries = _group_legend(groups, extra)
    syms, texts, lh = _legend(entries, W, H + 12) if entries else ([], [], 0.0)
    rule = lambda data, color, width, **kw: {"type": "rule", "from": {"data": data}, "interactive": False, "encode": {"enter": {  # noqa: E731
        "x": {"field": "x"}, "y": {"field": "y"}, "x2": {"field": "x2"}, "y2": {"field": "y2"}, "stroke": {"value": color}, "strokeWidth": {"value": width}, **kw}}}
    marks: list[dict[str, Any]] = [
        rule("lines", "#8A8D90", 1.4),
        *([rule("wings", "#6A6E73", 1.8, strokeCap={"value": "round"})] if wings else []),
        {"type": "symbol", "from": {"data": "nodes"}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "size": {"value": 140 if small else 280}, "shape": {"field": "shape"}, "fill": {"field": "fill"},
            "stroke": {"field": "stroke"}, "strokeWidth": {"field": "sw"}, "strokeDash": {"field": "dash"}}}},
        _text_mark("nodes", x={"field": "x"}, y={"field": "y"}, text={"field": "label"}, fontSize={"value": 9 if small else 10}, dx={"value": 9 if small else 11},
                   baseline={"value": "middle"}, fill={"value": INK}, limit={"value": LABEL}),
        *(_legend_marks() if entries else []),
    ]
    spec = {"$schema": "https://vega.github.io/schema/vega/v5.json", "width": W, "height": H + 12 + lh, "padding": 6, "autosize": "none",
            "data": _data(nodes=rows, lines=lines, wings=wings, legend_sym=syms, legend_txt=texts), "marks": marks}
    return _vega_svg(spec)


def _bundle(p: dict[str, Any]) -> str:
    """Hierarchical edge bundling: nodes on a circle, grouped; each link is pulled through its group nodes and the center."""
    g, tension = p["graph"], p["options"].get("tension", 0.85)
    nodes, links = g["nodes"], g["links"]
    if len(nodes) > BUNDLE_MAX[0] or len(links) > BUNDLE_MAX[1]:
        raise ChartError(f"bundle supports up to {BUNDLE_MAX[0]} nodes and {BUNDLE_MAX[1]} links, got {len(nodes)} and {len(links)}; filter the records or use a heatmap")
    groups = _group_order(nodes)
    _check_groups("bundle", groups)
    gi = {name: i for i, name in enumerate(groups)}
    R, M = 150, 135
    cx = cy = R + M
    ordered = [n for name in groups for n in nodes if n["group"] == name]
    total = len(ordered) + len(groups)  # one empty slot between groups
    pos: dict[str, tuple[float, float, float]] = {}
    grp_angles: dict[str, list[float]] = {name: [] for name in groups}
    slot = 0
    for name in groups:
        for n in ordered:
            if n["group"] != name:
                continue
            a = 2 * math.pi * slot / total - math.pi / 2
            pos[n["id"]] = (cx + R * math.cos(a), cy + R * math.sin(a), a)
            grp_angles[name].append(a)
            slot += 1
        slot += 1
    ring = {name: (cx + 0.45 * R * math.cos(sum(a) / len(a)), cy + 0.45 * R * math.sin(sum(a) / len(a))) for name, a in grp_angles.items()}
    group_of = {n["id"]: n["group"] for n in nodes}
    paths = []
    for k, ln in enumerate(links):
        gs, gt = group_of[ln["source"]], group_of[ln["target"]]
        pts = [pos[ln["source"]][:2], ring[gs], *([(cx, cy)] if gs != gt else []), *([ring[gt]] if gs != gt else []), pos[ln["target"]][:2]]
        if gs == gt:
            pts = [pos[ln["source"]][:2], ring[gs], pos[ln["target"]][:2]]
        paths += [{"seg": k, "x": x, "y": y, "color": CATEGORY[gi[gs]]} for x, y in pts]
    dots = [{"x": pos[n["id"]][0], "y": pos[n["id"]][1], "shape": SHAPES[gi[n["group"]]], "color": CATEGORY[gi[n["group"]]]} for n in nodes]
    labels = []
    for n in nodes:
        x, y, a = pos[n["id"]]
        right = math.cos(a) >= 0
        labels.append({"x": cx + (R + 12) * math.cos(a), "y": cy + (R + 12) * math.sin(a), "text": _short(n["label"], 24), "color": INK,
                       "angle": math.degrees(a) + (0 if right else 180), "align": "left" if right else "right"})
    syms, texts, lh = _legend(_group_legend(groups), 2 * cx, 2 * cy + 6)
    marks: list[dict[str, Any]] = [
        {"type": "group", "from": {"facet": {"data": "paths", "name": "seg", "groupby": "seg"}}, "marks": [
            {"type": "line", "from": {"data": "seg"}, "interactive": False, "encode": {"update": {
                "x": {"field": "x"}, "y": {"field": "y"}, "stroke": {"field": "color"}, "strokeWidth": {"value": 1.5}, "strokeOpacity": {"value": 0.55},
                "interpolate": {"value": "bundle"}, "tension": {"value": tension}}}}]},
        {"type": "symbol", "from": {"data": "dots"}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "shape": {"field": "shape"}, "size": {"value": 90}, "fill": {"field": "color"},
            "stroke": {"value": "#FFFFFF"}, "strokeWidth": {"value": 1}}}},
        _text_mark("labels", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, fontSize={"value": 10}, align={"field": "align"},
                   baseline={"value": "middle"}, angle={"field": "angle"}),
        *_legend_marks(),
    ]
    spec = {"$schema": "https://vega.github.io/schema/vega/v5.json", "width": 2 * cx, "height": 2 * cy + 6 + lh, "padding": 6, "autosize": "none",
            "data": _data(paths=paths, dots=dots, labels=labels, legend_sym=syms, legend_txt=texts), "marks": marks}
    return _vega_svg(spec)


def _parallel(p: dict[str, Any]) -> str:
    pl = p["parallel"]
    axes, series = pl["axes"], pl["series"]
    if len(series) > PARALLEL_MAX:
        raise ChartError(f"parallel supports up to {PARALLEL_MAX} series, got {len(series)}; filter the records or use a heatmap")
    n = len(axes)
    W = int(max(440, min(760, 130 * (n - 1) + 130)))
    X0, X1, Y0, Y1 = 65, W - 65, 74, 274
    xs = [X0 + i * (X1 - X0) / (n - 1) for i in range(n)]
    rng = p.get("range")
    doms: list[tuple[float, float]] = []
    for i in range(n):
        vals = [sr["values"][i] for sr in series if sr["values"][i] is not None]
        lo, hi = (float(rng[0]), float(rng[1])) if rng else ((min(vals), max(vals)) if vals else (0.0, 1.0))
        if hi == lo:
            pad = abs(lo) * 0.5 or 0.5
            lo, hi = lo - pad, hi + pad
        doms.append((lo, hi))

    def y_of(i: int, v: float) -> float:
        lo, hi = doms[i]
        f = (v - lo) / (hi - lo)
        return Y0 + f * (Y1 - Y0) if axes[i]["lower_is_better"] else Y1 - f * (Y1 - Y0)

    rules, titles, ticks, nas, segs, pts = [], [], [], [], [], []
    for i, a in enumerate(axes):
        f = {"display": a["display"], "precision": a["precision"]}
        lo, hi = doms[i]
        top, bottom = (lo, hi) if a["lower_is_better"] else (hi, lo)
        rules.append({"x": xs[i], "y": Y0, "y2": Y1})
        titles.append({"x": xs[i], "y": Y0 - 42, "text": _short(a["label"], 20), "color": INK, "weight": "bold"})
        if a["lower_is_better"]:
            titles.append({"x": xs[i], "y": Y0 - 29, "text": "lower is better", "color": MUTED, "weight": "normal"})
        ticks += [{"x": xs[i], "y": Y0 - 12, "text": _fmt(top, f), "color": MUTED}, {"x": xs[i], "y": Y1 + 14, "text": _fmt(bottom, f), "color": MUTED}]
        gone = [sr["label"] for sr in series if sr["values"][i] is None]
        if gone:
            nas.append({"x": xs[i], "y": Y1 + 32, "text": "N/A: " + _short(", ".join(gone), 18), "color": NA_TEXT})
    for si, sr in enumerate(series):
        run: list[tuple[float, float]] = []
        runs: list[list[tuple[float, float]]] = []
        for i, v in enumerate(sr["values"]):
            if v is None:
                if run:
                    runs.append(run)
                run = []
            else:
                run.append((xs[i], y_of(i, v)))
                pts.append({"x": xs[i], "y": y_of(i, v), "color": CATEGORY[si]})
        if run:
            runs.append(run)
        segs += [{"seg": f"{si}-{k}", "x": x, "y": y, "color": CATEGORY[si]} for k, r in enumerate(runs) if len(r) > 1 for x, y in r]
    syms, texts, lh = _legend([{"label": sr["label"], "color": CATEGORY[i], "shape": "circle"} for i, sr in enumerate(series)], W, Y1 + 52)
    marks: list[dict[str, Any]] = [
        {"type": "rule", "from": {"data": "rules"}, "encode": {"enter": {"x": {"field": "x"}, "y": {"field": "y"}, "y2": {"field": "y2"}, "stroke": {"value": MUTED}, "strokeWidth": {"value": 1.5}}}},
        {"type": "group", "from": {"facet": {"data": "segs", "name": "seg", "groupby": "seg"}}, "marks": [
            {"type": "line", "from": {"data": "seg"}, "interactive": False, "encode": {"enter": {
                "x": {"field": "x"}, "y": {"field": "y"}, "stroke": {"field": "color"}, "strokeWidth": {"value": 2.4}, "strokeOpacity": {"value": 0.9}, "interpolate": {"value": "linear"}}}}]},
        {"type": "symbol", "from": {"data": "pts"}, "encode": {"enter": {
            "x": {"field": "x"}, "y": {"field": "y"}, "size": {"value": 60}, "fill": {"field": "color"}, "stroke": {"value": "#FFFFFF"}, "strokeWidth": {"value": 1}}}},
        _text_mark("titles", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, align={"value": "center"}, baseline={"value": "middle"}, fontWeight={"field": "weight"}),
        _text_mark("ticks", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, align={"value": "center"}, baseline={"value": "middle"}, fontSize={"value": 10}),
        _text_mark("nas", x={"field": "x"}, y={"field": "y"}, text={"field": "text"}, align={"value": "center"}, baseline={"value": "middle"}, fontSize={"value": 10}, fontStyle={"value": "italic"}),
        *_legend_marks(),
    ]
    spec = {"$schema": "https://vega.github.io/schema/vega/v5.json", "width": W, "height": Y1 + 52 + lh, "padding": 6, "autosize": "none",
            "data": _data(rules=rules, segs=segs, pts=pts, titles=titles, ticks=ticks, nas=nas, legend_sym=syms, legend_txt=texts), "marks": marks}
    return _vega_svg(spec)


# --- Entry point ---------------------------------------------------------------------------------------


_RENDERERS = {"bar": _bar, "line": _line, "heatmap": _heatmap, "boxplot": _boxplot, "radar": _radar, "radial": _radial,
              "graph": _graph, "bundle": _bundle, "parallel": _parallel}


def render_payload(p: dict[str, Any]) -> Figure:
    """Render one resolved viz payload. Raises ChartError when the data cannot be charted legibly."""
    t = p["type"]
    if t not in _RENDERERS:
        raise ChartError(f"no chart renderer for type {t!r}")
    if t == "heatmap" and not p["matrix"]["rows"]:
        return _placeholder(p, "No data available")
    if t == "boxplot" and not any(s["y"] is not None for s in p["samples"]):
        return _placeholder(p, "No data available" if not p["samples"] else "All values are N/A")
    if t in ("graph", "bundle") and not p["graph"]["nodes"]:
        return _placeholder(p, "No data available")
    if t in ("graph", "bundle") and not p["graph"]["links"]:
        return _placeholder(p, "No links to draw" + (f": {p['graph']['skipped_links']} not drawable" if p["graph"]["skipped_links"] else ""))
    if t == "parallel" and not p["parallel"]["series"]:
        return _placeholder(p, "No data available")
    if t == "parallel" and all(v is None for sr in p["parallel"]["series"] for v in sr["values"]):
        return _placeholder(p, "All values are N/A")
    if t not in ("heatmap", "boxplot", "graph", "bundle", "parallel") and not p["points"]:
        return _placeholder(p, "No data available")
    if t not in ("heatmap", "boxplot", "graph", "bundle", "parallel") and all(q["value"] is None for q in p["points"]):
        return _placeholder(p, "All values are N/A")
    alt_text = p.get("alt") or _describe(p)
    return Figure(_RENDERERS[t](p), alt_text, _note(p))
