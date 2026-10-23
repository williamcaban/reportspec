"""DOCX output for ReportSpec v1alpha1 (DRAFT): the editable copy for auditors who need to annotate a report.

Pandoc (GPL-2.0+) does the conversion, run as a separate process. The input is the same Markdown the HTML
path starts from, with each chart block replaced by a PNG of the figure (rasterized from the same SVG, with
the same embedded fonts). The document uses pandoc's default styles and the fonts installed in the reader's Word.

Safety, because pandoc is handed text that includes untrusted results:
- The reader is commonmark_x without raw_html and raw_attribute: markup in results is literal text, and a
  fenced {=openxml} block cannot inject OOXML.
- Pandoc fetches any image URL it finds, and --sandbox would block our own figures too, so a template may
  not contain images at all. Figures come only from reportspec-viz blocks.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import vl_convert as vlc
from markdown_it import MarkdownIt

from reportspec_fonts import register_with_vl_convert

FIG_RE = re.compile(r"^@@RS-FIG:([a-z][a-z0-9-]*)@@$", re.M)
READER = "commonmark_x-raw_html-raw_attribute"
MD_ESC = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")
MAX_WIDTH_IN = 6.4


class DocxError(Exception):
    pass


def _esc(text: str) -> str:
    return MD_ESC.sub(r"\\\1", text)


TABLE_STYLE = (
    '<w:tblPr><w:tblInd w:w="0" w:type="dxa"/>'
    '<w:tblBorders><w:top w:val="single" w:sz="8" w:space="0" w:color="151515"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="D2D2D2"/>'
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="D2D2D2"/></w:tblBorders>'
    '<w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar></w:tblPr>'
    '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr><w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="12" w:space="0" w:color="151515"/></w:tcBorders>'
    '<w:shd w:val="clear" w:color="auto" w:fill="F5F5F5"/><w:vAlign w:val="bottom"/></w:tcPr></w:tblStylePr>')


def _reference_docx(pandoc: str) -> bytes | None:
    """Pandoc's default reference document with a readable table style (borders, padding, shaded header row).
    The default has none, so columns run together. Returns None, and pandoc keeps its defaults, if the layout changes."""
    done = subprocess.run([pandoc, "--print-default-data-file", "reference.docx"], capture_output=True, timeout=60, check=False)  # noqa: S603
    if done.returncode != 0:
        return None
    zin = zipfile.ZipFile(io.BytesIO(done.stdout))
    styles = zin.read("word/styles.xml").decode("utf-8")
    patched, n = re.subn(r'(<w:style w:type="table" w:default="1" w:styleId="Table">.*?<w:qFormat\s*/>\s*).*?(</w:style>)',
                         lambda m: m.group(1) + TABLE_STYLE + m.group(2), styles, count=1, flags=re.S)
    if n != 1:
        return None
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, patched.encode("utf-8") if item.filename == "word/styles.xml" else zin.read(item.filename))
    return out.getvalue()


def _polish_tables(docx: bytes) -> bytes:
    """Direct table formatting on top of the style, for viewers that ignore table styles (Quick Look, some previewers):
    borders and padding on every table, and a bold header row."""
    zin = zipfile.ZipFile(io.BytesIO(docx))
    xml = zin.read("word/document.xml").decode("utf-8")
    direct = ('<w:tblBorders><w:top w:val="single" w:sz="8" w:space="0" w:color="151515"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="D2D2D2"/>'
              '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="D2D2D2"/></w:tblBorders>'
              '<w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar>')
    xml = xml.replace("<w:tblLook ", direct + "<w:tblLook ").replace('<w:tblW w:type="auto" w:w="0" />', '<w:tblW w:type="pct" w:w="5000" />')
    xml = re.sub(r"(<w:tr><w:trPr><w:tblHeader[^>]*/></w:trPr>.*?</w:tr>)", lambda m: m.group(1).replace("<w:rPr><w:lang", "<w:rPr><w:b /><w:lang"), xml, flags=re.S)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, xml.encode("utf-8") if item.filename == "word/document.xml" else zin.read(item.filename))
    return out.getvalue()


def _width_in(svg: str) -> float:
    m = re.search(r'<svg[^>]*\swidth="([0-9.]+)"', svg)
    return min(MAX_WIDTH_IN, float(m.group(1)) / 96) if m else MAX_WIDTH_IN


def build_docx(md: str, figures: dict[str, dict[str, Any]], fm: dict[str, Any], evidence: dict[str, Any], *, toc: bool) -> bytes:
    """md: the template output with @@RS-FIG:id@@ placeholder paragraphs. figures: id -> number, title, caption, note, svg."""
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise DocxError("pandoc not found on PATH; DOCX output needs it (brew install pandoc, dnf install pandoc)")
    if any(c.type == "image" for t in MarkdownIt("commonmark").parse(md) for c in [t, *(t.children or [])]):
        raise DocxError("images in a template are not supported in DOCX output (pandoc would fetch their URLs); use a reportspec-viz block")
    register_with_vl_convert()

    title = str(fm.get("title", ""))
    md = re.sub(r"\A\s*#\s+" + re.escape(title) + r"\s*\n", "", md) if title else md  # the title is document metadata

    with tempfile.TemporaryDirectory(prefix="reportspec-docx-") as tmp:
        work = Path(tmp)

        def figure(m: re.Match[str]) -> str:
            f = figures[m.group(1)]
            name = f"fig-{m.group(1)}.png"
            (work / name).write_bytes(vlc.svg_to_png(f["svg"], scale=2))
            cap = f'::: {{custom-style="Image Caption"}}\nFigure {f["number"]}. {_esc(f["title"])}\n:::\n\n'
            out = f"![{_esc(f.get('alt') or f['title'])}]({name}){{width={_width_in(f['svg']):.2f}in}}"
            tail = " ".join(x for x in (f.get("caption"), f.get("note")) if x)
            return cap + out + (f"\n\n*{_esc(tail)}*" if tail else "")

        body = FIG_RE.sub(figure, md)
        src = [body.rstrip(), "", "## Evidence", "",
               f"Spec `{evidence['spec_name']}` v{evidence['spec_version']} ({evidence['spec_digest']}), generated {evidence['generated_at']}. "
               "Verdicts come from the producers of the results, not from this renderer.", ""]
        if evidence.get("sources"):
            src += ["| Source | Adapter | SHA-256 | Evaluations |", "|---|---|---|---|"]
            src += [f"| {_esc(s['uri'])} | {s['adapter']} | `{s['digest'][7:23]}` | {_esc(', '.join(s['evaluations']))} |" for s in evidence["sources"]]
            src.append("")
        src.append("Charts rendered with Red Hat Text (SIL OFL 1.1).")
        (work / "report.md").write_text("\n".join(src) + "\n", encoding="utf-8")

        cmd = [pandoc, "-f", READER, "-t", "docx", "--resource-path", str(work), "-o", str(work / "report.docx"), "-M", f"title={title}",
               "-M", f"lang={fm.get('lang', 'en')}"]
        if fm.get("subtitle"):
            cmd += ["-M", f"subtitle={fm['subtitle']}"]
        for a in fm.get("authors") or []:
            cmd += ["-M", f"author={a}"]
        if fm.get("date"):
            cmd += ["-M", f"date={fm['date']}"]
        ref = _reference_docx(pandoc)
        if ref:
            (work / "reference.docx").write_bytes(ref)
            cmd += ["--reference-doc", str(work / "reference.docx")]
        if toc:
            cmd.append("--toc")
        cmd.append(str(work / "report.md"))
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603
        if done.returncode != 0:
            raise DocxError(f"pandoc failed: {done.stderr.strip()[:400]}")
        return _polish_tables((work / "report.docx").read_bytes())
