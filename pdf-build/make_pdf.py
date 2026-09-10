#!/usr/bin/env python3
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

WORKDIR = Path(__file__).resolve().parent
SRC = WORKDIR / "book.html"
DST = Path(sys.argv[1] if len(sys.argv) > 1 else WORKDIR / "textbook.pdf")

FOOTER = """
<div style="width:100%;font-family:Carlito,Helvetica,Arial,sans-serif;font-size:8pt;
     color:#666;padding:0 0.75in;display:flex;justify-content:space-between;">
  <span style="flex:1;">Computational and Inferential Thinking &middot; CCSF Math 108</span>
  <span class="pageNumber"></span>
</div>"""
HEADER = '<div style="font-size:0;"></div>'

with sync_playwright() as p:
    br = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage",
                                 "--font-render-hinting=none"])
    page = br.new_page()
    page.set_default_timeout(600_000)
    t = time.time()
    page.goto(SRC.as_uri(), wait_until="load", timeout=600_000)
    page.wait_for_timeout(4000)
    print("loaded in %.1fs" % (time.time() - t))
    page.emulate_media(media="print")
    t = time.time()
    page.pdf(path=str(DST), format="Letter", print_background=True,
             display_header_footer=True, header_template=HEADER, footer_template=FOOTER,
             margin={"top": "0.55in", "bottom": "0.75in", "left": "0.75in", "right": "0.75in"},
             prefer_css_page_size=False, outline=True, tagged=True)
    print("pdf in %.1fs" % (time.time() - t))
    br.close()

print(DST, "%.1f MB" % (DST.stat().st_size / 1e6))
