"""Manifest parsing, validation and refusals for reading-room."""

from __future__ import annotations

import copy
import json

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


def test_check_jsonld_parity():
    from roomkit import parity as P

    jsonld_gg = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": "Camera Contract",
        "description": "Summary of camera contract.",
        "url": "https://glassgovernment.org/library/camera-contract/",
        "mainEntityOfPage": "https://glassgovernment.org/library/camera-contract/",
        "datePublished": "2026-01-31",
        "author": {"@type": "Organization", "name": "Test Agency"},
        "genre": "Contracts",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "identifier": "a" * 64,
        "creativeWorkStatus": "none",
    }
    # Matches live WordPress pretty-printed output
    html_gg = f'<script type="application/ld+json">\n{json.dumps(jsonld_gg, indent=4)}\n</script>'
    assert P.check_jsonld(jsonld_gg, html_gg) == []

    # Matches Deflock Dane output with isPartOf
    jsonld_dd = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": "Axon Contract",
        "description": "City of Madison Axon contract.",
        "url": "https://deflockdane.org/reading-room/axon-contract/",
        "mainEntityOfPage": "https://deflockdane.org/reading-room/axon-contract/",
        "datePublished": "2026-01-31",
        "author": {"@type": "Organization", "name": "Madison Police Department"},
        "identifier": "b" * 64,
        "isPartOf": {
            "@type": "Collection",
            "name": "Deflock Dane Reading Room",
            "url": "https://deflockdane.org/reading-room/",
        },
    }
    html_dd = f'<script type="application/ld+json">{json.dumps(jsonld_dd)}</script>'
    assert P.check_jsonld(jsonld_dd, html_dd) == []

    # Author omitted when agency is unknown
    jsonld_no_author = dict(jsonld_gg)
    del jsonld_no_author["author"]
    html_no_author = f'<script type="application/ld+json">{json.dumps(jsonld_no_author)}</script>'
    assert P.check_jsonld(jsonld_no_author, html_no_author) == []

    # Escaped solidus (e.g. </script> in values)
    jsonld_escaped = {"@type": "DigitalDocument", "name": "</script><script>alert(1)"}
    html_escaped = '<script type="application/ld+json">{"@type": "DigitalDocument", "name": "<\\/script><script>alert(1)"}</script>'
    assert P.check_jsonld(jsonld_escaped, html_escaped) == []

    # Clean page without JSON-LD when none expected
    assert P.check_jsonld(None, "<main><h1>Doc</h1></main>") == []

    # Mismatches
    assert P.check_jsonld(jsonld_gg, "<main><h1>No script</h1></main>") == [
        "no jsonld script tag"
    ]
    assert P.check_jsonld(None, html_gg) == [
        "unexpected jsonld script tag"
    ]
    assert P.check_jsonld(jsonld_gg, '<script type="application/ld+json">{bad json}</script>') == [
        "malformed jsonld: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
    ]
    # Missing key
    assert P.check_jsonld(jsonld_gg, html_no_author) == [
        "jsonld missing key 'author'"
    ]
    # Unexpected key
    assert P.check_jsonld(jsonld_no_author, html_gg) == [
        "jsonld unexpected key 'author'"
    ]
    # Mismatched value
    wrong_name = dict(jsonld_gg, name="Different Title")
    assert P.check_jsonld(wrong_name, html_gg) == [
        "jsonld name 'Camera Contract' != 'Different Title'"
    ]


def test_mask_sensitive_ssn():
    from roomkit.search import REDACTED_SSN, mask_sensitive

    assert mask_sensitive("SSN: 123-45-6789 confirmed", REDACTED_SSN) == f"SSN: {REDACTED_SSN} confirmed"
    assert mask_sensitive("SSN: 123 45 6789 confirmed", REDACTED_SSN) == f"SSN: {REDACTED_SSN} confirmed"
    assert mask_sensitive("SSN: 123 - 45 - 6789 confirmed", REDACTED_SSN) == f"SSN: {REDACTED_SSN} confirmed"
    assert mask_sensitive("SSN: 123-45-6789 confirmed") == "SSN:  confirmed"
    assert mask_sensitive("Contract 202610141") == "Contract 202610141"
    assert mask_sensitive("Area 000-12-3456 invalid") == "Area 000-12-3456 invalid"
    assert mask_sensitive("Area 666-12-3456 invalid") == "Area 666-12-3456 invalid"
    assert mask_sensitive("") == ""


def test_scan_page_images_and_boxes_parse_cleanly() -> None:
    data = _valid_manifest()
    data["documents"][0]["pages"] = [
        {
            "n": 1,
            "text": "Page one transcript",
            "provenance": "ocr",
            "image_url": "/reading-room/camera-contract/pages/page-1.webp",
            "boxes": [
                {
                    "text": "Page one",
                    "box": [0.1, 0.2, 0.15, 0.4],
                    "confidence": 0.95,
                }
            ],
        },
        {
            "n": 2,
            "text": "Page two transcript",
            "provenance": "ocr",
            "image_url": "https://example.test/pages/page-2.webp",
        },
    ]
    m = parse(data)
    assert not m.refusals
    doc = m.documents[0]
    assert len(doc.pages) == 2
    assert doc.pages[0].image_url == "/reading-room/camera-contract/pages/page-1.webp"
    assert len(doc.pages[0].boxes) == 1
    assert doc.pages[0].boxes[0]["box"] == [0.1, 0.2, 0.15, 0.4]
    assert doc.pages[0].boxes[0]["confidence"] == 0.95
    assert doc.pages[1].image_url == "https://example.test/pages/page-2.webp"
    assert doc.pages[1].boxes == ()


def test_scan_page_image_url_refusal() -> None:
    data = _valid_manifest()
    data["documents"][0]["pages"][0]["image_url"] = "javascript:alert(1)"
    m = parse(data)
    assert len(m.refusals) == 1
    assert "image_url 'javascript:alert(1)' is not https:// or a same-host path" in m.refusals[0][1]


def test_scan_page_boxes_validation_refusals() -> None:
    data = _valid_manifest()

    # Boxes not a list
    d1 = copy.deepcopy(data)
    d1["documents"][0]["pages"][0]["boxes"] = "not-a-list"
    assert "boxes is not a list" in parse(d1).refusals[0][1]

    # Box not a dict
    d2 = copy.deepcopy(data)
    d2["documents"][0]["pages"][0]["boxes"] = ["not-a-dict"]
    assert "box #0 is not an object" in parse(d2).refusals[0][1]

    # Coord not 4 numbers
    d3 = copy.deepcopy(data)
    d3["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.2, 0.3]}]
    assert "coord must be 4 numbers" in parse(d3).refusals[0][1]

    # Out of bounds (< 0.0)
    d4 = copy.deepcopy(data)
    d4["documents"][0]["pages"][0]["boxes"] = [{"box": [-0.1, 0.2, 0.5, 0.6]}]
    assert "coord out of bounds or inverted" in parse(d4).refusals[0][1]

    # Out of bounds (> 1.0)
    d5 = copy.deepcopy(data)
    d5["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.2, 1.2, 0.6]}]
    assert "coord out of bounds or inverted" in parse(d5).refusals[0][1]

    # Inverted y (ymin >= ymax)
    d6 = copy.deepcopy(data)
    d6["documents"][0]["pages"][0]["boxes"] = [{"box": [0.5, 0.2, 0.4, 0.6]}]
    assert "coord out of bounds or inverted" in parse(d6).refusals[0][1]

    # Inverted x (xmin >= xmax)
    d7 = copy.deepcopy(data)
    d7["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.8, 0.3, 0.7]}]
    assert "coord out of bounds or inverted" in parse(d7).refusals[0][1]

    # Confidence out of bounds
    d8 = copy.deepcopy(data)
    d8["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.2, 0.3, 0.4], "confidence": 1.5}]
    assert "confidence must be a number between 0 and 1 or null" in parse(d8).refusals[0][1]


def test_scan_pages_json_serialization() -> None:
    from roomkit import build as B
    from tests.test_golden import ENGINE

    data = _valid_manifest()
    data["documents"][0]["pages"][0]["image_url"] = "/reading-room/camera-contract/pages/p1.webp"
    data["documents"][0]["pages"][0]["boxes"] = [
        {"text": "Sample", "box": [0.1, 0.2, 0.3, 0.4], "confidence": 0.99}
    ]
    m = parse(data)
    files = B.render(m, engine=ENGINE)
    # Find fingerprinted pages.json
    pages_key = next(k for k in files if k.startswith("camera-contract/pages.") and k.endswith(".json"))
    rendered_json = json.loads(files[pages_key].decode("utf-8"))
    assert rendered_json["total"] == 2
    p1 = rendered_json["pages"][0]
    assert p1["n"] == 1
    assert p1["image_url"] == "/reading-room/camera-contract/pages/p1.webp"
    assert p1["boxes"] == [{"text": "Sample", "box": [0.1, 0.2, 0.3, 0.4], "confidence": 0.99}]
    p2 = rendered_json["pages"][1]
    assert "image_url" not in p2
    assert "boxes" not in p2


def test_table_csv_tsv_manifest_parses_cleanly() -> None:
    data = _valid_manifest()
    data["documents"][0]["file"]["ext"] = "csv"
    data["documents"][0]["file"]["mime"] = "text/csv"
    data["documents"][0]["file"]["url"] = "/reading-room/camera-contract/file.csv"
    data["documents"][0]["file"]["download_url"] = "/reading-room/camera-contract/file.csv?download=1"

    m = parse(data)
    assert not m.refusals
    assert m.documents[0].ext == "csv"

    # Also TSV
    data["documents"][0]["file"]["ext"] = "tsv"
    data["documents"][0]["file"]["mime"] = "text/tab-separated-values"
    data["documents"][0]["file"]["url"] = "/reading-room/camera-contract/file.tsv"
    data["documents"][0]["file"]["download_url"] = "/reading-room/camera-contract/file.tsv?download=1"

    m2 = parse(data)
    assert not m2.refusals
    assert m2.documents[0].ext == "tsv"


def test_table_csv_tsv_module_resolution() -> None:
    from roomkit import build as B
    from roomkit.manifest import TABLE

    assert "csv" in TABLE and "tsv" in TABLE
    assert B._module("csv") == "rr-reader-table.js"
    assert B._module("tsv") == "rr-reader-table.js"
    assert B._module("pdf") == "rr-reader-pdf.js"
    assert B._module("txt") == "rr-reader-text.js"









def _entity_block(doc_url: str) -> dict:
    return {"pages": [{
        "type": "vendor", "slug": "axon", "head_title": "Axon", "title": "Axon",
        "url": "https://example.test/reading-room/entity/vendor/axon/", "empty_text": "No documents",
        "groups": [{"heading": "Contracts", "documents": [
            {"slug": "excluded-doc", "title": "Excluded Doc", "url": doc_url}]}],
    }]}


def test_entity_page_rejects_non_public_document_slug():
    from roomkit import entities as E

    for url in ("https://example.test/reading-room/excluded-doc/", "/reading-room/excluded-doc/"):
        res, problems = E.parse(_entity_block(url), "https://example.test", "/reading-room/", {"camera-contract"})
        assert res is None
        assert any("excluded-doc' is not a public record in this room" in p for p in problems)


def test_entity_page_allows_external_document_link():
    from roomkit import entities as E

    _, problems = E.parse(_entity_block("https://other.example/records/excluded-doc/"),
                          "https://example.test", "/reading-room/", {"camera-contract"})
    assert not any("is not a public record" in p for p in problems)


def test_build_pages_json_masks_sensitive_text():
    from roomkit import build as B
    from roomkit.search import REDACTED_SSN

    m_data = _valid_manifest()
    m_data["documents"][0]["pages"] = [
        {"n": 1, "text": "Confidential report. Subject SSN: 123-45-6789 on file."}
    ]
    manifest = parse(m_data)
    files = B.render(manifest, engine=B.ENGINE)
    p_key = next(k for k in files if k.startswith("camera-contract/pages.") and k.endswith(".json"))
    pages_json = json.loads(files[p_key].decode())
    assert pages_json["pages"][0]["text"] == f"Confidential report. Subject SSN: {REDACTED_SSN} on file."
