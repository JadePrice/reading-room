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
