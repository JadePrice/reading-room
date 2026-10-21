"""Passage citations (GG, plan Task 12): the switch, the block's refusals, what the
room ships, parity.passages, and the reader's cite panel in a browser.

The fixture is hand-made (tests/roomkit/fixtures/passages-glassgovernment.json),
shaped like exporters/glassgovernment.php's passage fields, over the golden
manifest's records. The exporter itself ran under PHP 8.3 with WordPress stubs
(/srv/tmp/wt-room-passages-checkpoints.md); the gate has no php binary, so it is
checked here as text, like test_exporter_json.py.
"""

from __future__ import annotations

import copy
import functools
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import pack as K
from roomkit import passage_parity as PP
from roomkit import passages as PS
from roomkit.manifest import parse

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
ENGINE = GOLDEN / "engine"
FIXTURE = json.loads((HERE / "fixtures" / "passages-glassgovernment.json").read_text(encoding="utf-8"))
KEY = FIXTURE["passages"]["citations"][0]["stable_key"]


def _raw(passages: bool = True) -> dict:
    m = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    m["site"]["template"] = "glassgovernment"
    m["site"]["room_path"] = "/library/"
    if passages:
        for d in m["documents"]:
            if d["slug"] in FIXTURE["document_ids"]:
                d["document_id"] = FIXTURE["document_ids"][d["slug"]]
            for p, c in zip(d.get("pages") or [], FIXTURE["page_cites"].get(d["slug"], [])):
                p["cite"] = copy.deepcopy(c)
        m["passages"] = copy.deepcopy(FIXTURE["passages"])
    return m


def _pack(on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site("glassgovernment"))
    if on:
        p["features"] = {**p.get("features", {}), "passage-cite": True}
    return p


def _render(on: bool = True, raw: dict | None = None, **kw) -> dict[str, bytes]:
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, pack=_pack(on), **kw)


def _config(files) -> dict:
    s = files[B.published(files, "assets/rr-config.js")].decode()
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def _pages(files, slug="camera-contract") -> list[dict]:
    return json.loads(files[B.published(files, f"{slug}/pages.json")])["pages"]


# --- the switch ------------------------------------------------------------------

def test_switch_off_builds_exactly_the_room_without_passages():
    assert _render(on=False) == B.render(parse(_raw(passages=False)), engine=ENGINE, pack=_pack(on=False))


def test_switch_off_keeps_the_golden_bytes():
    from tests.roomkit import test_golden as G
    G.CASES["glassgovernment"]()  # the case exists
    raw = _raw()
    files = B.render(parse(raw), engine=ENGINE)  # the committed GG pack: switch off
    plain = B.render(parse(_raw(passages=False)), engine=ENGINE)
    assert files == plain
    assert "citations.json" not in files and _config(files)["passageUrl"] == ""


def test_every_committed_pack_has_the_switch_off():
    for site in ("default", "deflockdane", "glassgovernment", "hrtarchive"):
        assert not PS.enabled(K.for_site(site)), site


def test_switch_on_without_a_block_wires_no_route():
    files = _render(raw=_raw(passages=False))
    assert _config(files)["passageUrl"] == "" and "citations.json" not in files
    assert all("cite" not in p for p in _pages(files))


# --- what the room ships ---------------------------------------------------------

def test_switch_on_ships_the_route_the_page_citations_and_citations_json():
    files = _render()
    assert _config(files)["passageUrl"] == FIXTURE["passages"]["api"]
    assert [p["cite"] for p in _pages(files)] == FIXTURE["page_cites"]["camera-contract"]
    assert all("cite" not in p for p in _pages(files, "memo-text"))  # no cite exported, none shipped
    got = json.loads(files["citations.json"])
    want = {k: v for k, v in FIXTURE["passages"]["citations"][0].items() if k != "slug"}
    assert got == {"citations": {KEY: {"found": True, "citation": want}}}


def test_the_room_composes_no_citation_and_never_shows_the_ids():
    files = _render()
    html = b"".join(b for p, b in files.items() if p.endswith(".html")).decode()
    assert "document_id" not in html and '"7"' not in html
    for c in FIXTURE["page_cites"]["camera-contract"]:
        assert c["reference"] not in html  # page citations live in pages.json, read by the reader
    src = "".join((Path(B.__file__).parent / f).read_text() for f in ("passages.py", "build.py", "view.py"))
    assert "format_reference" not in src.replace("GGRR_Citations::format_reference", "")
    assert "Glass Government" not in src


def test_a_page_cite_without_the_switch_is_still_checked():
    raw = _raw()
    raw["documents"][0]["pages"][0]["cite"] = {"reference": ""}
    assert parse(raw).refusals


# --- refusals --------------------------------------------------------------------

def _refusals(mutate) -> list[str]:
    raw = _raw()
    mutate(raw)
    return [why for rid, why in parse(raw).refusals]


def _cite(raw):
    return raw["passages"]["citations"][0]


@pytest.mark.parametrize("mutate,says", [
    (lambda r: r["passages"].update(api="http://example.test/wp-json/ggrr/v1/passage"), "is not an https:// URL"),
    (lambda r: r["passages"].update(api="https://example.test/p?x=1"), "without a query"),
    (lambda r: _cite(r).update(slug="no-such-record"), "not a record in this room"),
    (lambda r: _cite(r).update(document_id=8), "is not camera-contract's"),
    (lambda r: _cite(r).update(stable_key="0" * 64), "stable_key is not sha256"),
    (lambda r: _cite(r).update(text="two"), "is not page 1's text"),
    (lambda r: _cite(r).update(page_number=5, stable_key=PS.stable_key(7, 5, 5, 8)), "has no page 5"),
    (lambda r: _cite(r).update(offset_start=8), "0 <= start < end"),
    (lambda r: _cite(r).pop("page_id"), "is not {slug, stable_key"),
    (lambda r: r["passages"]["citations"].append(copy.deepcopy(_cite(r))), "two rows with one key"),
    (lambda r: r["documents"][0].update(document_id="7"), "document_id is not a positive integer"),
    (lambda r: r["documents"][0]["pages"][0].update(cite={"reference": "x"}), "page cite is not"),
    (lambda r: r["documents"][0]["pages"][0]["cite"].update(ocr_confidence="0.9"), "ocr_confidence is not a number"),
    (lambda r: r["passages"].update(source={"f.php": "nothex"}), "passages.source"),
    (lambda r: r.update(passages=[]), "passages is not an object"),
])
def test_a_bad_block_is_refused_with_the_reason(mutate, says):
    probs = _refusals(mutate)
    assert any(says in p for p in probs), probs


def test_a_refused_block_stops_the_build(tmp_path):
    raw = _raw()
    _cite(raw)["text"] = "two"
    (tmp_path / "m.json").write_text(json.dumps(raw))
    assert cli.main(["build", "--manifest", str(tmp_path / "m.json"), "--out", str(tmp_path / "room")]) == 1
    assert not (tmp_path / "room").exists()


def test_a_citation_of_an_excluded_record_is_excluded_and_named(tmp_path, capsys):
    raw = _raw()
    raw["excluded"] = [{"slug": "benefits-snap-7cfr271", "problem": "no servable file"}]
    gone = copy.deepcopy(_cite(raw)) | {"slug": "benefits-snap-7cfr271", "stable_key": "4" * 64}
    raw["passages"]["citations"].append(gone)
    m = parse(raw)
    assert not m.refusals
    assert ("4" * 64, "its record (benefits-snap-7cfr271) is excluded: no servable file") in m.passages["excluded"]
    (tmp_path / "m.json").write_text(json.dumps(raw))
    assert cli.main(["build", "--manifest", str(tmp_path / "m.json"), "--out", str(tmp_path / "room")]) == 0
    out = capsys.readouterr().out
    assert f"EXCLUDED by the exporter: citation {'3' * 64}" in out and f"citation {'4' * 64}" in out


def test_stable_key_and_slices_are_the_plugins():
    # GGRR_Citations::stable_key, checked against a live answer (2026-10-15).
    assert PS.stable_key(505, 2, 72, 152) == "e8e78fcf23f030f850ebfe52560d74b314ac7940df95006ff235fcb650fdbed7"
    assert PS.stable_key(7, None, 0, 3) == __import__("hashlib").sha256(b"7||0|3").hexdigest()
    assert PS.slice_text("\U0001F693 café flock", 2, 6) == "café"   # code points, as mb_substr


# --- the exporter, as text ---------------------------------------------------------

EXPORTER = (B.REPO_ROOT / "roomkit/exporters/glassgovernment.php").read_text(encoding="utf-8")


def test_the_exporter_emits_the_passage_fields_from_the_plugins_helpers():
    assert "'document_id' => $id," in EXPORTER
    # the page cite: the passage route's reference for ?slug=&page=N
    assert re.search(r"'reference' => GGRR_Citations::format_reference\(.*?\$permalink \. '#page-' \. \(int\) \$p\['page_number'\], "
                     r"\(int\) \$p\['page_number'\]", EXPORTER, re.DOTALL)
    # its own date formula, as class-ggrr-rest.php passage() writes it
    assert "$p_date = !empty($doc['document_date']) ? $T::format_display_date((string) $doc['document_date']) : 'n.d.';" in EXPORTER
    assert "SELECT page_number, ocr_text, provenance_level, ocr_confidence FROM" in EXPORTER
    assert "'api' => rest_url('ggrr/v1/passage')," in EXPORTER
    assert "GGRR_Citations::get_by_stable_key($key)" in EXPORTER
    assert "'problem' => 'its record is not public'" in EXPORTER
    assert "($passages ? ['passages' => $passages] : [])" in EXPORTER
    # read-only: nothing that mints or writes
    assert "::mint(" not in EXPORTER and "$wpdb->insert" not in EXPORTER and "$wpdb->update" not in EXPORTER


# --- parity.passages ---------------------------------------------------------------

def _built(tmp_path) -> Path:
    B.write(_render(), tmp_path / "room")
    return tmp_path / "room"


def _live(room: dict) -> dict:
    pages = room["pages"]["camera-contract"]
    c = {k: v for k, v in FIXTURE["passages"]["citations"][0].items() if k != "slug"}
    return {
        "site": "glassgovernment", "fetched": "2026-10-15T00:00:00Z", "source": "test",
        "pages": [{"slug": "camera-contract", "page": p["n"], "status": 200,
                   "response": {"found": True, "reference": p["cite"]["reference"],
                                "passage": {"provenance_level": p["cite"]["provenance_level"],
                                            "ocr_confidence": p["cite"]["ocr_confidence"]}}} for p in pages],
        "spans": [{"slug": "camera-contract", "page": 2, "start": 0, "end": 4, "status": 200,
                   "response": {"found": True, "reference": pages[1]["cite"]["reference"],
                                "passage": {"document_id": 7, "page_number": 2, "offset_start": 0, "offset_end": 4,
                                            "stable_key": PS.stable_key(7, 2, 0, 4), "text": "Page"}}}],
        "citations": [{"key": KEY, "status": 200, "response": {"found": True, "citation": c}}],
    }


def test_parity_agrees_when_live_says_what_the_room_says(tmp_path, capsys):
    room = PP.room_data(_built(tmp_path))
    rep = PP.compare(_live(room), room)
    assert rep["ok"], PP.text(rep)
    assert PP.text(rep).startswith("AGREES: pages 2/2, spans 1/1, citations 1/1")
    (tmp_path / "live.json").write_text(json.dumps(_live(room)))
    assert cli.main(["parity", "--passages", str(tmp_path / "live.json"), "--out", str(tmp_path / "room")]) == 0


@pytest.mark.parametrize("break_it,says", [
    (lambda L: L["pages"][0]["response"].update(reference="other"), "reference differs"),
    (lambda L: L["pages"][1]["response"]["passage"].update(ocr_confidence=0.5), "ocr_confidence differs"),
    (lambda L: L["pages"][0].update(status=404, response={"found": False, "error": "not_found"}), "live answered 404 not_found"),
    (lambda L: L["spans"][0]["response"]["passage"].update(text="Pag"), "not the room's page text"),
    (lambda L: L["spans"][0]["response"]["passage"].update(stable_key="0" * 64), "stable_key is not sha256"),
    (lambda L: L["spans"][0]["response"].update(reference="x"), "not the room's page citation"),
    (lambda L: L["citations"][0]["response"]["citation"].update(citation_type="other"), "citations.json differs from live in citation_type"),
    (lambda L: L["citations"][0]["response"]["citation"].update(text="xyz"), "no record in the room has that text"),
    (lambda L: L.update(stopped="429 on pages"), "fetch stopped early"),
])
def test_parity_names_each_kind_of_difference(tmp_path, break_it, says):
    room = PP.room_data(_built(tmp_path))
    live = _live(room)
    break_it(live)
    rep = PP.compare(live, room)
    assert not rep["ok"] and says in PP.text(rep), PP.text(rep)


def test_a_document_scope_citation_is_held_to_citations_json(tmp_path):
    raw = _raw()
    doc = copy.deepcopy(_cite(raw)) | {"page_number": None, "offset_start": 0, "offset_end": 3, "text": "",
                                       "stable_key": PS.stable_key(7, None, 0, 3)}
    raw["passages"]["citations"].append(doc)
    B.write(_render(raw=raw), tmp_path / "room")
    room = PP.room_data(tmp_path / "room")
    live = _live(room)
    c = {k: v for k, v in doc.items() if k != "slug"}
    live["citations"].append({"key": doc["stable_key"], "status": 200, "response": {"found": True, "citation": c}})
    rep = PP.compare(live, room)
    assert rep["ok"], PP.text(rep)
    assert "1 citation(s) document-scope" in PP.text(rep)
    live["citations"][-1]["response"]["citation"] = c | {"text": "abc"}
    assert "citations.json differs from live in text" in PP.text(PP.compare(live, room))
    del room["citations"][doc["stable_key"]]
    live["citations"][-1]["response"]["citation"] = c
    assert "document-scope citation the room does not ship" in PP.text(PP.compare(live, room))


def test_the_fetch_is_paced_read_only_and_stops_at_a_429(tmp_path):
    room = PP.room_data(_built(tmp_path))
    want = PP.plan(room, 2, [KEY])
    assert [(w["slug"], w["page"]) for w in want["pages"]] == [("camera-contract", 1), ("camera-contract", 2)]
    asked, slept = [], []
    answers = iter([(200, "{}"), (429, ""), (200, "{}")])

    def get(url):
        asked.append(url)
        return next(answers)
    live = PP.fetch(room["api"], want, get=get, pace=2.0, sleep=slept.append)
    assert len(asked) == 2 and slept == [2.0]
    assert asked[0] == FIXTURE["passages"]["api"] + "?slug=camera-contract&page=1"
    assert live["stopped"].startswith("429 on pages") and len(live["pages"]) == 1
    with pytest.raises(PP.LiveError):
        PP.fetch("", want, get=get)


def test_the_curated_key_is_asked_of_the_citation_route(tmp_path):
    room = PP.room_data(_built(tmp_path))
    asked = []
    PP.fetch(room["api"], {"pages": [], "spans": [], "citations": [{"key": KEY}]},
             get=lambda u: (asked.append(u), (200, "{}"))[1], sleep=lambda s: None)
    assert asked == ["https://example.test/wp-json/ggrr/v1/citation?key=" + KEY]


# --- in a browser, with the real engine (skipped without Playwright's Chromium) ----

@pytest.fixture(scope="module")
def passage_room(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    fitz = pytest.importorskip("fitz")
    root = tmp_path_factory.mktemp("passage-room")
    (root / "files").mkdir()
    doc = fitz.open()
    for n in ("one", "two"):
        doc.new_page(width=612, height=792).insert_text((72, 120), f"Page {n}", fontsize=20)
    doc.save(root / "files" / "camera.pdf")
    raw = _raw()
    raw["documents"][0]["file"].update(url="/files/camera.pdf", download_url="/files/camera.pdf")
    m = parse(raw)
    assert not m.refusals, m.refusals
    B.write(B.render(m, pack=_pack()), root / "library")  # the real engine
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            srv.shutdown()
            pytest.skip(f"Playwright Chromium not installed: {e}")
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/library/camera-contract/"
        b.close()
    srv.shutdown()


SPAN_ANSWER = {"found": True, "slug": "camera-contract",
               "permalink": "https://example.test/library/camera-contract/#page-2",
               "reference": FIXTURE["page_cites"]["camera-contract"][1]["reference"],
               "passage": {"document_id": 7, "page_number": 2, "offset_start": 0, "offset_end": 4,
                           "stable_key": PS.stable_key(7, 2, 0, 4), "provenance_level": "offset",
                           "ocr_confidence": 0.912, "bounding_box": None, "text": "Page", "minted": False}}
AXE = """() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}})
  .then(r => r.violations.map(v => v.id + ': ' + v.nodes.map(n => n.target.join(' ')).join(', ')))"""


def _open(b, url, route=None, **ctx):
    page = b.new_context(viewport={"width": ctx.pop("width", 1280), "height": 900}, **ctx).new_page()
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "wp-json" in r.url else None)
    if route:
        page.route("https://example.test/wp-json/**", route)
    page.goto(url)
    page.wait_for_function("() => /Page 1 of 2/.test(document.querySelector('.rr-reader [data-reader-status]').textContent)")
    return page, asked


def test_in_a_browser_cite_page_is_the_exported_citation_with_no_request(passage_room):
    b, url = passage_room
    page, asked = _open(b, url)
    page.get_by_role("button", name="Cite the current page").click()
    ref = page.locator(".rr-reader__cite-ref")
    ref.filter(has_text="p. 1.").wait_for()
    assert ref.inner_text() == FIXTURE["page_cites"]["camera-contract"][0]["reference"]
    assert asked == []
    page.close()


def test_in_a_browser_a_hit_cite_asks_the_route_with_its_span(passage_room):
    b, url = passage_room
    page, asked = _open(b, url, route=lambda r: r.fulfill(status=200, content_type="application/json",
                                                            body=json.dumps(SPAN_ANSWER)))
    page.get_by_role("searchbox", name="Search within this document").fill("page")
    page.get_by_role("button", name="Cite this passage on page 2").click()
    page.locator(".rr-reader__cite blockquote").filter(has_text="Page").wait_for()
    assert len(asked) == 1 and asked[0].endswith("?slug=camera-contract&page=2&start=0&end=4")
    assert "Durable key" in page.locator(".rr-reader__cite").inner_text()
    page.close()


@pytest.mark.parametrize("route", ["abort", "500"])
def test_in_a_browser_a_failed_route_gives_the_page_citation(passage_room, route):
    b, url = passage_room
    handler = (lambda r: r.abort()) if route == "abort" else (lambda r: r.fulfill(status=500, body="down"))
    page, _ = _open(b, url, route=handler)
    page.get_by_role("searchbox", name="Search within this document").fill("page")
    page.get_by_role("button", name="Cite this passage on page 2").click()
    panel = page.locator(".rr-reader__cite")
    panel.locator(".rr-reader__cite-note").filter(has_text="this cites the page").wait_for()
    assert panel.locator(".rr-reader__cite-ref").inner_text() == FIXTURE["page_cites"]["camera-contract"][1]["reference"]
    assert panel.locator("blockquote").is_hidden() and "Durable key" not in panel.inner_text()
    page.close()


@pytest.mark.parametrize("width", (375, 1280))
def test_in_a_browser_the_open_panel_passes_axe_and_fits(passage_room, width):
    from tests.reading_room_reader.conftest import axe_source
    b, url = passage_room
    for scheme in ("light", "dark"):
        page, _ = _open(b, url, route=lambda r: r.abort(), width=width, color_scheme=scheme)
        if scheme == "dark" and page.locator("[data-room-toggle]").count():
            page.locator("[data-room-toggle]").click()
        page.get_by_role("searchbox", name="Search within this document").fill("page")
        page.get_by_role("button", name="Cite this passage on page 2").click()
        page.locator(".rr-reader__cite-note").filter(has_text="this cites the page").wait_for()
        # keyboard: the panel takes focus, Close is reachable and returns focus to Cite page
        assert page.evaluate("document.activeElement.classList.contains('rr-reader__cite')")
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), width
        page.evaluate(axe_source())
        assert page.evaluate(AXE) == [], (width, scheme)
        page.get_by_role("button", name="Close citation").press("Enter")
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Cite the current page"
        page.close()


# --- a citation may pin the file it was made against (file_sha256) -------------

def _doc_sha(raw: dict) -> str:
    return next(d for d in raw["documents"] if d["slug"] == _cite(raw)["slug"])["file"]["sha256"]


def test_a_pinned_citation_matching_the_file_builds_and_is_beside_not_in_the_citation():
    raw = _raw()
    _cite(raw)["file_sha256"] = _doc_sha(raw)
    m = parse(raw)
    assert not m.refusals, m.refusals
    entry = PS.citations_json(m.passages)["citations"][KEY]
    assert entry["file_sha256"] == _doc_sha(raw)
    assert "file_sha256" not in entry["citation"]


def test_an_unpinned_citation_is_unchanged():
    m = parse(_raw())
    assert not m.refusals
    assert "file_sha256" not in PS.citations_json(m.passages)["citations"][KEY]


@pytest.mark.parametrize("pin,says", [
    ("0" * 64, "source changed since this was cited"),
    ("ABC", "file_sha256 is not 64 lowercase hex"),
    (None, None)])
def test_a_pin_that_is_not_the_files_hash_is_refused(pin, says):
    raw = _raw()
    _cite(raw)["file_sha256"] = pin
    m = parse(raw)
    if says is None:  # an explicit null is the same as no pin
        assert not m.refusals
    else:
        assert any(says in why for _, why in m.refusals), m.refusals


def test_the_exporter_pins_curated_citations_to_the_records_file():
    assert "$public_sha" in EXPORTER and "'file_sha256' => $pin" in EXPORTER
