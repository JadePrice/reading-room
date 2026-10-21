"""A local reading room for the shared reader engine.

Builds a throwaway site in a temp dir: the engine straight from
`reading-room-reader/src/`, the pinned pdf.js from `reading-room-reader/vendor/`,
generated fixture files (a 3-page text PDF, an image-only scan, a corrupt PDF,
an image, a text file) and static JSON stand-ins for the two REST routes the
engine calls (doc-search, passage). Served over http.server on a free port, so
fetch() and the pdf.js worker behave as they do on a real site.

No network. Nothing here is copied from either site's plugin, so these tests
exercise the canonical engine, which is what sync.sh vendors.
"""

from __future__ import annotations

import functools
import json
import shutil
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "reading-room-reader"

def axe_source() -> str:
    """axe-core 4.13.0, vendored and pinned in tests/vendor/ (see its README)."""
    path = REPO / "tests" / "vendor" / "axe.min.js"
    if not path.exists():
        raise FileNotFoundError(f"axe-core is not vendored at {path}; a missing axe looks like a clean result")
    return path.read_text(encoding="utf-8")

# The doc-search stand-in. The first snippet carries a literal "&" next to a
# query term ("amp"): before 0.4.0 the engine escaped the snippet and then
# highlighted it, so "amp" matched inside "&amp;" and mangled the entity.
DOC_SEARCH = {
    "pages": [
        {"page_number": 2, "snippet": "Flock & ALPR camera amp contract", "offset_start": 10, "offset_end": 30},
        {"page_number": 3, "snippet": "renewal amp terms", "offset_start": 0, "offset_end": 12},
    ]
}

# A roomkit pages.json: the reader searches it in the browser (static mode).
STATIC_PAGES = {
    "slug": "test-doc",
    "total": 3,
    "pages": [
        {"n": 1, "provenance": "pdf", "text": "Page 1 of the camera contract.\nFlock Safety ALPR retention terms"},
        {"n": 2, "provenance": "pdf", "text": "Page 2: the vendor keeps scans for thirty days; Flock & ALPR renewal"},
        {"n": 3, "provenance": "ocr", "text": "Page 3 renewal terms. Reflockulated is not a word."},
    ],
}

PASSAGE = {
    "found": True,
    "reference": "Test Agency, Camera Contract (2026), p. 1. https://example.test/library/test-doc/#page-1",
    "passage": {
        "page_number": 1,
        "text": "The vendor shall retain data for 30 days.",
        "provenance_level": "ocr",
        "ocr_confidence": 0.973,
        "stable_key": "test-doc:p1:0-41",
        "minted": False,
    },
}


def _make_files(root: Path) -> None:
    fitz = pytest.importorskip("fitz")
    files = root / "files"
    files.mkdir()

    doc = fitz.open()
    for n in (1, 2, 3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 120), f"Page {n} of the camera contract", fontsize=20)
        page.insert_text((72, 160), "Flock Safety ALPR retention terms", fontsize=14)
    doc.save(files / "text.pdf")

    # Image-only scan: each page is a raster of the text PDF, no text layer.
    scan = fitz.open()
    for page in doc:
        pix = page.get_pixmap(dpi=50)
        p = scan.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, pixmap=pix)
    scan.save(files / "scan.pdf")
    doc[0].get_pixmap(dpi=40).save(files / "page.png")

    (files / "corrupt.pdf").write_bytes(b"this is not a pdf at all")
    (files / "notes.txt").write_text("Line one\n<b>shown as source, not bold</b>\n", encoding="utf-8")
    (files / "data.csv").write_text("Year,Agency,Amount\n2025,Police,1000\n2026,Sheriff,2500\n", encoding="utf-8")


def page_html(
    file: str,
    ext: str,
    *,
    features: str | None = "spread,search",
    title: str = "Camera Contract",
    config: dict | None = None,
    modules: tuple[str, ...] = ("rr-reader-pdf", "rr-reader-image", "rr-reader-text"),
    head: str = "",
    file_dir: str = "files",
    poster: str = "",
    pages_url: str = "",
) -> str:
    """One document page, shaped like the sites' templates."""
    cfg = {
        "pdfJsUrl": "/pdfjs/pdf.min.js",
        "pdfWorkerUrl": "/pdfjs/pdf.worker.min.js",
        "docSearchUrl": "/api/doc-search.json",
        "passageUrl": "/api/passage.json",
    }
    cfg.update(config or {})
    feat = "" if features is None else f' data-features="{features}"'
    if poster:
        feat += f' data-poster="{poster}"'
    if pages_url:
        feat += f' data-pages-url="{pages_url}"'
    scripts = "\n".join(f'<script src="/engine/modules/{m}.js"></script>' for m in modules)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>{head}</head>
<body><main>
<h1>{title}</h1>
<p class="cite">Test Agency, {title} (2026).
  <button type="button" data-rr-cite-copy data-cite="Test Agency, {title} (2026)." hidden>Copy citation</button></p>
<div class="rr-reader" data-file-url="/{file_dir}/{file}" data-ext="{ext}" data-slug="test-doc"
     data-title="{title}"{feat}>
  <p class="rr-reader__status" data-reader-status role="status" aria-live="polite">Loading the reader.</p>
  <div data-reader-fallback>
    <a class="fb-open" href="/files/{file}">Open the file</a>
    <a class="fb-text" href="/text/">Read the text</a>
  </div>
</div>
</main>
<script>window.rrReaderConfig = {json.dumps(cfg)};</script>
<script src="/engine/rr-reader.js"></script>
{scripts}
<script src="/engine/modules/rr-cite.js"></script>
</body></html>"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def do_GET(self):
        # /slow/<file> is /files/<file> after a pause: a slow link, server-side,
        # so the browser's own timers run while the file is on its way.
        if self.path.startswith("/slow/"):
            time.sleep(SLOW_SECONDS)
            self.path = "/files/" + self.path[len("/slow/"):]
        super().do_GET()


SLOW_SECONDS = 1.5


@pytest.fixture(scope="session")
def reader_site(tmp_path_factory):
    root = tmp_path_factory.mktemp("reading-room")
    shutil.copytree(ENGINE / "src", root / "engine")
    shutil.copytree(ENGINE / "vendor" / "pdfjs", root / "pdfjs")
    (root / "api").mkdir()
    (root / "api" / "doc-search.json").write_text(json.dumps(DOC_SEARCH))
    (root / "api" / "passage.json").write_text(json.dumps(PASSAGE))
    (root / "api" / "pages.json").write_text(json.dumps(STATIC_PAGES))
    _make_files(root)

    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Site:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        dir = root

        def page(self, name: str, html: str) -> str:
            (root / f"{name}.html").write_text(html, encoding="utf-8")
            return f"{self.base}/{name}.html"

    yield Site()
    server.shutdown()
