"""graph, bundle and parallel: the properties the conformance cases cannot see (geometry, determinism, limits, safety)."""

import random
import re
from pathlib import Path

import pytest

from reportspec import charts
from reportspec.cli import main

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "policy-coverage.report.md"
INPUT = ROOT / "examples" / "inputs" / "policy-coverage.jsonl"


def payload(kind: str, **extra):
    base = {"id": "t", "type": kind, "title": "t", "caption": None, "alt": None, "direction": None, "threshold": None, "range": None,
            "display": None, "precision": None, "options": {}}
    return base | extra


def graph_payload(n: int, m: int, seed: int = 1, kind: str = "graph", groups: int = 3, label: str = "Node"):
    rnd = random.Random(seed)
    nodes = [{"id": f"n{i}", "label": f"{label} {i}", "group": f"g{i % groups}" if kind == "bundle" or i % 2 else None, "resolved": True} for i in range(n)]
    links: set[tuple[int, int]] = set()
    while len(links) < m:
        a, b = rnd.randrange(n), rnd.randrange(n)
        if a != b:
            links.add((a, b))
    return payload(kind, graph={"nodes": nodes, "links": [{"source": f"n{a}", "target": f"n{b}"} for a, b in sorted(links)],
                                "directed": kind == "graph", "skipped_links": 0, "unresolved_nodes": 0})


def svg_size(svg: str) -> tuple[float, float]:
    w, h = re.search(r'width="([\d.]+)" height="([\d.]+)"', svg).groups()
    return float(w), float(h)


def symbol_positions(svg: str) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in re.findall(r'transform="translate\(([-\d.]+),([-\d.]+)\)"', svg)]


@pytest.mark.parametrize(("n", "m"), [(10, 9), (25, 30), (50, 70), (80, 120)])
def test_graph_stays_inside_its_frame(n, m):
    """Vega's force layout has no bounds: unfitted, a 25-node graph spilled 260 px outside a 680 px frame."""
    svg = charts.render_payload(graph_payload(n, m)).svg
    w, h = svg_size(svg)
    pts = symbol_positions(svg)
    assert len(pts) >= n
    assert all(0 <= x <= w and 0 <= y <= h for x, y in pts)


def test_graph_nodes_are_not_stacked_at_the_origin():
    """A force transform given a bad field reference fails silently, with NaN positions drawn at (0, 0)."""
    svg = charts.render_payload(graph_payload(12, 11)).svg
    nodes = {p for p in symbol_positions(svg) if p != (0.0, 0.0)}
    assert len(nodes) >= 12
    xs = [x for x, _ in nodes]
    assert max(xs) - min(xs) > 100


@pytest.mark.parametrize("kind", ["graph", "bundle"])
def test_same_input_draws_the_same_svg(kind):
    p = graph_payload(30, 40, kind=kind)
    assert charts.render_payload(p).svg == charts.render_payload(p).svg


def test_bundle_nodes_sit_inside_the_frame():
    svg = charts.render_payload(graph_payload(60, 90, kind="bundle", groups=6)).svg
    w, h = svg_size(svg)
    assert all(0 <= x <= w and 0 <= y <= h for x, y in symbol_positions(svg))


@pytest.mark.parametrize(("kind", "n"), [("graph", 81), ("bundle", 121)])
def test_density_limits_fail_with_a_message(kind, n):
    with pytest.raises(charts.ChartError, match=r"supports up to \d+ nodes"):
        charts.render_payload(graph_payload(n, n // 2, kind=kind))


def test_too_many_groups_fails_with_a_message():
    with pytest.raises(charts.ChartError, match="supports up to 8 groups"):
        charts.render_payload(graph_payload(30, 20, kind="bundle", groups=9))


def test_parallel_limit_is_series():
    series = [{"label": f"s{i}", "values": [0.1 * i, 0.5], "texts": ["a", "b"]} for i in range(9)]
    axes = [{"field": f, "label": f, "lower_is_better": False, "display": None, "precision": None} for f in "ab"]
    with pytest.raises(charts.ChartError, match="up to 8 series"):
        charts.render_payload(payload("parallel", parallel={"axes": axes, "series": series}))


def test_vega_failures_are_chart_errors_not_tracebacks(monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("Vega to SVG conversion failed:\nSyntaxError: Unexpected token ']'\n    at Function")

    monkeypatch.setattr(charts.vlc, "vega_to_svg", boom)
    with pytest.raises(charts.ChartError, match="the chart could not be drawn: SyntaxError"):
        charts.render_payload(graph_payload(5, 4, kind="bundle"))


@pytest.mark.parametrize("kind", ["graph", "bundle"])
def test_hostile_labels_stay_inert(kind):
    p = graph_payload(6, 5, kind=kind, label="<script>alert(1)</script>")
    fig = charts.render_payload(p)
    assert "<script" not in fig.svg and "<foreignObject" not in fig.svg and "onerror" not in fig.svg
    assert "alert(1)" in fig.alt  # present as text, so a screen reader reads it


def test_parallel_breaks_the_line_at_na_and_labels_it():
    axes = [{"field": f, "label": f.upper(), "lower_is_better": f == "b", "display": None, "precision": None} for f in "abc"]
    series = [{"label": "full", "values": [0.1, 0.5, 0.9], "texts": ["0.1", "0.5", "0.9"]},
              {"label": "gappy", "values": [0.3, None, 0.7], "texts": ["0.3", "N/A", "0.7"]}]
    fig = charts.render_payload(payload("parallel", parallel={"axes": axes, "series": series}))
    assert "N/A: gappy" in fig.svg
    assert "1 value not available" in fig.note and "not drawn through zero" in fig.note
    # a run of one point is a dot, not a line: only the full series has a line
    assert fig.svg.count('stroke-width="2.4"') == 1


def test_parallel_flip_puts_better_values_up():
    axes = [{"field": "hi", "label": "hi", "lower_is_better": False, "display": None, "precision": None},
            {"field": "lo", "label": "lo", "lower_is_better": True, "display": None, "precision": None}]
    series = [{"label": "a", "values": [0.0, 0.0], "texts": ["0", "0"]}, {"label": "b", "values": [1.0, 1.0], "texts": ["1", "1"]}]
    svg = charts.render_payload(payload("parallel", parallel={"axes": axes, "series": series})).svg
    lines = re.findall(r'<path d="M([\d.]+),([\d.]+)L([\d.]+),([\d.]+)"[^>]*stroke-width="2.4"', svg)
    assert len(lines) == 2
    a, b = lines  # series a: low on both axes
    # on the normal axis a low value is at the bottom (larger y); on the flipped axis it is at the top
    assert float(a[1]) > float(b[1]) and float(a[3]) < float(b[3])


def test_empty_networks_get_a_labelled_placeholder():
    fig = charts.render_payload(payload("graph", graph={"nodes": [{"id": "a", "label": "a", "group": None, "resolved": True}], "links": [],
                                                        "directed": True, "skipped_links": 2, "unresolved_nodes": 0}))
    assert "No links to draw: 2 not drawable" in fig.svg


def test_policy_coverage_example_renders_all_three(tmp_path):
    out = tmp_path / "pc.html"
    assert main(["render", str(EXAMPLE), "--input", str(INPUT), "--format", "html", "-o", str(out)]) == 0
    html = out.read_text()
    for fig in ("policy-risk-bundle", "attack-flow", "config-parallel"):
        assert fig in html
    assert html.count("<svg") >= 3
    assert "No links to draw" not in html  # the example's own data is wired correctly
