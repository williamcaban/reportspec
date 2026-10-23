# Fonts

ReportSpec output embeds **Red Hat Text** and **Red Hat Mono** from this folder, so a report looks the same on any machine and uses only open fonts.

| File | Used for |
|---|---|
| `RedHatText-Regular.ttf`, `-Italic`, `-SemiBold`, `-Bold` | Body text, headings, chart labels |
| `RedHatMono-Regular.ttf` | Code spans |

- **Source:** [RedHatOfficial/RedHatFont](https://github.com/RedHatOfficial/RedHatFont), commit `6bb1048a6402b0076ea04f42951ec66263cd1437`, files under `fonts/Proportional/RedHatText/ttf/` and `fonts/Mono/RedHatMono/ttf/`. Font Version 1.030.
- **License:** SIL Open Font License 1.1 (`LICENSE`, the upstream file, and `OFL.txt`). Redistribution inside software is allowed.
- **Reserved Font Name "Red Hat".** A modified font may not keep the name, and subsetting is a modification. So the files are embedded **byte for byte**: base64 TTF in the HTML, and WeasyPrint's normal document embedding in the PDF. Do not subset, rename or re-export these files. Converting to WOFF2 would save about 60% of the HTML size and is probably fine, but has not been confirmed against the license, so it is not done.
- **Glyph coverage.** Red Hat Text has no ✓ ✗ ⚠ → ≥ ≤. Status marks are SVG icons (see `../icons/`), and templates should avoid those characters.

## Policy

Every font must be open (SIL OFL or equivalent) and either shipped in Linux distributions or vendored here. Fallbacks in the font stacks name only open families: `Liberation Sans`, `DejaVu Sans`, `Liberation Mono`, `DejaVu Sans Mono`, then the generic family. Helvetica, Arial, Menlo and other proprietary families are never named; an earlier version leaked Helvetica Neue and Menlo from a Mac into the PDF, and `pdffonts` now guards against that (VISUAL-QA.md, VQA-13).

## Distribution packaging (checked 2026-10-23 in containers)

| Font | Fedora 43 (`quay.io/fedora/python-314`) | Fedora 42 (`quay.io/fedora/python-313`) | UBI 9 (`registry.access.redhat.com/ubi9/ubi`) |
|---|---|---|---|
| Red Hat Text, Mono | `redhat-text-fonts`, `redhat-mono-fonts` 4.1.0-2.fc43 | 4.1.0-1.fc42 | not in the UBI 9 repos |
| Liberation Sans | 2.1.5-14.fc43 | 2.1.5-13.fc42 | not in the UBI 9 repos (`liberation-mono-fonts` only) |
| DejaVu Sans | 2.37-26.fc43 | 2.37-25.fc42 | installed by default |
| Noto Sans, Noto Sans CJK | `google-noto-sans-fonts`, `google-noto-sans-cjk-fonts` (OFL-1.1); also on Fedora 44 | same | not in the UBI 9 repos |

Fedora 44 was checked too (Red Hat fonts 4.1.0-3.fc44, license `OFL-1.1-RFN AND CC-BY-SA-4.0`).

**Why the container still uses the vendored files.** Fedora's package is the same font version (1.030, `fc-scan` reports 67502) but ships OpenType/CFF `.otf` files, while this folder holds `.ttf`. The bytes differ. If the image installed the RPMs as well, the family name "Red Hat Text" would resolve to two different files (the system `.otf` and the registered `.ttf`) and layout could depend on which one wins. So the `Containerfile` installs only the fallback families and leaves the Red Hat fonts to this folder: one source, the same bytes on every host. CJK labels need a Noto CJK package (Fedora) or a vendored copy; that is out of scope for v1alpha1.

UBI 9 was the first base image considered. It has none of the Red Hat, Liberation Sans or Noto fonts, so it would have needed the vendored files too; the Fedora Python images were chosen instead (see `Containerfile` at the repository root).

## DOCX

DOCX files embed no fonts. Word uses the styles' own fonts (pandoc's defaults), and the charts inside carry Red Hat Text as pixels.
