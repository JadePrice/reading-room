"""The archive viewer (rr-reader-archive.js): HTML mirrors and WACZ replay.

Both run in real Chromium against the local site in conftest.py. The WACZ is
built here from scratch (warcio, no network): one archived page whose
stylesheet is in the archive and whose image points off-site, so a replay that
leaked to the live web would show up as a request to that host.

Skipped, loudly, when Playwright's Chromium is not installed (the rule in
test_reader_browser.py).
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from tests.reading_room_reader.conftest import ENGINE, axe_source

sync_api = pytest.importorskip("playwright.sync_api")
warcio = pytest.importorskip("warcio")

VENDOR = ENGINE / "vendor" / "replaywebpage"
OFFSITE = "offsite.invalid"
ARCHIVED_URL = "https://www.example.gov/health/page.html"
TS = "20250116120000"

PAGE = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Archived fixture page</title>
<link rel="stylesheet" href="/health/style.css"></head>
<body><h1>Archived fixture page</h1><p id="t">Gender-affirming care guidance, as published.</p>
<img src="https://{OFFSITE}/tracker.png" alt="">
<script>document.body.setAttribute('data-ran', '1')</script></body></html>"""


# ---- fixtures -------------------------------------------------------------------

def _wacz(path: Path) -> None:
    """A minimal valid WACZ 1.1.1: one WARC, a CDXJ index, pages.jsonl, datapackage.json."""
    from warcio.statusandheaders import StatusAndHeaders
    from warcio.warcwriter import WARCWriter

    buf = io.BytesIO()
    writer = WARCWriter(buf, gzip=True)
    entries = []
    for url, ctype, body in [
        (ARCHIVED_URL, "text/html; charset=utf-8", PAGE.encode()),
        ("https://www.example.gov/health/style.css", "text/css", b"h1{color:#036}"),
    ]:
        headers = StatusAndHeaders("200 OK", [("Content-Type", ctype), ("Content-Length", str(len(body)))],
                                   protocol="HTTP/1.1")
        rec = writer.create_warc_record(url, "response", payload=io.BytesIO(body), http_headers=headers,
                                        warc_headers_dict={"WARC-Date": "2025-01-16T12:00:00Z"})
        start = buf.tell()
        writer.write_record(rec)
        entries.append((url, ctype.split(";")[0], start, buf.tell() - start,
                        rec.rec_headers.get_header("WARC-Payload-Digest")))
    warc = buf.getvalue()

    def surt(u: str) -> str:
        host, _, rest = u.split("://", 1)[1].partition("/")
        parts = host.split(".")
        if parts[0] == "www":
            parts = parts[1:]
        return ",".join(reversed(parts)) + ")/" + rest

    cdx = "".join(
        f"{surt(u)} {TS} " + json.dumps({"url": u, "mime": m, "status": "200", "digest": d,
                                          "length": str(ln), "offset": str(off), "filename": "data.warc.gz"}) + "\n"
        for u, m, off, ln, d in sorted(entries, key=lambda e: surt(e[0]))
    ).encode()
    pages = (json.dumps({"format": "json-pages-1.0", "id": "pages", "title": "Pages", "hasText": True}) + "\n"
             + json.dumps({"id": "p1", "url": ARCHIVED_URL, "ts": "2025-01-16T12:00:00Z",
                           "title": "Archived fixture page"}) + "\n").encode()
    files = {"archive/data.warc.gz": warc, "indexes/index.cdx": cdx, "pages/pages.jsonl": pages}
    package = {
        "profile": "data-package", "wacz_version": "1.1.1", "created": "2025-01-16T12:00:00Z",
        "software": "reading-room-reader tests",
        "resources": [{"name": Path(n).name, "path": n, "hash": "sha256:" + hashlib.sha256(b).hexdigest(),
                       "bytes": len(b)} for n, b in files.items()],
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        for n, b in files.items():
            z.writestr(n, b)
        z.writestr("datapackage.json", json.dumps(package))


@pytest.fixture(scope="module")
def archive_site(reader_site):
    d = reader_site.dir
    for sub in ("files", "csp"):
        (d / sub).mkdir(exist_ok=True)
        (d / sub / "mirror.html").write_text(PAGE, encoding="utf-8")
    _wacz(d / "files" / "page.wacz")
    return reader_site


def archive_html(file_url: str, kind: str, *, replay_base: str | None = "/replay/",
                 page: str = "", ts: str = "") -> str:
    cfg = {"replayBase": replay_base} if replay_base is not None else {}
    extra = (f' data-archive-page="{page}"' if page else "") + (f' data-archive-ts="{ts}"' if ts else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Archived page</title></head>
<body><main><h1>Archived page</h1>
<div class="rr-reader" data-file-url="{file_url}" data-ext="{'wacz' if kind == 'wacz' else 'html'}"
     data-archive="{kind}" data-title="Archived fixture page"{extra}>
  <p class="rr-reader__status" data-reader-status role="status" aria-live="polite">Loading the reader.</p>
  <div data-reader-fallback>
    <a class="fb-open" href="{file_url}">Open the archived copy</a>
    <a class="fb-record" href="https://web.archive.org/web/{TS}/{ARCHIVED_URL}">Wayback Machine copy</a>
  </div>
</div></main>
<script>window.rrReaderConfig = {json.dumps(cfg)};</script>
<script src="/engine/rr-reader.js"></script>
<script src="/engine/modules/rr-reader-text.js"></script>
<script src="/engine/modules/rr-reader-archive.js"></script>
</body></html>"""


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001 — any launch failure is "no browser"
            pytest.skip(f"Playwright Chromium not installed: {e}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    offsite: list[str] = []

    def guard(route):
        offsite.append(route.request.url)
        route.abort()

    ctx.route(f"**://{OFFSITE}/**", guard)
    pg = ctx.new_page()
    pg.set_default_timeout(20000)
    pg.offsite = offsite
    yield pg
    ctx.close()


def mirror_frame(page):
    page.wait_for_selector(".rr-reader__archive-frame")
    handle = page.query_selector(".rr-reader__archive-frame")
    frame = handle.content_frame()
    frame.wait_for_selector("#t")
    return frame


# ---- the vendored replayer ---------------------------------------------------------

def test_vendored_replaywebpage_matches_its_pinned_hashes():
    sums = dict(line.split()[::-1] for line in (VENDOR / "SHA256SUMS").read_text().splitlines())
    assert set(sums) == {"ui.js", "sw.js", "LICENSE"}
    for name, digest in sums.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name
    assert "AGPL" in (VENDOR / "SOURCE.md").read_text()


# ---- html mirrors ----------------------------------------------------------------

def test_html_mirror_mounts_sandboxed_not_as_source_text(page, archive_site):
    page.goto(archive_site.page("arch-html", archive_html("/files/mirror.html", "html")))
    frame = mirror_frame(page)
    el = page.locator(".rr-reader__archive-frame")
    assert el.get_attribute("sandbox") == ""
    assert el.get_attribute("referrerpolicy") == "no-referrer"
    assert page.locator(".rr-reader__text").count() == 0  # the text viewer did not take it
    assert "Gender-affirming care guidance" in frame.inner_text("#t")
    # The archived page's own script never ran.
    assert frame.evaluate("document.body.getAttribute('data-ran')") is None
    # The site's fallback links stay: the reader only adds.
    assert page.locator(".fb-record").is_visible()


def test_html_mirror_without_csp_does_request_off_site(page, archive_site):
    # Why sites must send the CSP: the sandbox stops scripts, not requests.
    page.goto(archive_site.page("arch-html-open", archive_html("/files/mirror.html", "html")))
    mirror_frame(page)
    deadline = time.time() + 5
    while not page.offsite and time.time() < deadline:
        page.wait_for_timeout(100)
    assert any(OFFSITE in u for u in page.offsite)


def test_html_mirror_with_the_csp_makes_no_off_site_request(page, archive_site):
    page.goto(archive_site.page("arch-html-csp", archive_html("/csp/mirror.html", "html")))
    mirror_frame(page)
    page.wait_for_timeout(1000)
    assert page.offsite == []


def test_html_mirror_record_page_passes_axe(page, archive_site):
    page.goto(archive_site.page("arch-html-axe", archive_html("/csp/mirror.html", "html")))
    mirror_frame(page)
    page.evaluate(axe_source())
    result = page.evaluate(
        "() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})")
    serious = [v["id"] for v in result["violations"] if v["impact"] in ("serious", "critical")]
    assert serious == []


# ---- wacz replay -------------------------------------------------------------------

def _replayed_text(page, timeout_s: float = 30.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for fr in page.frames:
            try:
                if fr.query_selector("#t"):
                    return fr.inner_text("#t")
            except Exception:  # noqa: BLE001, S110 - frames come and go during replay
                pass
        page.wait_for_timeout(250)
    raise AssertionError(f"replay never showed the archived page; frames: {[f.url for f in page.frames]}")


def test_wacz_replays_the_archived_page_from_the_room_alone(page, archive_site):
    page.goto(archive_site.page("arch-wacz", archive_html(
        "/files/page.wacz", "wacz", page=ARCHIVED_URL, ts=TS)))
    page.wait_for_selector("replay-web-page")
    el = page.locator("replay-web-page")
    assert el.get_attribute("replaybase") == "/replay/"
    assert el.get_attribute("embed") == "replay-with-info"
    assert el.get_attribute("newwindowbase").startswith(archive_site.base)
    assert "Gender-affirming care guidance" in _replayed_text(page)
    # Every request stayed on the room's origin: the off-site image was never fetched live.
    page.wait_for_timeout(1000)
    assert page.offsite == []


def test_wacz_without_a_replay_base_falls_back_to_the_links(page, archive_site):
    page.goto(archive_site.page("arch-wacz-nobase", archive_html("/files/page.wacz", "wacz", replay_base=None)))
    page.wait_for_selector(".rr-reader[data-reader-failed='1']")
    assert page.locator("replay-web-page").count() == 0
    assert page.locator(".fb-open").first.is_visible()
    assert "cannot replay" in page.locator("[data-reader-status]").inner_text()
