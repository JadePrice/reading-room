"""Contract tests for reading-room-reader/contract/*.schema.json.

Payloads mirror the response shapes verified in the site A plugin
(site-a-reading-room class-site-a-rest.php doc_search / passage) and the site B plugin
(site-b-reading-room class-site-b-reading-room-rest.php doc_search).
"""
import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

CONTRACT = Path(__file__).resolve().parents[2] / "reading-room-reader" / "contract"
ROOMKIT_GOLDEN = Path(__file__).resolve().parents[1] / "roomkit" / "golden"


def _schema(name):
    return json.loads((CONTRACT / f"{name}.schema.json").read_text())


def _validate(name, payload):
    jsonschema.validate(payload, _schema(name))


SITE_A_DOC_SEARCH = {
    "slug": "example-pd-flock",
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

SITE_B_DOC_SEARCH = {
    "slug": "example-village-flock",
    "q": "flock",
    "count": 1,
    "pages": [{"page_number": 1, "snippet": "...Flock Safety..."}],
}

PASSAGE_OK = {
    "found": True,
    "slug": "example-pd-flock",
    "permalink": "https://site-a.example/library/example-pd-flock/#page-2",
    "reference": "Example PD, Flock contract, 2025, p. 2",
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
    _validate("doc-search", SITE_A_DOC_SEARCH)


def test_dd_doc_search_valid_without_gg_only_fields():
    _validate("doc-search", SITE_B_DOC_SEARCH)


def test_doc_search_rejects_extra_top_level_field():
    bad = dict(SITE_A_DOC_SEARCH, ocr_text="full page text must never ship")
    with pytest.raises(jsonschema.ValidationError):
        _validate("doc-search", bad)


def test_doc_search_rejects_page_with_ocr_text():
    bad = json.loads(json.dumps(SITE_A_DOC_SEARCH))
    bad["pages"][0]["ocr_text"] = "leaked"
    with pytest.raises(jsonschema.ValidationError):
        _validate("doc-search", bad)


def test_doc_search_rejects_bad_slug():
    bad = dict(SITE_B_DOC_SEARCH, slug="Not A Slug")
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
    ["bad_slug", "not_found", "incomplete_span", "passage_bad_range"],
)
def test_passage_error_valid(err):
    _validate("passage", {"found": False, "error": err})


def test_passage_unknown_error_rejected():
    with pytest.raises(jsonschema.ValidationError):
        _validate("passage", {"found": False, "error": "something_else"})


# --- pages.json: what roomkit writes, held to the schema the reader reads (roadmap T2) ---


def _passages_raw(passages: bool = True) -> dict:
    """The core golden manifest; with `passages`, camera-contract carries a page citation
    per page and the manifest an (empty) passages block. Site-free, so this file runs
    in the public mirror too; a site's real passage export is tested in
    tests/roomkit/sites/test_passages_sites.py."""
    m = json.loads((ROOMKIT_GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    if passages:
        d = next(d for d in m["documents"] if d["slug"] == "camera-contract")
        d["document_id"] = 7
        for i, pg in enumerate(d["pages"], 1):
            pg["cite"] = {"reference": f'Test Agency. "Camera Contract." p. {i}. '
                                       f"https://example.test/reading-room/camera-contract/#page-{i}.",
                          "provenance_level": "page", "ocr_confidence": None}
        m["passages"] = {"api": "https://example.test/api/passage", "citations": [], "excluded": []}
    return m


def _passages_pack(on: bool = True) -> dict:
    from roomkit import build as B

    p = copy.deepcopy(B.pack_for_site("example"))
    if on:
        p["features"] = {**p.get("features", {}), "passage-cite": True}
    return p


def _built_pages():
    """Every pages.json of real builds: the golden manifest with page citations on,
    and a scan record with page images and OCR boxes."""
    from roomkit import build as B
    from roomkit import search as S
    from roomkit.manifest import parse

    raw = _passages_raw()
    raw["documents"][0]["pages"][0].update({
        "image_url": "/library/scan/page-1.webp",
        "boxes": [{"box": [0.1, 0.2, 0.15, 0.4], "text": "Flock", "confidence": 0.95},
                  {"box": [0.5, 0.5, 0.6, 0.6]}],
    })
    m = parse(raw)
    assert not m.refusals, m.refusals
    # The example pack turns corpus search on; the stand-in index is deterministic.
    files = B.render(m, engine=ROOMKIT_GOLDEN / "engine", pack=_passages_pack(), indexer=S.stand_in)
    out = {p: json.loads(b) for p, b in files.items() if p.endswith(".json") and "/pages." in p}
    assert out
    assert any("cite" in pg for d in out.values() for pg in d["pages"])
    assert any("boxes" in pg and "image_url" in pg for d in out.values() for pg in d["pages"])
    plain = B.render(parse(_passages_raw(passages=False)), engine=ROOMKIT_GOLDEN / "engine",
                     pack=_passages_pack(False), indexer=S.stand_in)
    out.update({"plain:" + p: json.loads(b) for p, b in plain.items() if p.endswith(".json") and "/pages." in p})
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


def test_pages_contract_accepts_versioned_source_metadata():
    payload = next(iter(_built_pages().values()))
    payload.update({
        "schema_version": "1.0",
        "lang": "es-MX",
        "provenance": {
            "source_url": "https://example.test/source",
            "issuing_org": "Example Agency",
            "acquisition_method": "official-publication",
            "source_state": "live",
        },
        "relations": [{"slug": "related-record", "basis": "curated", "note": "Same docket."}],
    })
    _validate("pages", payload)


def test_contract_schemas_declare_a_version():
    for name in ("doc-search", "pages", "passage"):
        assert _schema(name)["version"] == "1.0"
