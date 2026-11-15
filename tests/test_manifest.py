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
            "original_url": "/reading-room/camera-contract/file/?original=1",
            "ia_url": "https://archive.org/details/test",
            "ia_pending": False,
            "category": "contracts",
        }
    }
    m = parse(data)
    assert not m.refusals
    hdr = m.documents[0].display["header"]
    assert hdr["meta"] == ["Agency", "Collection", "2020-2025"]
    assert hdr["original_url"] == "/reading-room/camera-contract/file/?original=1"
    assert hdr["ia_url"] == "https://archive.org/details/test"
    assert hdr["category"] == "contracts"


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
    from tests.roomkit.test_golden import ENGINE

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

    for url in ("https://example.test/reading-room/excluded-doc/", "/reading-room/excluded-doc/",
                "https://EXAMPLE.test/reading-room/excluded-doc/", "https://example.test:443/reading-room/excluded-doc/",
                "https://example.test/reading-room/x/../excluded-doc/", "/reading-room/%65xcluded-doc/"):
        res, problems = E.parse(_entity_block(url), "https://example.test", "/reading-room/", {"camera-contract"})
        assert res is None
        assert any("excluded-doc' is not a public record in this room" in p for p in problems)


def test_entity_page_allows_external_document_link():
    from roomkit import entities as E

    _, problems = E.parse(_entity_block("https://other.example/records/excluded-doc/"),
                          "https://example.test", "/reading-room/", {"camera-contract"})
    assert not any("is not a public record" in p for p in problems)


def test_entity_page_rejects_a_public_slug_naming_a_withheld_url():
    from roomkit import entities as E

    block = _entity_block("https://example.test/reading-room/excluded-doc/")
    block["pages"][0]["groups"][0]["documents"][0]["slug"] = "camera-contract"
    res, problems = E.parse(block, "https://example.test", "/reading-room/", {"camera-contract"})
    assert res is None and any("is not a public record" in p for p in problems)
