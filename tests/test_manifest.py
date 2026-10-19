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

