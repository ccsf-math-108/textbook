# Textbook → PDF build scripts

Turns a MyST-based textbook project (like `ccsf-math-108/textbook`, driven by
its `myst.yml` table of contents) into one print-ready PDF: cover page,
linked table of contents with real page numbers, numbered chapters/sections,
syntax-highlighted code cells with their stored Jupyter outputs (plots,
tables, errors), math rendered as MathML, and a proper PDF bookmark outline.

## Setup (one time)

```bash
pip install --break-system-packages \
    markdown-it-py mdit-py-plugins pygments latex2mathml pyyaml pypdf pillow playwright
playwright install chromium
```

(Drop `--break-system-packages` if you're in a virtualenv.)

## Run

From this folder, pointing at your textbook repo (the folder that contains
`myst.yml`):

```bash
python3 build_html.py /path/to/textbook          # -> book.html
python3 make_pdf.py pass1.pdf                     # first render
python3 finish_pdf.py pass1.pdf map               # -> pagemap.json (real page numbers)
python3 build_html.py /path/to/textbook           # re-render with those page numbers in the TOC
python3 make_pdf.py pass2.pdf
python3 finish_pdf.py pass2.pdf final MyTextbook.pdf
```

If you omit the path argument, `build_html.py` looks for `myst.yml` in its
own folder — so it also works if you copy the scripts directly into the
textbook repo and run them from there.

## Why two passes

Page numbers for the table of contents aren't known until after the PDF is
rendered once. Pass 1 renders once just to learn where each chapter landed;
`finish_pdf.py map` reads those positions out of the PDF's internal named
destinations into `pagemap.json`. Pass 2 re-renders with the real numbers
baked into the Contents page. `finish_pdf.py final` then throws out
Chromium's flat, auto-generated outline and rebuilds a proper nested
chapter/section bookmark tree from the same table of contents, and sets the
PDF title/author/subject metadata.

## Files

- `build_html.py` — parses `myst.yml`'s `toc`, renders each `.md`/`.ipynb`
  file, inlines all images as base64 (downscaling anything wider than
  1500px so the PDF doesn't bloat), converts `$...$` math to MathML, and
  writes one self-contained `book.html`.
- `make_pdf.py` — prints `book.html` to PDF via headless Chromium
  (Playwright), with a running footer and print page breaks per chapter.
- `finish_pdf.py` — resolves page numbers (`map` mode) or rebuilds the PDF
  bookmark outline and metadata (`final` mode).

## Tweaking

- Page size/margins/footer text: top of `make_pdf.py`.
- Fonts, colors, chapter-break behavior, table/code styling: the `CSS`
  string near the bottom of `build_html.py`.
- Cover page text/logo: the `doc = f"""..."""` block at the bottom of
  `build_html.py`.
- Which files/order appear: edited via your `myst.yml`'s `project.toc`, not
  the scripts — the build always follows that file.
