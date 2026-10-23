"""Chart renderer for ReportSpec v1alpha1 (DRAFT): resolved viz payload in, SVG out.

The seam with the rest of the implementation is the payload (schemas/resolved-viz-v1alpha1.schema.json).
Nothing here sees bindings, templates or hosts, so EvalHub and ASAGO can share it.

  bar, line, heatmap, boxplot  Altair builds a Vega-Lite spec
  radar, radial                a Vega spec with the geometry computed here

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

from reportspec_fonts import SANS_STACK, register_with_vl_convert

register_with_vl_convert()
FONT = SANS_STACK  # Red Hat Text, embedded by the document; open fallbacks only
# Theme tokens. Specs state intent (palette, direction); only this module owns colors.
PASS, FAIL, NEUTRAL, NA_TEXT = "#3E8635", "#C9190B", "#0066CC", "#6A6E73"
INK, MUTED, GRID, NA_FILL, THRESHOLD = "#151515", "#6A6E73", "#D2D2D2", "#E0E0E0", "#8A4B00"
BOX_FILL = "#BEE1F4"

VEGA_LITE = "6.4"  # must be in vl_convert.get_vegalite_versions()
RADAR_AXES = (3, 12)
RADIAL_MAX = 8
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


def _note(p: dict[str, Any]) -> str:
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
    return vlc.vega_to_svg(spec, allowed_base_urls=[])


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


# --- Entry point ---------------------------------------------------------------------------------------


_RENDERERS = {"bar": _bar, "line": _line, "heatmap": _heatmap, "boxplot": _boxplot, "radar": _radar, "radial": _radial}


def render_payload(p: dict[str, Any]) -> Figure:
    """Render one resolved viz payload. Raises ChartError when the data cannot be charted legibly."""
    t = p["type"]
    if t not in _RENDERERS:
        raise ChartError(f"no chart renderer for type {t!r}")
    if t == "heatmap" and not p["matrix"]["rows"]:
        return _placeholder(p, "No data available")
    if t == "boxplot" and not any(s["y"] is not None for s in p["samples"]):
        return _placeholder(p, "No data available" if not p["samples"] else "All values are N/A")
    if t not in ("heatmap", "boxplot") and not p["points"]:
        return _placeholder(p, "No data available")
    if t not in ("heatmap", "boxplot") and all(q["value"] is None for q in p["points"]):
        return _placeholder(p, "All values are N/A")
    alt_text = p.get("alt") or _describe(p)
    return Figure(_RENDERERS[t](p), alt_text, _note(p))
