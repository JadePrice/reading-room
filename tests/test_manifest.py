"""Manifest parsing, validation and refusals for reading-room."""

from __future__ import annotations

import pytest

from roomkit.manifest import ManifestError, parse

SHA = "a" * 64


def _valid_manifest() -> dict:
    return {
        "site": {
            "name": "example.test",
            "title": "Reading Room",
            "base_url": "https://example.test",
            "room_path": "/reading-room/",
        },
        "documents": [
            {
                "slug": "camera-contract",
                "title": "Camera Contract",
                "visibility": "public",
                "citation": "Agency, Camera Contract (2026).",
                "agency": "Test Agency",
                "date": "2026-01-31",
                "summary": "Summary of camera contract.",
                "file": {
                    "url": "/reading-room/camera-contract/file/?v=aaaaaaaaaaaa",
                    "download_url": "/reading-room/camera-contract/file/?download=1",
                    "sha256": SHA,
                    "bytes": 1024,
                    "ext": "pdf",
                    "mime": "application/pdf",
                },
                "pages": [
                    {"n": 1, "text": "Page one text", "provenance": "pdf"},
                    {"n": 2, "text": "Page two text", "provenance": "ocr"},
                ],
            }
        ],
    }


def test_valid_manifest_parses_cleanly() -> None:
    data = _valid_manifest()
    m = parse(data)
    assert not m.refusals
    assert len(m.documents) == 1
    doc = m.documents[0]
    assert doc.slug == "camera-contract"
    assert doc.title == "Camera Contract"
    assert doc.ext == "pdf"
    assert len(doc.pages) == 2


def test_missing_site_raises_error() -> None:
    data = _valid_manifest()
    del data["site"]
    with pytest.raises(ManifestError, match="has no 'site' object"):
        parse(data)


def test_malformed_base_url_raises_error() -> None:
    data = _valid_manifest()
    data["site"]["base_url"] = "http://insecure.test"
    with pytest.raises(ManifestError, match="must be https://"):
        parse(data)


def test_missing_citation_refuses_document() -> None:
    data = _valid_manifest()
    data["documents"][0]["citation"] = ""
    m = parse(data)
    assert len(m.refusals) == 1
    assert "citation" in m.refusals[0][1]
    assert len(m.documents) == 0


def test_non_public_visibility_refuses_document() -> None:
    data = _valid_manifest()
    data["documents"][0]["visibility"] = "internal"
    m = parse(data)
    assert len(m.refusals) == 1
    assert "visibility" in m.refusals[0][1]
    assert len(m.documents) == 0


def test_duplicate_slug_refuses_second_document() -> None:
    data = _valid_manifest()
    doc2 = dict(data["documents"][0])
    doc2["title"] = "Second doc"
    data["documents"].append(doc2)
    m = parse(data)
    assert len(m.refusals) == 1
    assert m.refusals[0][1] == "duplicate slug"
    assert len(m.documents) == 1


def test_display_header_parsing() -> None:
    data = _valid_manifest()
    data["documents"][0]["display"] = {
        "header": {
            "meta": ["Agency", "Collection", "2020-2025"],
            "original_url": "?original=1",
            "ia_url": "https://archive.org/details/test",
            "ia_pending": False,
            "category": "contracts",
        }
    }
    m = parse(data)
    assert not m.refusals
    hdr = m.documents[0].display["header"]
    assert hdr["meta"] == ["Agency", "Collection", "2020-2025"]
    assert hdr["original_url"] == "?original=1"
    assert hdr["ia_url"] == "https://archive.org/details/test"
    assert hdr["category"] == "contracts"


def test_badges_and_notice_parity():
    from roomkit import parity as P
    display = {
        "badge": "Government record",
        "badge_kind": "government",
        "badge_sr": "Provenance: ",
        "notice": {
            "heading": "Collection Sensitivity",
            "body": "This collection contains sensitive surveillance materials.",
            "report": "Report issues to records@example.test",
        },
    }
    # Matches live WordPress markup
    html_live = """
    <h1 class="ggrr-doc__title">Test Doc<span class="ggrr-prov-badge ggrr-prov-badge--government"><span class="visually-hidden">Provenance: </span>Government record</span></h1>
    <aside class="ggrr-sensitivity" aria-labelledby="ggrr-sensitivity-head">
      <h2 class="ggrr-sensitivity__head" id="ggrr-sensitivity-head">Collection Sensitivity</h2>
      <p class="ggrr-sensitivity__body">This collection contains sensitive surveillance materials.</p>
      <p class="ggrr-sensitivity__report">Report issues to records@example.test</p>
    </aside>
    """
    assert P.check_badges_notice(display, html_live) == []

    # Matches static roomkit markup
    html_static = """
    <h1 class="room__title">Test Doc <span class="room__badge room__badge--government"><span class="room__sr">Provenance: </span>Government record</span></h1>
    <aside class="room__notice" aria-labelledby="room-notice-h">
      <h2 id="room-notice-h">Collection Sensitivity</h2>
      <p>This collection contains sensitive surveillance materials.</p>
      <p class="room__notice-report">Report issues to records@example.test</p>
    </aside>
    """
    assert P.check_badges_notice(display, html_static) == []

    # Mismatches
    assert P.check_badges_notice({"badge": "Third-party report"}, html_live) == [
        "badge 'Third-party report' not in page"
    ]
    assert P.check_badges_notice({"badge": "Government record", "badge_kind": "third-party"}, html_live) == [
        "badge_kind 'third-party' not in page"
    ]
    assert P.check_badges_notice({"notice": {"heading": "Other Heading", "body": "Body"}}, html_live) == [
        "notice heading 'Other Heading' not in page",
        "notice body 'Body' not in page",
    ]
    assert P.check_badges_notice(
        {"notice": {"heading": "Collection Sensitivity", "body": "This collection contains sensitive surveillance materials.", "report": "Wrong report"}},
        html_live,
    ) == [
        "notice report 'Wrong report' not in page",
    ]


@pytest.mark.parametrize("bad_path", [
    "//other-host/",
    "/path\\with\\backslash/",
    "/path?query=1/",
    "/path#fragment/",
    "/path/../relative/",
    "/path/./current/",
    "no-leading-slash/",
    "/no-trailing-slash",
])
def test_room_path_validation(bad_path: str):
    data = _valid_manifest()
    data["site"]["room_path"] = bad_path
    with pytest.raises(ManifestError):
        parse(data)


def test_numeric_validation_rejects_booleans():
    # file.bytes = True
    d1 = _valid_manifest()
    d1["documents"][0]["file"]["bytes"] = True
    m1 = parse(d1)
    assert any("file.bytes is not a non-negative integer" in prob for _, prob in m1.refusals)

    # page.n = True
    d2 = _valid_manifest()
    d2["documents"][0]["pages"][0]["n"] = True
    m2 = parse(d2)
    assert any("a page is not {n: int, text: str}" in prob for _, prob in m2.refusals)

    # document_id = True
    d3 = _valid_manifest()
    d3["documents"][0]["document_id"] = True
    m3 = parse(d3)
    assert any("document_id is not a positive integer" in prob for _, prob in m3.refusals)


def test_check_link_groups_parity():
    from roomkit import parity as P

    groups = [
        {
            "heading": "Topics",
            "style": "chips",
            "items": [
                {"label": "Surveillance", "url": "https://glassgovernment.org/library/topics/surveillance/"},
            ],
        },
        {
            "heading": "Named in this document",
            "blurb": "Matched verbatim in the document text.",
            "style": "chips",
            "items": [
                {
                    "label": "Flock Safety",
                    "kind": "Vendor",
                    "quote": "contract with Flock Safety for ALPR cameras",
                    "url": "https://glassgovernment.org/library/entity/vendor/flock-safety/",
                },
            ],
        },
        {
            "heading": "Related documents",
            "style": "list",
            "items": [
                {
                    "label": "Camera Audit",
                    "url": "https://glassgovernment.org/library/camera-audit/",
                    "meta": "Audit Collection",
                },
            ],
        },
    ]

    html_live = """
    <div class="ggrr-doc__topics">
      <dl>
        <dt>Topics</dt>
        <dd class="ggrr-doc__topic-list">
          <a class="ggrr-doc__topic-badge" href="https://glassgovernment.org/library/topics/surveillance/">Surveillance</a>
        </dd>
      </dl>
    </div>
    <div class="ggrr-doc__entities">
      <dl>
        <dt>Named in this document<span class="ggrr-doc__entity-why">Matched verbatim in the document text.</span></dt>
        <dd class="ggrr-doc__entity-list">
          <a class="ggrr-doc__entity-badge ggrr-doc__entity-badge--vendor" href="https://glassgovernment.org/library/entity/vendor/flock-safety/">
            <span class="ggrr-doc__entity-name">Flock Safety</span>
            <span class="ggrr-doc__entity-type">Vendor</span>
            <span class="ggrr-doc__entity-span">&ldquo;contract with <mark class="ggrr-doc__entity-hit">Flock Safety</mark> for ALPR cameras&rdquo;</span>
          </a>
        </dd>
      </dl>
    </div>
    <div class="ggrr-doc__related">
      <h2>Related documents</h2>
      <ul class="ggrr-doc__related-list">
        <li>
          <a href="https://glassgovernment.org/library/camera-audit/">Camera Audit</a>
          <span class="ggrr-doc__related-collection">Audit Collection</span>
        </li>
      </ul>
    </div>
    """
    assert P.check_link_groups(groups, html_live) == []

    # Deflock Dane single vendors group
    dd_groups = [
        {
            "heading": "Vendors",
            "style": "chips",
            "items": [
                {"label": "Axon", "url": "/reading-room/entity/vendor/axon/"},
            ],
        }
    ]
    html_dd = """
    <div class="deflock-reading-room__vendors">
      <h2>Vendors</h2>
      <ul class="deflock-reading-room__chips">
        <li><a class="deflock-reading-room__chip" href="/reading-room/entity/vendor/axon/">Axon</a></li>
      </ul>
    </div>
    """
    assert P.check_link_groups(dd_groups, html_dd) == []

    # Mismatches
    assert P.check_link_groups([{"heading": "Missing Heading", "items": [{"label": "X"}]}], html_live) == [
        "group #0 heading 'Missing Heading' not in page"
    ]
    assert P.check_link_groups([{"heading": "Topics", "items": [{"label": "Missing Topic"}]}], html_live) == [
        "group #0 item #0 label 'Missing Topic' not in page"
    ]
    assert P.check_link_groups(
        [{"heading": "Topics", "items": [{"label": "Surveillance", "url": "https://other.test/wrong-url/"}]}],
        html_live,
    ) == [
        "group #0 item #0 (Surveillance) url 'https://other.test/wrong-url/' not in page"
    ]
    assert P.check_link_groups(
        [{"heading": "Named in this document", "items": [{"label": "Flock Safety", "quote": "truncated quote that doesn't match"}]}],
        html_live,
    ) == [
        "group #0 item #0 (Flock Safety) quote \"truncated quote that doesn't match\" not in page"
    ]


def test_check_notes_parity():
    from roomkit import parity as P

    # Live GG markup
    html_gg = """
    <div class="ggrr-doc__notes">
      <h2>Notes</h2>
      <p>Line one<br />Line two</p>
    </div>
    """
    assert P.check_notes("Line one\nLine two", html_gg) == []

    # Live DD markup
    html_dd = """
    <section class="deflock-reading-room__notes">
      <h2>Notes</h2>
      <p>Line one<br />Line two</p>
    </section>
    """
    assert P.check_notes("Line one\nLine two", html_dd) == []

    # Roomkit static markup
    html_static = """
    <section class="room__panel" aria-labelledby="room-notes-h">
      <h2 id="room-notes-h">Notes</h2>
      <p class="room__notes">Line one<br>Line two</p>
    </section>
    """
    assert P.check_notes("Line one\nLine two", html_static) == []

    # Absent/suppressed notes with clean page
    html_clean = "<main><h1>Document</h1><p>Citation</p></main>"
    assert P.check_notes("", html_clean) == []
    assert P.check_notes(None, html_clean) == []

    # Multiline notes with HTML entities
    html_entities = '<p class="room__notes">One<br><br>Three &amp; &lt;four&gt;</p>'
    assert P.check_notes("One\n\nThree & <four>", html_entities) == []

    # Mismatches
    assert P.check_notes("Different text", html_gg) == ["notes 'Different text' not in page"]
    assert P.check_notes("Line one\nLine two", html_clean) == [
        "notes 'Line one\\nLine two' not in page",
        "notes block absent from page",
    ]
    assert P.check_notes("", html_gg) == ["unexpected notes block in page"]
    assert P.check_notes(None, html_dd) == ["unexpected notes block in page"]


def test_check_copy_citation_parity():
    from roomkit import parity as P

    cite = "Agency, Camera Contract (2026). https://example.test/reading-room/camera-contract/"
    # Live GG markup
    html_gg = f"""
    <div class="ggrr-doc__cite">
      <p class="ggrr-doc__cite-text" id="ggrr-cite-text">{cite}</p>
      <button type="button" class="ggrr-doc__btn ggrr-doc__btn--ghost ggrr-doc__cite-copy" data-ggrr-cite-copy data-cite="{cite}" hidden>Copy citation</button>
    </div>
    """
    assert P.check_copy_citation(cite, html_gg) == []

    # Live DD markup
    html_dd = f"""
    <section class="deflock-reading-room__cite">
      <p class="deflock-reading-room__cite-text">{cite}</p>
      <button type="button" class="deflock-reading-room__button deflock-reading-room__button--secondary deflock-reading-room__cite-copy" data-rr-cite-copy data-cite="{cite}" data-cite-copied-label="Copied" hidden>Copy citation</button>
    </section>
    """
    assert P.check_copy_citation(cite, html_dd) == []

    # Roomkit static markup
    html_static = f"""
    <p class="room__cite-text">{cite}</p>
    <button type="button" class="room__btn room__btn--ghost room__cite-copy" data-rr-cite-copy data-cite="{cite}" data-cite-copied-label="Copied" hidden>Copy citation</button>
    """
    assert P.check_copy_citation(cite, html_static) == []

    # Mismatches
    assert P.check_copy_citation(cite, "<main><p>No button here</p></main>") == [
        "no copy citation button"
    ]
    html_unhidden = f'<button type="button" data-rr-cite-copy data-cite="{cite}">Copy</button>'
    assert P.check_copy_citation(cite, html_unhidden) == [
        "copy citation button not hidden for no-JS"
    ]
    html_missing_cite = '<button type="button" data-rr-cite-copy hidden>Copy</button>'
    assert P.check_copy_citation(cite, html_missing_cite) == [
        "copy citation button missing data-cite"
    ]
    html_wrong_cite = '<button type="button" data-rr-cite-copy data-cite="Different citation" hidden>Copy</button>'
    assert P.check_copy_citation(cite, html_wrong_cite) == [
        f"copy citation data-cite 'Different citation' != {cite!r}"
    ]




