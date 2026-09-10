#!/usr/bin/env python3
"""Resolve section -> page numbers from a rendered PDF, and (optionally) write a
clean chapter/section outline into the final PDF."""
import json, sys, warnings
from pathlib import Path
import pypdf
from pypdf.generic import Fit

warnings.filterwarnings("ignore")

WORKDIR = Path(__file__).resolve().parent
SRC = Path(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else "map"   # "map" or "final"
DST = Path(sys.argv[3]) if len(sys.argv) > 3 else None

reader = pypdf.PdfReader(str(SRC))
idx = {id(p.get_object()): i for i, p in enumerate(reader.pages)}
dests = reader.named_destinations
entries = json.loads((WORKDIR / "entries.json").read_text())

pages = {}
for e in entries:
    d = dests.get("/" + e["id"]) or dests.get(e["id"])
    if d is None:
        continue
    pg = d.page
    if hasattr(pg, "get_object"):
        pg = pg.get_object()
    n = idx.get(id(pg))
    if n is None:
        try:
            n = reader.get_page_number(pg)
        except Exception:
            n = None
    if n is not None:
        pages[e["id"]] = n + 1          # 1-based, matches printed footer

print("resolved %d/%d destinations" % (len(pages), len(entries)))

if MODE == "map":
    (WORKDIR / "pagemap.json").write_text(json.dumps(pages, indent=0))
    sys.exit(0)

# ---- final: rebuild the outline from the table of contents ----------------
w = pypdf.PdfWriter(clone_from=str(SRC))
try:
    w._root_object[pypdf.generic.NameObject("/Outlines")]  # drop Chromium's outline
    del w._root_object["/Outlines"]
except KeyError:
    pass
w._root_object.pop("/PageMode", None)

parents = {}
for e in entries:
    n = pages.get(e["id"])
    if n is None:
        continue
    num = ".".join(str(x) for x in e["num"]) if e["num"] else ""
    title = ("%s %s" % (num, e["title"])).strip()
    parent = parents.get(e["depth"] - 1) if e["depth"] else None
    item = w.add_outline_item(title, n - 1, parent=parent, fit=Fit.fit_horizontally(top=792))
    parents[e["depth"]] = item

w._root_object[pypdf.generic.NameObject("/PageMode")] = pypdf.generic.NameObject("/UseOutlines")
w.add_metadata({
    "/Title": "Computational and Inferential Thinking: The Foundations of Data Science",
    "/Author": "Ani Adhikari, John DeNero, David Wagner",
    "/Subject": "CCSF Math 108 textbook",
    "/Creator": "MyST source compiled to PDF",
})
w.write(str(DST))
print("wrote", DST, "%.1f MB" % (DST.stat().st_size / 1e6))
