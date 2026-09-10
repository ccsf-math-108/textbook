#!/usr/bin/env python3
"""Assemble the CCSF Math 108 textbook (MyST project) into one print-ready HTML file."""
import base64, html, json, mimetypes, os, re, sys, yaml
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.deflist import deflist_plugin
from pygments import highlight
from pygments.lexers import PythonLexer, get_lexer_by_name
from pygments.formatters import HtmlFormatter
import latex2mathml.converter as l2m

# ROOT = the textbook repo (folder containing myst.yml). Defaults to the
# folder this script lives in; override with:  python3 build_html.py /path/to/textbook
WORKDIR = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else WORKDIR
OUT = WORKDIR / "book.html"

# ---------------------------------------------------------------- math
TEX_FIX = [(r"\vert", "|"), (r"\Vert", "‖")]
def to_mathml(tex, display=False):
    for a, b in TEX_FIX:
        tex = tex.replace(a, b)
    try:
        return l2m.convert(tex, display="block" if display else "inline")
    except Exception:
        return '<code class="rawmath">%s</code>' % html.escape(tex)

def render_math_inline(self, tokens, idx, options, env):
    return to_mathml(tokens[idx].content, False)

def render_math_block(self, tokens, idx, options, env):
    return '<div class="math-block">%s</div>' % to_mathml(tokens[idx].content, True)

md = (
    MarkdownIt("commonmark", {"html": True, "linkify": False, "typographer": False})
    .enable("table")
    .enable("strikethrough")
    .use(dollarmath_plugin, allow_space=False, allow_digits=True, double_inline=True)
    .use(deflist_plugin)
)
for name in ("math_inline", "math_inline_double"):
    md.add_render_rule(name, render_math_inline)
for name in ("math_block", "math_block_label"):
    md.add_render_rule(name, render_math_block)

# ---------------------------------------------------------------- assets
MAXW = 1500          # figures are ≤6.5in wide in print, so ~230 dpi is plenty
def shrink(raw: bytes, mime: str):
    """Downscale oversized raster images so the PDF stays a reasonable size."""
    if mime not in ("image/png", "image/jpeg"):
        return raw, mime
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(raw))
        if im.width <= MAXW:
            return raw, mime
        h = round(im.height * MAXW / im.width)
        im = im.resize((MAXW, h), Image.LANCZOS)
        buf = io.BytesIO()
        if mime == "image/jpeg":
            im.convert("RGB").save(buf, "JPEG", quality=86, optimize=True,
                                   progressive=True)
        else:
            im.save(buf, "PNG", optimize=True)
        return (buf.getvalue(), mime) if buf.tell() < len(raw) else (raw, mime)
    except Exception:
        return raw, mime

_asset_cache = {}
def data_uri(path: Path):
    key = str(path)
    if key not in _asset_cache:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        raw, mime = shrink(path.read_bytes(), mime)
        _asset_cache[key] = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())
    return _asset_cache[key]

def png_uri(b64: str):
    b64 = "".join(b64) if isinstance(b64, list) else b64
    b64 = b64.strip().replace("\n", "")
    try:
        raw, _ = shrink(base64.b64decode(b64), "image/png")
        b64 = base64.b64encode(raw).decode()
    except Exception:
        pass
    return "data:image/png;base64," + b64

MISSING = set()
def fix_srcs(htm, base: Path):
    def repl(m):
        pre, url, post = m.group(1), m.group(2), m.group(3)
        if url.startswith(("data:", "http://", "https://", "#")):
            return m.group(0)
        p = (base / url).resolve()
        if not p.exists():
            p2 = (ROOT / url.lstrip("/")).resolve()
            p = p2 if p2.exists() else p
        if not p.exists():
            MISSING.add(url)
            return m.group(0)
        return pre + data_uri(p) + post
    return re.sub(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', repl, htm, flags=re.I)

# ---------------------------------------------------------------- headings
HEAD_RE = re.compile(r"<(/?)h([1-6])([^>]*)>", re.I)
def shift_headings(htm, delta):
    if not delta:
        return htm
    return HEAD_RE.sub(
        lambda m: "<%sh%d%s>" % (m.group(1), min(6, int(m.group(2)) + delta), m.group(3)),
        htm)

FIRST_HEAD = re.compile(r"\s*<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)
def strip_title_heading(htm, title):
    m = FIRST_HEAD.match(htm)
    if not m:
        return htm
    text = re.sub(r"<[^>]+>", "", m.group(2))
    # drop the file's own leading title heading: either it matches the title we
    # are using, or it is a top-level (h1/h2) heading opening the document
    if norm(text) == norm(title) or int(m.group(1)) == 1:
        return htm[m.end():]
    return htm

def norm(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip().lower()

# ---------------------------------------------------------------- front matter
FM_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*\n?", re.S)
def split_front_matter(text):
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}, text
    if not isinstance(fm, dict):
        return {}, text
    return fm, text[m.end():]

HEADING_ANY = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$|^(?!\s*$)(.+)\n(=+|-+)\s*$", re.M)
def first_heading(text):
    for m in HEADING_ANY.finditer(text):
        if m.group(1):
            return m.group(2).strip()
        return m.group(3).strip()
    return None

# ---------------------------------------------------------------- notebooks
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
def clean(s):
    return ANSI.sub("", s)

def joinsrc(x):
    return "".join(x) if isinstance(x, list) else (x or "")

def render_outputs(outputs):
    out = []
    for o in outputs:
        t = o.get("output_type")
        if t in ("execute_result", "display_data"):
            d = o.get("data", {})
            if "image/png" in d:
                out.append('<div class="out out-img"><img src="%s"></div>'
                           % png_uri(d["image/png"]))
            elif "text/html" in d:
                out.append('<div class="out out-html">%s</div>' % joinsrc(d["text/html"]))
            elif "text/plain" in d:
                out.append('<div class="out"><pre class="out-text">%s</pre></div>'
                           % html.escape(clean(joinsrc(d["text/plain"]))))
        elif t == "stream":
            out.append('<div class="out"><pre class="out-text %s">%s</pre></div>'
                       % ("stderr" if o.get("name") == "stderr" else "",
                          html.escape(clean(joinsrc(o.get("text", ""))))))
        elif t == "error":
            tb = clean("\n".join(o.get("traceback", [])))
            out.append('<div class="out"><pre class="out-text err">%s</pre></div>' % html.escape(tb))
    return "".join(out)

PY_FMT = HtmlFormatter(cssclass="highlight", nowrap=False)
def render_code(src, lang="python"):
    try:
        lexer = get_lexer_by_name(lang)
    except Exception:
        lexer = PythonLexer()
    return '<div class="incell">%s</div>' % highlight(src, lexer, PY_FMT)

def render_notebook(path: Path, delta, title_hint=None):
    nb = json.loads(path.read_text())
    lang = (nb.get("metadata", {}).get("language_info", {}) or {}).get("name", "python")
    parts = []
    title = title_hint
    first_md = True
    for cell in nb.get("cells", []):
        tags = [t.lower() for t in (cell.get("metadata", {}).get("tags") or [])]
        tags = [t.replace("_", "-") for t in tags]
        if "remove-cell" in tags or "hide-cell" in tags:
            continue
        ctype = cell.get("cell_type")
        src = joinsrc(cell.get("source"))
        if ctype == "markdown":
            if first_md:
                fm, src = split_front_matter(src)
                if not title:
                    title = fm.get("title") or first_heading(src)
                first_md = False
            if not src.strip():
                continue
            htm = md.render(src)
            htm = fix_srcs(htm, path.parent)
            if title and not parts:
                htm = strip_title_heading(htm, title)
            parts.append(shift_headings(htm, delta))
        elif ctype == "code":
            body = []
            if "remove-input" not in tags and "hide-input" not in tags and src.strip():
                body.append(render_code(src.rstrip("\n"), lang))
            if "remove-output" not in tags:
                o = render_outputs(cell.get("outputs", []))
                if o:
                    body.append(o)
            if body:
                parts.append('<div class="cell">%s</div>' % "".join(body))
    return title or path.stem.replace("_", " "), "".join(parts)

def render_markdown_file(path: Path, delta, title_hint=None):
    text = path.read_text()
    fm, body = split_front_matter(text)
    title = title_hint or fm.get("title") or first_heading(body) or path.stem
    htm = md.render(body)
    htm = fix_srcs(htm, path.parent)
    htm = strip_title_heading(htm, title)
    return title, shift_headings(htm, delta)

# ---------------------------------------------------------------- TOC walk
cfg = yaml.safe_load((ROOT / "myst.yml").read_text())
proj = cfg["project"]

entries = []
def walk(items, depth, prefix):
    n = 0
    for it in items:
        f = it.get("file")
        if not f:
            continue
        f = " ".join(str(f).split())
        numbered = not (depth == 0 and f.endswith("chapters/intro.md"))
        num = None
        if numbered:
            n += 1
            num = (prefix + [n]) if prefix else [n]
        entries.append({
            "file": f, "depth": depth, "num": num,
            "title_override": it.get("title"),
        })
        if it.get("children"):
            walk(it["children"], depth + 1, num or [])
    return n

walk(proj["toc"], 0, [])
print("entries:", len(entries))

# ---------------------------------------------------------------- render all
sections = []
for i, e in enumerate(entries):
    p = ROOT / e["file"]
    delta = e["depth"]
    if p.suffix == ".ipynb":
        title, body = render_notebook(p, delta, e["title_override"])
    else:
        title, body = render_markdown_file(p, delta, e["title_override"])
    e["title"] = title
    e["id"] = "sec-%02d" % i
    lvl = min(6, 1 + e["depth"])
    numtxt = ".".join(str(x) for x in e["num"]) if e["num"] else ""
    label = ('<span class="secnum">%s</span> ' % numtxt) if numtxt else ""
    cls = "chapter" if e["depth"] == 0 else "section"
    sections.append(
        '<section class="%s" id="%s"><h%d class="unit-title">%s%s</h%d>%s</section>'
        % (cls, e["id"], lvl, label, html.escape(title), lvl, body))
    print("  %-6s %s" % (numtxt or "-", title))

if MISSING:
    print("MISSING assets:", sorted(MISSING), file=sys.stderr)

# ---------------------------------------------------------------- TOC html
PAGES = {}
pagemap = WORKDIR / "pagemap.json"
if pagemap.exists():
    PAGES = json.loads(pagemap.read_text())

toc_rows = []
for e in entries:
    numtxt = ".".join(str(x) for x in e["num"]) if e["num"] else ""
    pg = PAGES.get(e["id"], "")
    toc_rows.append(
        '<li class="d%d"><a href="#%s"><span class="tn">%s</span>'
        '<span class="tt">%s</span><span class="tl"></span>'
        '<span class="tp">%s</span></a></li>'
        % (e["depth"], e["id"], numtxt, html.escape(e["title"]), pg))
toc_html = '<ol class="toc">%s</ol>' % "".join(toc_rows)
json.dump([{"id": e["id"], "num": e["num"], "depth": e["depth"], "title": e["title"]}
           for e in entries], open(WORKDIR / "entries.json", "w"))

authors = ", ".join(a["name"] for a in proj.get("authors", []))
logo = data_uri(ROOT / "ccsflogo.png")
pyg_css = PY_FMT.get_style_defs(".highlight")

CSS = """
@page { size: Letter; margin: 0.8in 0.75in 0.85in 0.75in; }
:root { --ink:#1a1a1a; --muted:#555; --rule:#d6d6d6; --code-bg:#f6f7f9; --accent:#0b5c8a; }
* { box-sizing: border-box; }
body { font-family: "Bitstream Charter","Charter","DejaVu Serif",Georgia,serif;
       font-size: 10.5pt; line-height: 1.5; color: var(--ink); margin:0; }
p { margin: 0 0 0.62em; text-align: left; }
a { color: var(--accent); text-decoration: none; }
h1,h2,h3,h4,h5,h6 { font-family:"Carlito","DejaVu Sans",Helvetica,Arial,sans-serif;
   font-weight:700; line-height:1.2; color:#111; break-after: avoid-page; page-break-after: avoid;
   margin: 1.1em 0 0.45em; }
h1 { font-size: 22pt; } h2 { font-size: 15pt; } h3 { font-size: 12.5pt; }
h4 { font-size: 11pt; } h5,h6 { font-size: 10.5pt; }
.secnum { color: var(--accent); font-variant-numeric: tabular-nums; }
section.chapter { break-before: page; page-break-before: always; }
section.chapter > h1 { padding-bottom: .25em; border-bottom: 2px solid var(--accent); margin-top: 0; }
section.section > h2, section.section > h3 { break-before: auto; }
section { break-inside: auto; }

/* cover */
.cover { height: 9.1in; display:flex; flex-direction:column; justify-content:center;
         text-align:center; break-after: page; page-break-after: always; }
.cover img.logo { width: 2.1in; margin: 0 auto 0.5in; }
.cover .t { font-family:"Carlito","DejaVu Sans",sans-serif; font-size: 34pt; font-weight:700;
            line-height:1.12; margin-bottom: .18in; }
.cover .s { font-size: 13pt; color: var(--muted); margin-bottom: .5in; }
.cover .a { font-size: 12pt; } .cover .a span { display:block; margin:.06in 0; }
.cover .f { margin-top: .8in; font-size: 9.5pt; color: var(--muted); }

/* toc */
.toc-page { break-after: page; page-break-after: always; }
.toc-page h1 { border-bottom: 2px solid var(--accent); padding-bottom:.25em; }
ol.toc { list-style:none; margin:0; padding:0; font-family:"Carlito","DejaVu Sans",sans-serif; }
ol.toc li { margin: 1.5pt 0; break-inside: avoid; }
ol.toc a { color: var(--ink); display:flex; gap:.5em; align-items: baseline; }
ol.toc .tn { color: var(--accent); min-width: 3.1em; font-variant-numeric: tabular-nums; }
ol.toc .tt { flex: 0 1 auto; }
ol.toc .tl { flex: 1 1 auto; border-bottom: 1px dotted #bbb; height: .55em; min-width: 1em; }
ol.toc .tp { flex: 0 0 auto; color: var(--muted); font-variant-numeric: tabular-nums;
             font-size: 9pt; }
ol.toc li.d0 { font-weight:700; font-size:11pt; margin-top: 7pt; }
ol.toc li.d1 { padding-left: 1.4em; font-size: 10pt; }
ol.toc li.d2 { padding-left: 2.8em; font-size: 9.5pt; color: var(--muted); }
ol.toc li.d1 .tn, ol.toc li.d2 .tn { min-width: 3.4em; }

/* code + outputs */
.cell { margin: 0.55em 0; break-inside: avoid-page; }
.incell { background: var(--code-bg); border:1px solid #e3e5e9; border-left:3px solid #9bb7c9;
          border-radius:3px; padding:.4em .6em; margin-bottom:.3em; }
pre, code, kbd { font-family:"DejaVu Sans Mono","Courier New",monospace; }
.incell pre { margin:0; font-size:8.6pt; line-height:1.38; white-space:pre-wrap;
              word-break:break-word; }
p code, li code, td code, h1 code, h2 code, h3 code, h4 code {
  background:var(--code-bg); border:1px solid #e6e8ec; border-radius:3px;
  padding:0 .25em; font-size:8.9pt; }
.out { margin: .15em 0 .3em; }
pre.out-text { margin:0; font-size:8.6pt; line-height:1.35; white-space:pre-wrap;
               word-break:break-word; color:#222; padding:.25em .1em; }
pre.out-text.err, pre.out-text.stderr { color:#8a1f1f; }
.out-img img { max-width:100%; max-height:4.4in; display:block; margin:.2em auto; }
figure { margin: .6em 0; text-align:center; break-inside: avoid-page; }
figure img { max-width:100%; }
img { max-width: 100%; height:auto; }
p > img, p > a > img { display:block; margin:.4em auto; max-height:5in; }

/* tables */
table { border-collapse: collapse; margin:.35em 0; font-size:8.8pt;
        font-family:"Carlito","DejaVu Sans",sans-serif; max-width:100%; }
.out-html table { break-inside: avoid-page; }
th, td { border: 1px solid #cfd3d8; padding: 2pt 5pt; text-align:left; vertical-align:top; }
thead th, tr:first-child th { background:#eef1f4; }
.out-html { overflow: hidden; }
.out-html p { margin:.2em 0; font-size:9pt; color: var(--muted); }

blockquote { margin:.6em 0; padding:.2em 0 .2em 1em; border-left:3px solid var(--rule);
             color:#333; }
hr { border:0; border-top:1px solid var(--rule); margin:1em 0; }
ul, ol { margin:.3em 0 .7em; padding-left:1.5em; }
li { margin:.12em 0; }
math { font-family:"DejaVu Math TeX Gyre","Latin Modern Math",serif; }
.math-block { text-align:center; margin:.6em 0; break-inside: avoid; }
.rawmath { background:#fff3cd; }
"""

doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(proj.get('title','Textbook'))}</title>
<style>{CSS}
{pyg_css}
</style></head>
<body>
<div class="cover">
  <img class="logo" src="{logo}" alt="City College of San Francisco">
  <div class="t">Computational and<br>Inferential Thinking</div>
  <div class="s">The Foundations of Data Science &middot; 2nd Edition<br>
     CCSF Math 108 edition</div>
  <div class="a">{''.join('<span>%s</span>' % html.escape(a['name']) for a in proj.get('authors', []))}</div>
  <div class="f">Licensed CC BY-NC-ND 4.0 &middot; PDF compiled from the course textbook source</div>
</div>
<div class="toc-page"><h1>Contents</h1>{toc_html}</div>
{''.join(sections)}
</body></html>
"""
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(doc)
print("wrote", OUT, "%.1f MB" % (OUT.stat().st_size / 1e6))
