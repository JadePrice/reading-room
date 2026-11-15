"""Fixture-level tests ensuring non-public documents never leak into room artifacts.

Covers:
- Manifest rejection of non-public visibility
- Excluded records never generating pages, page text, sitemap entries, or search inputs
- Retraction mechanics via diff_locks (ensuring remove_now and purge include all retracted assets)
"""

import json

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit.manifest import parse


def _base_manifest() -> dict:
    return {
        "site": {
            "name": "records.example.org",
            "title": "Example Archive Reading Room",
            "base_url": "https://records.example.org",
            "room_path": "/library/",
            "template": "default",
            "index": {
                "groups": ["City Council", "Police Oversight"],
                "title": "Reading Room",
                "eyebrow": "Public Records Archive",
                "lede": "Official documents and audit records.",
            },
        },
        "documents": [
            {
                "slug": "public-doc-1",
                "title": "Public Meeting Notice",
                "visibility": "public",
                "citation": "City of Example, Common Council Meeting 2026-10-20",
                "date": "2026-10-20",
                "file": {
                    "url": "https://records.example.org/library/files/notice.pdf",
                    "download_url": "https://records.example.org/library/files/notice.pdf",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "bytes": 1024,
                    "ext": "pdf",
                    "mime": "application/pdf",
                },
                "pages": [
                    {"n": 1, "text": "Public notice page one content.", "provenance": "ocr"}
                ],
            },
            {
                "slug": "public-doc-2",
                "title": "Oversight Report",
                "visibility": "public",
                "citation": "Office of the Independent Monitor Q3 Report",
                "date": "2026-10-01",
                "file": {
                    "url": "https://records.example.org/library/files/report.pdf",
                    "download_url": "https://records.example.org/library/files/report.pdf",
                    "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "bytes": 2048,
                    "ext": "pdf",
                    "mime": "application/pdf",
                },
                "pages": [
                    {"n": 1, "text": "Oversight findings page one.", "provenance": "ocr"}
                ],
            },
        ],
    }


def test_manifest_refuses_non_public_visibility_values():
    """Any non-public visibility is recorded as a refusal and prevents rendering."""
    for invalid_visibility in ("draft", "private", "internal", "restricted", "pending-review", None):
        data = _base_manifest()
        data["documents"][0]["visibility"] = invalid_visibility
        m = parse(data)
        assert len(m.refusals) > 0
        refused_row, reason = m.refusals[0]
        assert refused_row == "public-doc-1"
        assert "visibility is" in reason
        assert "not 'public'" in reason
        # Build refuses to render any manifest with refusals
        with pytest.raises(ValueError) as exc_info:
            B.render(m)
        assert "render() called on a manifest with refusals" in str(exc_info.value)


def test_excluded_records_never_leak_into_built_room_or_search():
    """Excluded records must have zero presence in HTML files, page texts, and sitemaps."""
    data = _base_manifest()
    data["excluded"] = [
        {"slug": "withheld-investigation-doc", "problem": "Active litigation hold"}
    ]
    m = parse(data)
    rendered = B.render(m)

    # 1. No page directory or index.html for excluded document
    assert "withheld-investigation-doc/index.html" not in rendered
    assert not any(p.startswith("withheld-investigation-doc/") for p in rendered)

    # 2. Excluded document does not appear in sitemap if sitemaps feature is enabled
    if "sitemap.xml" in rendered:
        sitemap_text = rendered["sitemap.xml"].decode("utf-8")
        assert "withheld-investigation-doc" not in sitemap_text

    # 3. Excluded document never enters Pagefind search input
    if "pagefind/input.json" in rendered:
        search_input = json.loads(rendered["pagefind/input.json"].decode("utf-8"))
        indexed_urls = [entry.get("url", "") for entry in search_input]
        assert not any("withheld-investigation-doc" in u for u in indexed_urls)


def test_retracted_document_is_queued_in_remove_now_and_purged():
    """When a document leaves the manifest, diff_locks queues it for immediate deletion."""
    # Initial build with 2 documents
    m1 = parse(_base_manifest())
    rendered1 = B.render(m1)
    lock1 = json.loads(rendered1[B.LOCK])

    # Second build with public-doc-2 retracted
    data2 = _base_manifest()
    data2["documents"] = [data2["documents"][0]]  # public-doc-2 removed
    m2 = parse(data2)
    rendered2 = B.render(m2)
    lock2 = json.loads(rendered2[B.LOCK])

    diff = cli.diff_locks(lock1, lock2)

    # Must be in remove_now for immediate deletion
    assert "public-doc-2/index.html" in diff["remove_now"]
    # Pages JSON must also be in remove_now
    assert any(p.startswith("public-doc-2/pages.") and p.endswith(".json") for p in diff["remove_now"])

    # Must be in purge for CDN edge cache clearance
    assert "public-doc-2/index.html" in diff["purge"]
    assert "index.html" in diff["purge"]  # catalog index re-renders

    # Active documents must NOT be in remove_now
    assert "public-doc-1/index.html" not in diff["remove_now"]


def test_sitemap_leak_prevention():
    """Sitemaps must strictly contain only public documents."""
    data = _base_manifest()
    m = parse(data)
    rendered = B.render(m)
    if "sitemap.xml" in rendered:
        sitemap_text = rendered["sitemap.xml"].decode("utf-8")
        assert "public-doc-1" in sitemap_text
        assert "public-doc-2" in sitemap_text
        assert "draft" not in sitemap_text
        assert "private" not in sitemap_text


@pytest.mark.browser
def test_browser_csp_header_enforces_self_and_blocks_inline_script(tmp_path):
    """Playwright browser verification that room CSP stops inline script execution."""
    sync_api = pytest.importorskip("playwright.sync_api")
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    # Render a room with CSP enabled
    data = _base_manifest()
    m = parse(data)
    rendered = B.render(m)
    
    # Write room files to tmp_path
    B.write(rendered, tmp_path / "library")

    class CSPHandler(SimpleHTTPRequestHandler):
        def end_headers(self):
            # Send the roomkit CSP header exactly as emitted in build.CSP
            self.send_header("Content-Security-Policy", B.CSP)
            super().end_headers()
        def log_message(self, *a):
            pass

    handler = functools.partial(CSPHandler, directory=str(tmp_path))
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    except OSError as exc:
        pytest.skip(f"local HTTP server unavailable: {exc}")
    
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/library/public-doc-1/"

    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001 - any launch failure skips
                pytest.skip(f"Playwright Chromium not available: {e}")
            
            pg = b.new_page()
            csp_violations = []
            pg.on("console", lambda msg: csp_violations.append(msg.text) if "Content Security Policy" in msg.text else None)
            
            res = pg.goto(url)
            assert res.status == 200
            
            # Legitimate room scripts (room.js etc.) load without CSP violations on initial page load
            assert not any("room.js" in v for v in csp_violations)
            
            # Attempting an inline script eval must trigger a CSP violation in the browser
            try:
                pg.evaluate("""
                    const s = document.createElement('script');
                    s.textContent = 'window.__leaked_inline_flag = true;';
                    document.body.appendChild(s);
                """)
            except Exception:  # noqa: BLE001, S110 - the CSP blocking the script is the point
                pass  # CSP blocked script execution
                
            flag = pg.evaluate("window.__leaked_inline_flag === undefined")
            assert flag is True, "Inline script was executed despite CSP!"
            b.close()
    finally:
        srv.shutdown()
        srv.server_close()
