"""Contract tests for reading-room-reader/contract/*.schema.json.

Payloads mirror the response shapes verified in the GG plugin
(gg-reading-room class-ggrr-rest.php doc_search / passage) and the DD plugin
(deflock-reading-room class-deflock-reading-room-rest.php doc_search).
"""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

CONTRACT = Path(__file__).resolve().parents[2] / "reading-room-reader" / "contract"


def _schema(name):
    return json.loads((CONTRACT / f"{name}.schema.json").read_text())


def _validate(name, payload):
    jsonschema.validate(payload, _schema(name))


GG_DOC_SEARCH = {
    "slug": "sun-prairie-pd-flock",
    "q": "flock",
    "count": 1,
    "pages": [
        {
            "page_number": 2,
            "snippet": "...the Flock camera network...",
            "offset_start": 40,
            "offset_end": 45,
            "provenance_level": "offset",
        }
    ],
}

DD_DOC_SEARCH = {
    "slug": "waunakee-flock",
    "q": "flock",
    "count": 1,
    "pages": [{"page_number": 1, "snippet": "...Flock Safety..."}],
}

PASSAGE_OK = {
    "found": True,
    "slug": "sun-prairie-pd-flock",
    "permalink": "https://glassgovernment.org/library/sun-prairie-pd-flock/#page-2",
    "reference": "Sun Prairie PD, Flock contract, 2025, p. 2",
    "passage": {
        "document_id": 17,
        "page_number": 2,
        "offset_start": 0,
        "offset_end": 12,
        "stable_key": "k_abc123",
        "provenance_level": "offset",
        "ocr_confidence": 0.91,
        "bounding_box": None,
        "text": "Flock Safety",
        "minted": True,
    },
}


def test_gg_doc_search_valid():
    _validate("doc-search", GG_DOC_SEARCH)


def test_dd_doc_search_valid_without_gg_only_fields():
    _validate("doc-search", DD_DOC_SEARCH)


def test_doc_search_rejects_extra_top_level_field():
    bad = dict(GG_DOC_SEARCH, ocr_text="full page text must never ship")
    with pytest.raises(jsonschema.ValidationError):
        _validate("doc-search", bad)


def test_doc_search_rejects_page_with_ocr_text():
    bad = json.loads(json.dumps(GG_DOC_SEARCH))
    bad["pages"][0]["ocr_text"] = "leaked"
    with pytest.raises(jsonschema.ValidationError):
        _validate("doc-search", bad)


def test_doc_search_rejects_bad_slug():
    bad = dict(DD_DOC_SEARCH, slug="Not A Slug")
    with pytest.raises(jsonschema.ValidationError):
        _validate("doc-search", bad)


def test_passage_found_valid():
    _validate("passage", PASSAGE_OK)


def test_passage_bounding_box_must_be_null():
    bad = json.loads(json.dumps(PASSAGE_OK))
    bad["passage"]["bounding_box"] = {"x": 1, "y": 2}
    with pytest.raises(jsonschema.ValidationError):
        _validate("passage", bad)


@pytest.mark.parametrize(
    "err",
    ["bad_slug", "not_found", "incomplete_span", "ggrr_passage_bad_range"],
)
def test_passage_error_valid(err):
    _validate("passage", {"found": False, "error": err})


def test_passage_unknown_error_rejected():
    with pytest.raises(jsonschema.ValidationError):
        _validate("passage", {"found": False, "error": "something_else"})


# --- pages.json: what roomkit writes, held to the schema the reader reads (roadmap T2) ---


def _built_pages():
    """Every pages.json of a real build: the golden manifest, with page images and
    OCR boxes on its first paged record."""
    from roomkit import build as B
    from roomkit.manifest import parse

    golden = Path(__file__).resolve().parents[1] / "golden"
    raw = json.loads((golden / "manifest.json").read_text(encoding="utf-8"))
    doc = next(d for d in raw["documents"] if d.get("pages"))
    doc["pages"][0].update({
        "image_url": "/reading-room/scan/page-1.webp",
        "boxes": [{"box": [0.1, 0.2, 0.15, 0.4], "text": "Flock", "confidence": 0.95},
                  {"box": [0.5, 0.5, 0.6, 0.6]}],
    })
    m = parse(raw)
    assert not m.refusals, m.refusals
    files = B.render(m, engine=golden / "engine")
    out = {p: json.loads(b) for p, b in files.items() if p.endswith(".json") and "/pages." in p}
    assert out
    assert any("boxes" in pg and "image_url" in pg for d in out.values() for pg in d["pages"])
    return out


def test_every_built_pages_json_is_the_contract():
    for path, payload in _built_pages().items():
        try:
            _validate("pages", payload)
        except jsonschema.ValidationError as exc:
            raise AssertionError(f"{path}: {exc.message}") from exc


def test_pages_contract_refuses_a_field_the_reader_does_not_know():
    payload = next(iter(_built_pages().values()))
    payload["pages"][0]["html"] = "<b>markup is never a page field</b>"
    with pytest.raises(jsonschema.ValidationError):
        _validate("pages", payload)
