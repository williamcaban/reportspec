"""Fonts for ReportSpec output (DRAFT).

Policy: every font is open (SIL OFL or similar) and either ships in Linux distributions or is vendored
here. Output must not depend on what the machine has installed (VISUAL-QA.md, VQA-13 and VQA-20), so the
reference renderer embeds Red Hat Text and Red Hat Mono from fonts/ and names only open, widely packaged
fonts as fallbacks. Helvetica, Arial and other proprietary families are never named.

The font files are embedded byte for byte. Red Hat's license carries a Reserved Font Name, which forbids
a modified font from keeping the name, and subsetting counts as modification. PDF output is embedded by
WeasyPrint as subsets, which is ordinary document embedding.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"

SANS, MONO = "Red Hat Text", "Red Hat Mono"
# Fallbacks only matter for glyphs Red Hat Text lacks. The container image installs Liberation and DejaVu (Fedora packages).
SANS_STACK = f"{SANS}, Liberation Sans, DejaVu Sans, sans-serif"
MONO_STACK = f"{MONO}, Liberation Mono, DejaVu Sans Mono, monospace"

# family, style, weight, file
FACES: tuple[tuple[str, str, int, str], ...] = (
    (SANS, "normal", 400, "RedHatText-Regular.ttf"),
    (SANS, "italic", 400, "RedHatText-Italic.ttf"),
    (SANS, "normal", 600, "RedHatText-SemiBold.ttf"),
    (SANS, "normal", 700, "RedHatText-Bold.ttf"),
    (MONO, "normal", 400, "RedHatMono-Regular.ttf"),
)


@lru_cache(maxsize=1)
def font_face_css() -> str:
    """@font-face rules with the font files inlined as data: URIs, so the HTML stays one self-contained file."""
    rules = []
    for family, style, weight, name in FACES:
        data = base64.b64encode((FONT_DIR / name).read_bytes()).decode("ascii")
        rules.append(f'@font-face{{font-family:"{family}";font-style:{style};font-weight:{weight};'
                     f'src:url(data:font/ttf;base64,{data}) format("truetype")}}')
    return "\n".join(rules)


@lru_cache(maxsize=1)
def register_with_vl_convert() -> None:
    """Let vl-convert measure and rasterize chart text with the same fonts the document embeds."""
    import vl_convert as vlc

    vlc.register_font_directory(str(FONT_DIR))
