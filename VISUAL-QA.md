# ReportSpec Visual QA requirements

**Status:** DRAFT · **Author:** William Caban · **Date:** 2026-10-23 · **Applies to:** every host that renders ReportSpec charts to HTML or PDF (EvalHub, ASAGO)

Semantic conformance (`conformance/`) proves that the numbers, verdicts and N/A handling are right. It cannot prove that a chart looks right. A chart can render without error and still clip a label, draw a missing value as zero, or run across a page break. This document records what "looks right" means, how it is checked, and what is required before a new chart type ships.

## Where the idea came from

The first Vega radar spike (2026-10-23) produced SVG and PDF with no errors, and two defects were found only by looking at the pages:

| Defect | What it looked like | Requirement it became |
|---|---|---|
| N/A drawn as 0 | A `null` axis pulled the radar polygon to the center | VQA-3 |
| Clipped labels | Right-hand labels cut off in the PDF at 300 px ("TruthfulQ…", "Garak AS…") | VQA-1 |
| Label collisions | Value labels sat on top of lines and axis names | VQA-2 |

These three are permanent regression cases (see "Regression cases"). The first full-report review (2026-10-23) found four more, all in output that rendered without errors:

| Defect | What it looked like | Requirement it became |
|---|---|---|
| Gradient legend missing in the PDF | Heatmap legend showed labels and a stray tick, no color bar. It rendered correctly through resvg, so the same SVG differs by engine | VQA-12, VQA-21 |
| Invented axis titles | Altair printed field names ("value, t", "label", "group", "y") | VQA-2 |
| Value labels on the threshold line | "9.0% · PASS" struck through by the dashed line on horizontal bars | VQA-2 |
| Ring label under an axis label | The outermost radar ring label collided with the top axis label | VQA-2 |

## Implementation status (2026-10-23)

The reference renderer ([`reportspec_charts.py`](reportspec_charts.py), [`reportspec_html.py`](reportspec_html.py)) was reviewed by rendering the showcase report to PDF and HTML and looking at every page (layer H). Layers A and G are not built yet; conformance cases 30 to 32 cover parts of VQA-3, VQA-9, VQA-15, VQA-16 and VQA-18.

| Requirement | State |
|---|---|
| VQA-3 N/A never zero, VQA-9 alt text, VQA-10 text is text | Implemented, checked by eye and by `pdftotext` |
| VQA-13 open fonts, embedded | Implemented: every sample PDF lists only Red Hat Text and Red Hat Mono in `pdffonts`, and no proprietary family name appears in the HTML outside the font data. Not yet an automated test |
| VQA-15 degenerate data, VQA-16 density limits | Placeholder for empty or all-N/A; radar and radial limits enforced. Other states not exercised |
| VQA-18 inert untrusted text, VQA-19 no fetching | Implemented and in conformance (case 30); PDF URL fetcher refuses everything; chart specs pass `allowed_base_urls=[]` |
| VQA-1, 2, 11, 12 | Reviewed by eye on the showcase; no automated check yet |
| VQA-20 determinism | Measured once, not automated: the showcase HTML is byte-identical across Fedora 42 (Python 3.13), Fedora 43 (Python 3.14), repeat runs and macOS once the `generated` timestamp is masked; PDF text matches and pages 2 to 5 are pixel-identical, pages 1 and 6 differ only in the timestamp lines. The timestamp is the one source of nondeterminism |
| VQA-6, 7, 8, 14, 17, 21 | Not checked |

## Requirements

Each requirement is checked at one or more layers: **A** automated check, **G** golden image, **H** human review. "Must" items block a release; "should" items are tracked defects.

### Completeness and legibility

| ID | Requirement | Layer |
|---|---|---|
| VQA-1 | **No clipping.** Every text and mark lies inside the figure bounds in the SVG, and inside the page in the PDF. Label length is bounded by truncation with an ellipsis, never by cropping. Must | A, G |
| VQA-2 | **No overlap.** Labels do not overlap each other, marks or axes beyond a tolerance. Where collisions are likely (radar, radial), labels use a layout that avoids them, such as value text inside the axis label. Must for text-on-text, should for text-on-mark | G, H |
| VQA-3 | **N/A is never zero.** Every null or missing value is visibly marked "N/A" in the chart, never plotted at 0, never silently omitted. The number of N/A marks equals the number of null values in the payload. A series with N/A is not filled (radar, radial). Must | A, G |
| VQA-4 | **Thresholds are legible.** A threshold is drawn at the right position, labeled with its value, and a pass/fail state is carried by more than color (a label, icon or shape). Must | A, H |
| VQA-5 | **Direction is explicit.** When a series is `lower_is_better`, the figure says so in the caption or axis. Must | A |
| VQA-6 | **Min size.** Rendered text is at least 8 pt at 100% in the PDF. Marks and touch targets in HTML are at least 3 px wide. Must | A |

### Color and accessibility

| ID | Requirement | Layer |
|---|---|---|
| VQA-7 | **Contrast.** Text meets WCAG 2.2 AA (4.5:1); non-text marks meet 3:1 against their background. Colors come from theme tokens, never from the spec. Must | A |
| VQA-8 | **Not color alone.** Pass/fail and N/A stay distinguishable in grayscale and for the common color-vision deficiencies. Must | G, H |
| VQA-9 | **Alt text.** Every figure has an accessible name. When the spec has no `alt`, one is generated from the data and lists every value. Must | A |
| VQA-10 | **Text is text.** Chart text is real text in SVG and PDF: selectable, searchable and extractable. Rasterized charts are allowed only as an explicit `format.markdown.viz: image` fallback. Must | A |

### Document layout (PDF and print)

| ID | Requirement | Layer |
|---|---|---|
| VQA-11 | **No split figures.** A figure and its caption never break across pages. A heading is never the last line on a page. Table headers repeat on each page. Must | G, H |
| VQA-12 | **Fits the page.** Figures fit the content width at Letter and A4, portrait. Wide matrices scale or wrap, never overflow. Must | A, G |
| VQA-13 | **Open fonts, embedded.** Every font in the PDF is embedded and open: Red Hat Text and Red Hat Mono, vendored in `fonts/` and embedded byte for byte (the Reserved Font Name forbids subsetting). No proprietary family (Helvetica, Arial, Menlo, Calibri) appears in the PDF or in an HTML font stack. No missing-glyph boxes for Latin; a defined fallback for CJK. Must | A |
| VQA-14 | **Grayscale print.** The report is legible printed in grayscale, with no dependence on background colors. Should | H |

### Data robustness

| ID | Requirement | Layer |
|---|---|---|
| VQA-15 | **Degenerate data has a defined rendering.** Empty data, one point, all N/A, all values equal, zero-variance box, negative values and values outside `range` each produce a labeled placeholder or a clamped mark with a note. Blank output is a defect. Must | A, G |
| VQA-16 | **Density limits.** Each type has a documented limit (implemented: radar 3 to 12 axes, radial up to 8 items; proposed: heatmap up to 40 columns). Beyond it the renderer fails with a message or degrades to a table. It never produces an unreadable chart. Must | A |
| VQA-17 | **Data parity.** Every value shown in a chart also appears in its Markdown table fallback and its alt text, with the same formatting. Must | A |

### Safety and reproducibility

| ID | Requirement | Layer |
|---|---|---|
| VQA-18 | **Untrusted text is inert.** Labels and cell values containing markup, such as `<script>`, `<img onerror>` or `{{7*7}}`, render as literal text. The SVG contains no `<script>`, `<foreignObject>`, event-handler attributes or external `href`. Must | A |
| VQA-19 | **No fetching at render time.** Rendering performs no network or file access beyond its inputs. Chart specs with external data URLs fail (`allowed_base_urls=[]`), and the PDF engine's URL fetcher refuses everything except `data:` URIs. Must | A |
| VQA-20 | **Determinism.** The same bundle and spec produce byte-identical SVG and HTML. PDFs are equal after stripping timestamps, and their rasterized pages match the goldens within tolerance. Must | A, G |
| VQA-21 | **Host parity.** The same resolved payload renders the same figure on EvalHub and ASAGO. Hosts may not restyle charts outside theme tokens. Must | G |

## How it is checked

| Layer | What | Where it runs | Gate |
|---|---|---|---|
| **A. Automated checks** | Rules over the payload, SVG and PDF: N/A count equals N/A marks, no forbidden elements, text bounds inside the viewBox, contrast of theme tokens, fonts embedded (`pdffonts`), chart text present (`pdftotext`), data parity | Unit tests in the reference implementation | Every change |
| **G. Golden images** | One PNG per figure per case, compared pixel by pixel with a small tolerance (anti-aliasing). Goldens are generated and compared only inside the pinned render image | CI, in the container | Every change that touches a chart or the theme |
| **H. Human review** | A reviewer looks at the rendered pages against the checklist below and records it | When a chart type is added, or its geometry changes | Before a chart type ships |

### Human review checklist

For each chart type, review the gallery page rendered to PDF and to HTML:

1. Every label is complete and readable. Nothing is cut off.
2. The N/A case shows "N/A" and nothing is drawn at zero.
3. The threshold, direction and pass/fail are obvious without color.
4. Fits on the page with its caption. No awkward page break.
5. Reads correctly in grayscale.
6. The empty, one-point, long-label and maximum-density states look intentional.

The reviewer, date, renderer version and the reviewed PNGs are saved with the conformance case, so a later change can be compared against what was approved.

## Gallery cases (to be built)

Each chart type gets a conformance case rendering these states, which double as the golden set and the review gallery:

`normal` · `with-N/A` · `all-N/A` · `empty` · `single-point` · `all-equal` · `long-labels` · `max-density` · `out-of-range` · `hostile-labels` (markup in every label and value)

## Regression cases

| ID | From | Case |
|---|---|---|
| VQ-R1 | N/A drawn as 0 | A radar with one null axis: the polygon must break at the axis, which shows "N/A" |
| VQ-R2 | Clipped labels | A 6-axis radar with a 10-character axis name and 300 px width: all labels inside the figure |
| VQ-R3 | Label collisions | A radar with values near 1.0: value text must not overlap axis names |
| VQ-R4 | Gradient legend | A heatmap rendered to PDF through WeasyPrint shows a legend with color. Any legend must be checked in every output engine (HTML in a browser, PDF in WeasyPrint), not in one |
| VQ-R5 | Invented axis titles | A chart with no `x_label` or `y_label` shows no axis title |
| VQ-R6 | Value labels vs threshold | A horizontal bar with a threshold: no value label is crossed by the threshold line |
| VQ-R7 | Proprietary font leak | `pdffonts` on the showcase PDF lists only Red Hat Text and Red Hat Mono. The first full render embedded Helvetica Neue, Menlo and Noto from the Mac that built it |
| VQ-R8 | Missing glyphs | No template or generated text uses a character Red Hat Text lacks (✓ ✗ ⚠ → ≥ ≤); status marks are SVG icons |

## Open questions

1. **Tolerance for golden images.** Proposed: at most 0.1% of pixels differ by more than a small color distance. Needs tuning against real CI output.
2. **Who owns the pinned render image.** It must exist once and be shared by EvalHub and ASAGO, or goldens will drift apart. A reference [`Containerfile`](Containerfile) now exists (Fedora Python 3.14 or 3.13, locked dependencies), but it builds `FROM quay.io/fedora/python-314` by tag, which moves. Goldens need the base image pinned by digest, and one owner who bumps it on purpose.
3. **Automated overlap detection.** Text bounding boxes need a font-metrics source. Until one exists, VQA-2 is checked through goldens and human review.
4. **One SVG, several engines.** The gradient-legend defect shows that an SVG correct in one renderer can be wrong in another. Goldens are needed per output path (browser, WeasyPrint), not per chart.
5. **CJK and right-to-left labels.** Out of scope for v1alpha1. VQA-13 only requires a defined fallback.
