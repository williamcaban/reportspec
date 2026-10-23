"""HTML and PDF assembly for ReportSpec v1alpha1 (DRAFT).

Input is Markdown that already went through the template engine, with each chart block replaced by a
placeholder paragraph (FIG_TOKEN), plus the rendered figures. Output is one self-contained HTML file
(inline SVG, inline CSS, no external requests) and, from it, a PDF.

Raw HTML in the Markdown is switched off (html=False): results are untrusted, and the template author
gets Markdown, not markup. Figures are inserted after the Markdown pass, so nothing in the SVG can be
reinterpreted as Markdown, and nothing in the Markdown can reach the SVG.
"""

from __future__ import annotations

import html as htmllib
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup

from reportspec_fonts import MONO_STACK, SANS_STACK, font_face_css

FIG_TOKEN = "@@RS-FIG:{}@@"
FIG_RE = re.compile(r"<p>@@RS-FIG:([a-z][a-z0-9-]*)@@</p>")
BADGE_RE = re.compile(r"<td([^>]*)>(PASS|FAIL)</td>")
ICON_DIR = Path(__file__).parent / "icons"
ICON_FILES = {"PASS": "circle-check.svg", "FAIL": "circle-xmark.svg"}  # Font Awesome Free (icons: CC BY 4.0), see icons/LICENSE.txt


@lru_cache(maxsize=None)
def _icon(word: str) -> str:
    """Inline SVG icon for a badge. Glyphs would depend on the font (Red Hat Text has no check or cross), so icons are SVG."""
    svg = (ICON_DIR / ICON_FILES[word]).read_text()
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)  # attribution is printed once, in the Evidence footer
    return svg.replace("<svg ", '<svg class="ic" aria-hidden="true" ', 1)

H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>\s*", re.S)

CSS = """
:root{--ink:#151515;--muted:#6a6e73;--rule:#d2d2d2;--soft:#f5f5f5;--accent:#0066cc;--pass:#1e4f18;--pass-bg:#e7f5e2;--fail:#7d1007;--fail-bg:#fce8e6}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);background:#fff;font:15px/1.55 __SANS__}
.report{max-width:900px;margin:0 auto;padding:32px 28px 64px}
.cover{border-bottom:3px solid var(--ink);padding-bottom:14px;margin-bottom:22px}
.cover h1{font-size:30px;line-height:1.15;margin:0 0 6px}
.cover .subtitle{font-size:17px;color:var(--muted);margin:0 0 8px}
.cover .meta{font-size:12.5px;color:var(--muted);margin:0}
.cover .tags span{display:inline-block;border:1px solid var(--rule);border-radius:10px;padding:0 8px;margin:6px 6px 0 0;font-size:11.5px;color:var(--muted)}
h2{font-size:21px;margin:30px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--rule)}
h3{font-size:16.5px;margin:22px 0 6px}
p,li{max-width:74ch}
code{font:12.5px/1.4 __MONO__;background:var(--soft);padding:1px 4px;border-radius:3px}
blockquote{margin:14px 0;padding:8px 14px;border-left:4px solid var(--accent);background:var(--soft)}
blockquote p{margin:4px 0}
table{border-collapse:collapse;margin:12px 0;font-size:13.5px;width:100%}
th,td{border-bottom:1px solid var(--rule);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600;border-bottom:2px solid var(--ink)}
.badge .ic{width:.95em;height:.95em;vertical-align:-.14em;margin-right:.3em;fill:currentColor}
.badge{display:inline-block;padding:0 9px;border-radius:10px;font-weight:700;font-size:11.5px;letter-spacing:.03em;border:1px solid}
.badge.pass{color:var(--pass);background:var(--pass-bg);border-color:var(--pass)}
.badge.fail{color:var(--fail);background:var(--fail-bg);border-color:var(--fail)}
figure.viz{margin:18px 0;padding:12px 14px;border:1px solid var(--rule);border-radius:6px;break-inside:avoid}
figure.viz figcaption.title{font-weight:600;margin:0 0 6px}
figure.viz .chart{overflow-x:auto}
figure.viz svg{max-width:100%;height:auto;display:block;margin:0 auto}
figure.viz .note{font-size:12px;color:var(--muted);margin:8px 0 0}
.toc{background:var(--soft);border-radius:6px;padding:8px 18px;margin:0 0 20px;font-size:14px}
.toc ol{margin:4px 0;padding-left:0;list-style:none}.toc li.l3{margin-left:18px;font-size:13px}
.toc h2{font-size:14px;border:0;margin:6px 0 2px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
section.evidence{margin-top:40px;padding-top:6px;border-top:3px solid var(--ink);font-size:12.5px;color:#3c3f42}
section.evidence h2{font-size:15px;border:0;margin:10px 0 4px}
section.evidence table{font-size:12px}
section.evidence .credits{font-size:11px;color:var(--muted)}
@page{size:__PAGE__;margin:16mm 15mm 18mm;@bottom-center{content:counter(page) " / " counter(pages);font:9px __SANS__;color:#6a6e73}}
@media print{
  body{font-size:10.5pt;line-height:1.45}.report{max-width:none;padding:0}
  h2,h3{break-after:avoid}figure.viz{break-inside:avoid}table{font-size:9.5pt}thead{display:table-header-group}tr{break-inside:avoid}
  .badge{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

PAGE = Environment(autoescape=select_autoescape(default=True)).from_string("""<!doctype html>
<html lang="{{ lang }}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>{% if authors %}<meta name="author" content="{{ authors | join(', ') }}">{% endif %}
<meta name="generator" content="reportspec reference implementation (v1alpha1 DRAFT)">
<style>{{ css }}</style></head>
<body><main class="report">
<header class="cover"><h1>{{ title }}</h1>{% if subtitle %}<p class="subtitle">{{ subtitle }}</p>{% endif %}
<p class="meta">{{ meta_line }}</p>{% if tags %}<p class="tags">{% for t in tags %}<span>{{ t }}</span>{% endfor %}</p>{% endif %}</header>
{% if toc %}<nav class="toc"><h2>Contents</h2><ol>{% for level, text, slug in toc %}<li class="l{{ level }}"><a href="#{{ slug }}">{{ text }}</a></li>{% endfor %}</ol></nav>{% endif %}
<article>{{ body }}</article>
<section class="evidence"><h2>Evidence</h2>
<p>Spec <code>{{ ev.spec_name }}</code> v{{ ev.spec_version }} ({{ ev.spec_digest }}), generated {{ ev.generated_at }}. Verdicts come from the producers of the results, not from this renderer.</p>
<p class="credits">Fonts: Red Hat Text and Red Hat Mono (SIL OFL 1.1). Status icons: Font Awesome Free by Fonticons, Inc. (CC BY 4.0).</p>
{% if ev.sources %}<table><thead><tr><th>Source</th><th>Adapter</th><th>SHA-256</th><th>Evaluations</th></tr></thead><tbody>
{% for s in ev.sources %}<tr><td>{{ s.uri }}</td><td>{{ s.adapter }}</td><td><code>{{ s.digest[7:23] }}</code></td><td>{{ s.evaluations | join(', ') }}</td></tr>{% endfor %}</tbody></table>{% endif %}
{% if ev.warnings %}<p><strong>Warnings</strong></p><ul>{% for w in ev.warnings %}<li>{{ w }}</li>{% endfor %}</ul>{% endif %}
</section></main></body></html>""")


def _slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}-{n}", n + 1
    used.add(slug)
    return slug


def markdown_to_html(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Markdown to HTML with raw HTML disabled. Returns the HTML and the h2/h3 outline for the TOC."""
    mdi = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = mdi.parse(md)
    outline: list[tuple[int, str, str]] = []
    used: set[str] = set()
    for i, t in enumerate(tokens):
        if t.type != "heading_open":
            continue
        inline = tokens[i + 1]
        text = "".join(c.content for c in (inline.children or []) if c.type in ("text", "code_inline")) or inline.content
        slug = _slug(text, used)
        t.attrSet("id", slug)
        if t.tag in ("h2", "h3"):
            outline.append((int(t.tag[1]), text, slug))
    return mdi.renderer.render(tokens, mdi.options, {}), outline


def figure_html(number: int, vid: str, vtype: str, title: str, caption: str | None, svg: str, alt: str, note: str) -> str:
    esc = htmllib.escape
    cap = f'<p class="note">{esc(caption)}</p>' if caption else ""
    nt = f'<p class="note">{esc(note)}</p>' if note else ""
    return (f'<figure class="viz viz-{esc(vtype)}" id="viz-{esc(vid)}"><figcaption class="title">Figure {number}. {esc(title)}</figcaption>'
            f'<div class="chart" role="img" aria-label="{esc(alt, quote=True)}">{svg}</div>{cap}{nt}</figure>')


def build_html(md_html: str, figures: dict[str, str], fm: dict[str, Any], report: dict[str, Any],
               evidence: dict[str, Any], *, toc: bool, page: str = "Letter") -> str:
    body, outline = markdown_to_html(md_html)
    title = str(fm.get("title", report["spec_name"]))
    # The cover carries the title, so drop the body's own leading h1 when it repeats it.
    m = H1_RE.match(body)
    if m and htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() == title.strip():
        body = body[m.end():]
    body = FIG_RE.sub(lambda mm: figures.get(mm.group(1), mm.group(0)), body)
    body = BADGE_RE.sub(lambda mm: f'<td{mm.group(1)}><span class="badge {mm.group(2).lower()}">{_icon(mm.group(2))}{mm.group(2)}</span></td>', body)
    meta_bits = [", ".join(map(str, fm.get("authors") or [])), str(fm.get("date") or ""), f"v{fm['version']}" if fm.get("version") else ""]
    return PAGE.render(
        lang=fm.get("lang", "en"), title=title, subtitle=fm.get("subtitle"), authors=fm.get("authors") or [], tags=fm.get("tags") or [],
        meta_line=" · ".join(b for b in meta_bits if b), toc=outline if toc and outline else None, body=Markup(body), ev=evidence,
        css=Markup(font_face_css() + CSS.replace("__PAGE__", page).replace("__SANS__", SANS_STACK).replace("__MONO__", MONO_STACK)))


def _ensure_native_libs() -> None:
    """WeasyPrint needs Pango. Homebrew installs it outside dyld's default search path, and dyld reads
    DYLD_FALLBACK_LIBRARY_PATH only at process start, so set it and re-exec once."""
    brew = Path("/opt/homebrew/lib")
    if sys.platform == "darwin" and brew.is_dir() and str(brew) not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{brew}:{os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')}".rstrip(":")
        os.execv(sys.executable, [sys.executable, *sys.argv])


def html_to_pdf(html: str) -> bytes:
    """HTML to PDF with WeasyPrint. The document is self-contained (fonts and charts are inline), so the
    fetcher allows data: URIs and nothing else: no network, no local files (VQA-19)."""
    _ensure_native_libs()
    try:
        from weasyprint import HTML, URLFetcher
    except OSError as e:  # missing Pango / GObject
        raise RuntimeError(f"WeasyPrint could not load its native libraries ({e}). Install Pango, for example: brew install pango") from e

    return HTML(string=html, url_fetcher=URLFetcher(allowed_protocols=["data"])).write_pdf()
