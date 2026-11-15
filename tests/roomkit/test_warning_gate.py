"""The warning gate (display.gate) on documents with a notice.

When display.gate is true, the reader mount waits behind the notice for an
explicit user click ("Show document") before mounting or fetching the PDF.
Without JavaScript, no inline <object> is rendered, and only plain links show.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roomkit import build as B
from roomkit.manifest import parse

ENGINE = Path(__file__).resolve().parent / "golden" / "engine"


def _doc_manifest(gate: bool = False, with_notice: bool = True) -> dict:
    disp = {}
    if with_notice:
        disp["notice"] = {"heading": "Hate warning: anti-trans source",
                          "body": "Preserved as a historical record, not a trusted source."}
    if gate:
        disp["gate"] = True
    return {
        "site": {
            "name": "records.example.org",
            "title": "Archive",
            "base_url": "https://records.example.org",
            "room_path": "/documents/",
            "template": "example",
        },
        "documents": [
            {
                "slug": "test-gated-doc",
                "title": "Test Gated Document",
                "visibility": "public",
                "citation": "Test Citation. https://records.example.org/documents/test-gated-doc/",
                "date": "2025-01-01",
                "file": {
                    "url": "/documents/test-gated-doc/file.pdf",
                    "download_url": "/documents/test-gated-doc/file.pdf?download=1",
                    "sha256": "a" * 64,
                    "bytes": 1024,
                    "ext": "pdf",
                    "mime": "application/pdf",
                },
                "display": disp,
            }
        ],
    }


def test_manifest_refuses_non_boolean_gate():
    m = _doc_manifest(with_notice=True)
    m["documents"][0]["display"]["gate"] = "true"
    parsed = parse(m)
    assert len(parsed.refusals) == 1
    assert parsed.refusals[0] == ("test-gated-doc", "display.gate is not a boolean")


def test_manifest_refuses_gate_without_notice():
    m = _doc_manifest(gate=True, with_notice=False)
    parsed = parse(m)
    assert len(parsed.refusals) == 1
    assert parsed.refusals[0] == ("test-gated-doc", "display.gate needs a display.notice to stand behind")


def test_manifest_accepts_valid_gate_with_notice():
    m = _doc_manifest(gate=True, with_notice=True)
    parsed = parse(m)
    assert parsed.refusals == []
    assert len(parsed.documents) == 1
    assert parsed.documents[0].display.get("gate") is True


def test_gated_document_renders_gated_markup():
    m = parse(_doc_manifest(gate=True, with_notice=True))
    files = B.render(m, engine=ENGINE)
    html = files["test-gated-doc/index.html"].decode("utf-8")

    # Gate box and reveal button
    assert 'class="room__gate" data-room-gate' in html
    assert 'data-room-gate-open hidden>Show document</button>' in html

    # Reader mount holds data-gate-file-url and is hidden
    assert 'data-gate-file-url="/documents/test-gated-doc/file.pdf"' in html
    assert 'data-file-url=' not in html
    assert 'tabindex="-1" hidden' in html

    # No inline <object> in fallback
    assert '<object' not in html
    assert 'class="rr-reader__object"' not in html

    # Working download and open links are preserved in both gate and fallback
    assert 'href="/documents/test-gated-doc/file.pdf"' in html
    assert 'href="/documents/test-gated-doc/file.pdf?download=1"' in html


def test_ungated_document_renders_normal_reader():
    m = parse(_doc_manifest(gate=False, with_notice=True))
    files = B.render(m, engine=ENGINE)
    html = files["test-gated-doc/index.html"].decode("utf-8")

    # No gate container or button
    assert 'data-room-gate' not in html
    assert 'data-room-gate-open' not in html

    # Direct data-file-url and visible mount
    assert 'data-file-url="/documents/test-gated-doc/file.pdf"' in html
    assert 'data-gate-file-url' not in html

    # Standard noscript object fallback is present
    assert '<object class="rr-reader__object"' in html


@pytest.mark.browser
def test_in_a_browser_click_reveals_reader_and_requests_pdf(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    m = parse(_doc_manifest(gate=True, with_notice=True))
    files = B.render(m, engine=ENGINE)
    B.write(files, tmp_path / "documents")

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    except OSError as exc:
        pytest.skip(f"local HTTP server unavailable: {exc}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/documents/test-gated-doc/"

    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001 - any launch failure skips
                pytest.skip(f"Playwright Chromium not available: {e}")
            pg = b.new_page()
            requests = []
            pg.on("request", lambda r: requests.append(r.url))
            pg.goto(url)

            # Before click: no PDF request made
            pdf_reqs = [u for u in requests if u.endswith(".pdf")]
            assert pdf_reqs == []

            # Button is unhidden by room.js
            btn = pg.locator("[data-room-gate-open]")
            assert btn.is_visible()

            # Reader mount is hidden
            reader = pg.locator(".rr-reader")
            assert reader.is_hidden()

            # Click reveal button
            btn.click()

            # After click: reader is visible, gate is hidden
            assert reader.is_visible()
            assert pg.locator("[data-room-gate]").is_hidden()
            assert reader.get_attribute("data-file-url") == "/documents/test-gated-doc/file.pdf"
            assert reader.get_attribute("data-gate-file-url") is None

            b.close()
    finally:
        srv.shutdown()
