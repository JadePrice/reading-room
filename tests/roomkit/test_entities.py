"""Entities (plan Task 7): the entity index and entity pages, behind the pack's switch.

The fixtures are hand-made `entities` blocks over the golden manifest's records,
shaped like each site's export (tests/roomkit/fixtures/entities-*.json). Every
word on the pages is the export's: change it there and the page changes.
"""

from __future__ import annotations

import base64
import copy
import functools
import itertools
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import entities as E
from roomkit import entity_parity as EP
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit.manifest import parse

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
ENGINE = GOLDEN / "engine"
SITES = ("deflockdane", "glassgovernment")


def _block(site: str) -> dict:
    return json.loads((HERE / "fixtures" / f"entities-{site}.json").read_text(encoding="utf-8"))["entities"]


def _raw(site: str, entities: bool = True, text_only: bool = True) -> dict:
    """The golden manifest with the site's entities block. GG's block lists a text-only
    record (the live site has them; the room holds them since 2026-10-20), so it is
    added to the documents too. `text_only=False` leaves it out of both, which the
    golden-bytes tests need (the golden manifest has no such record)."""
    m = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    m["site"]["template"] = site
    if site == "glassgovernment":
        m["site"]["room_path"] = "/library/"
    if entities:
        block = _block(site)
        if site == "glassgovernment":
            if text_only:
                m["documents"].append({
                    "slug": "cfr-text-only", "title": "A text-only record", "visibility": "public",
                    "citation": "Test Agency, A text-only record.", "file": None,
                    "search_text": "Regulation text that is searchable and not shown.",
                    "display": {"no_file": "No file is attached to this record yet."}})
            else:
                for pg in block["pages"]:
                    for g in pg.get("groups", []):
                        g["documents"] = [d for d in g.get("documents", []) if d.get("slug") != "cfr-text-only"]
        m["entities"] = block
    return m


def _pack(site: str, on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site(site))
    p["features"] = {**p.get("features", {}), "entities": on}
    return p


def _render(site: str, on: bool = True, raw: dict | None = None, **kw) -> dict[str, bytes]:
    m = parse(raw if raw is not None else _raw(site))
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, indexer=S.stand_in, pack=_pack(site, on), **kw)


def _main(html: bytes | str) -> str:
    s = html.decode() if isinstance(html, bytes) else html
    return s[s.index("<main"):s.index("</main>")]


# --- the switch ------------------------------------------------------------------------

@pytest.mark.parametrize("site", SITES)
def test_switch_off_builds_exactly_the_room_without_entities(site):
    with_block = B.render(parse(_raw(site, text_only=False)), engine=ENGINE, indexer=S.stand_in, pack=_pack(site, on=False))
    without = B.render(parse(_raw(site, entities=False)), engine=ENGINE, indexer=S.stand_in, pack=_pack(site, on=False))
    assert with_block == without
    assert not [p for p in with_block if p.startswith(("entity/", "entities/"))]


@pytest.mark.parametrize("site", SITES)
def test_switch_off_keeps_the_golden_bytes(site):
    # The golden cases with an entities block added and the switch off. dd's committed
    # pack has it on (2026-10-20), so its golden case is built with that pack, switched off;
    # only the lock's pack hash can differ, so it is compared without it.
    from tests.roomkit import test_golden as G
    _m, kw = G.CASES[site]()
    raw = _raw(site, text_only=False)
    if site == "deflockdane":
        kw = {"mount": "/rr-staging/", "noindex": True}
    files = B.render(parse(raw), engine=ENGINE, indexer=S.stand_in, pack=_pack(site, on=False), **kw)
    got = b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))
    pack_line = re.compile(rb'\n "pack": "[0-9a-f]{64}",\n')
    assert pack_line.sub(b"\n", got) == pack_line.sub(b"\n", (GOLDEN / f"{site}.txt").read_bytes())


def test_only_dd_and_gg_ship_with_the_switch_on():
    # dd turned on 2026-10-20 (parity.entities 16/16 since 2026-10-15); GG the same day, once its
    # text-only records were in the room (the entity pages link them).
    assert E.enabled(K.for_site("deflockdane")) and E.enabled(K.for_site("glassgovernment"))
    for site in ("default", "hrtarchive"):
        assert not E.enabled(K.for_site(site)), site


def test_switch_on_without_a_block_builds_no_entity_pages():
    files = B.render(parse(_raw("glassgovernment", entities=False)), engine=ENGINE, indexer=S.stand_in, pack=_pack("glassgovernment"))
    assert not [p for p in files if p.startswith(("entity/", "entities/"))]
    css = files[B.published(files, "assets/room.css")].decode()
    assert R.ENTITIES_CSS not in css


def test_switch_on_ships_the_pages_and_their_stylesheet():
    files = _render("glassgovernment")
    assert {"entities/index.html", "entity/vendor/flock/index.html", "entity/agency/test-agency/index.html",
            "entity/agency/obrien-sons/index.html"} <= set(files)
    assert R.ENTITIES_CSS in files[B.published(files, "assets/room.css")].decode()
    dd = _render("deflockdane")
    assert {"entity/vendor/flock/index.html", "entity/agency/test-agency/index.html"} <= set(dd)
    assert not [p for p in dd if p.startswith("entities/")]  # dd has no index page


# --- the index -------------------------------------------------------------------------

def test_index_groups_and_entities_in_the_exported_order():
    html = _main(_render("glassgovernment")["entities/index.html"])
    groups = re.findall(r'data-room-entity-group="([^"]+)"', html)
    assert groups == ["vendor", "agency"]
    assert re.findall(r'data-room-entity="([^"]+)"', html) == ["vendor/flock", "agency/test-agency", "agency/obrien-sons"]
    assert '<h2 id="room-etype-agency">Agencies <span class="room__section-n">2</span></h2>' in html
    assert "O&#x27;Brien &amp; Sons" in html  # escaped


def test_index_reorders_when_the_export_does():
    raw = _raw("glassgovernment")
    raw["entities"]["index"]["groups"].reverse()
    raw["entities"]["index"]["groups"][0]["entities"].reverse()
    html = _main(_render("glassgovernment", raw=raw)["entities/index.html"])
    assert re.findall(r'data-room-entity="([^"]+)"', html) == ["agency/obrien-sons", "agency/test-agency", "vendor/flock"]


# --- an entity page ----------------------------------------------------------------------

def test_documents_in_the_exported_groups_and_order():
    html = _main(_render("glassgovernment")["entity/vendor/flock/index.html"])
    assert re.findall(r'data-room-doc="([^"]+)"', html) == ["big-report", "cfr-text-only", "camera-contract"]
    # Under a documents heading, the groups are h3: no gap in the outline.
    assert re.findall(r"<(h[1-6])", html) == ["h1", "h2", "h2", "h3", "h3"]
    assert '<h2 id="room-edocs-h" class="room__sr">Documents linked to this entity</h2>' in html
    # dd has no documents heading: its groups are h2.
    dd = _main(_render("deflockdane")["entity/vendor/flock/index.html"])
    assert re.findall(r"<(h[1-6])", dd) == ["h1", "h2", "h2"]
    assert re.findall(r'data-room-doc="([^"]+)"', dd) == ["big-report", "camera-contract"]


def test_links_follow_the_mount_and_records_outside_the_room_stay_live():
    html = _main(_render("glassgovernment")["entity/vendor/flock/index.html"])
    assert 'href="/library/big-report/"' in html
    assert 'href="/library/cfr-text-only/"' in html  # a text-only record, which the room holds
    assert 'href="/library/entity/agency/test-agency/"' in html
    assert 'href="/library/entities/"' in html  # crumb to the index
    dd = _render("deflockdane", mount="/rr-staging/", noindex=True)
    page = dd["entity/vendor/flock/index.html"].decode()
    assert 'href="/rr-staging/camera-contract/"' in page and 'href="/rr-staging/">' in page
    assert '<link rel="canonical" href="https://example.test/reading-room/entity/vendor/flock/">' in page
    assert 'content="noindex, nofollow"' in page


def test_document_page_chips_point_into_the_room_only_with_the_switch_on():
    on = _render("deflockdane")["camera-contract/index.html"].decode()
    off = B.render(parse(_raw("deflockdane")), engine=ENGINE, indexer=S.stand_in, pack=_pack("deflockdane", on=False))
    off = off["camera-contract/index.html"].decode()
    assert 'href="/reading-room/entity/vendor/flock/"' in on
    assert 'href="https://example.test/reading-room/entity/vendor/flock/"' in off


def test_alongside_in_order_with_kind_and_count():
    html = _main(_render("glassgovernment")["entity/vendor/flock/index.html"])
    al = html[html.index("room__alongside"):html.index("room__edocs")]
    assert re.findall(r'data-room-entity="([^"]+)"', al) == ["agency/test-agency"]
    assert ('<span class="room__item-kind">Agency</span><span class="room__item-meta">1<span class="room__sr">'
            ' shared documents</span></span>') in al
    assert '<ul class="room__chips" aria-labelledby="room-alongside-h">' in al
    # No alongside in the export, none on the page.
    assert "room__alongside" not in _main(_render("glassgovernment")["entity/agency/obrien-sons/index.html"])
    assert "room__alongside" not in _main(_render("deflockdane")["entity/vendor/flock/index.html"])


@pytest.mark.parametrize("site, path, where, old, new", [
    ("glassgovernment", "entity/vendor/flock/index.html", ("pages", 0, "alongside", "heading"),
     "Appears alongside", "Seen beside"),
    ("glassgovernment", "entity/vendor/flock/index.html", ("pages", 0, "documents_heading"),
     "Documents linked to this entity", "Records naming this party"),
    ("glassgovernment", "entity/vendor/flock/index.html", ("pages", 0, "groups", 0, "heading"),
     "Second Agency", "Another collection"),
    ("glassgovernment", "entity/vendor/flock/index.html", ("pages", 0, "eyebrow"),
     "Entity · Vendor", "Entity: vendor"),
    ("glassgovernment", "entities/index.html", ("index", "groups", 0, "heading"), "Vendors", "Suppliers"),
    ("glassgovernment", "entities/index.html", ("index", "back", "label"), "← Reading Room", "Back"),
    ("deflockdane", "entity/vendor/flock/index.html", ("pages", 0, "lede"),
     "2 released records across 2 agencies.", "Two records, two agencies."),
    ("deflockdane", "entity/vendor/flock/index.html", ("pages", 0, "groups", 0, "heading"),
     "O'Brien & Sons", "Other records"),
])
def test_every_heading_and_label_is_the_exports(site, path, where, old, new):
    raw = _raw(site)
    node = raw["entities"]
    for k in where[:-1]:
        node = node[k]
    assert node[where[-1]] == old
    before = _render(site, raw=raw)[path].decode()
    node[where[-1]] = new
    after = _render(site, raw=raw)[path].decode()
    esc = lambda s: s.replace("&", "&amp;").replace("'", "&#x27;")
    assert esc(old) in before and esc(old) not in after and esc(new) in after


def test_the_claim_headings_on_a_record_page_are_the_exports():
    raw = _raw("glassgovernment")
    raw["documents"][0]["display"]["groups"][0]["heading"] = "Named in this record"
    page = _render("glassgovernment", raw=raw)["camera-contract/index.html"].decode()
    assert "Named in this record" in page and "Named in this document" not in page


def test_no_template_or_view_composes_entity_words():
    # The words live in the export (here the fixtures), not in the room's code.
    words = ("Appears alongside", "Documents linked", "Vendors", "Agencies", "shared documents",
             "Reading Room", "released record", "Entity ·")
    for f in ("entities.html", "entity.html", "partials/entity-head.html"):
        t = re.sub(r"\{#.*?#\}", "", (R.TEMPLATES / "room" / f).read_text(), flags=re.DOTALL)
        assert not [w for w in words if w in t], f
    for mod in ("view.py", "entities.py", "build.py"):
        src = (R.TEMPLATES.parent / mod).read_text()
        assert not [w for w in words if w != "Reading Room" and f'"{w}' in src], mod  # (doc pages' own default predates this)


# --- JSON-LD and the head ----------------------------------------------------------------

def test_jsonld_is_the_exported_object_and_dd_has_none():
    page = _render("glassgovernment")["entity/vendor/flock/index.html"].decode()
    blob = re.search(r'<script type="application/ld\+json">(.*?)</script>', page).group(1)
    assert json.loads(blob) == _block("glassgovernment")["pages"][0]["jsonld"]
    assert json.loads(blob)["@type"] == "Organization"
    agency = _render("glassgovernment")["entity/agency/test-agency/index.html"].decode()
    assert json.loads(re.search(r'ld\+json">(.*?)</script>', agency).group(1))["@type"] == "GovernmentOrganization"
    dd = _render("deflockdane")["entity/vendor/flock/index.html"].decode()
    assert "application/ld+json" not in dd
    assert "<title>Flock Safety — Reading Room — Deflock Dane</title>" in dd
    assert '<meta name="description" content="Public records citing Flock Safety in the Deflock Dane reading room.">' in dd


def test_jsonld_cannot_close_its_script():
    raw = _raw("glassgovernment")
    raw["entities"]["pages"][0]["jsonld"]["name"] = "</script><b>x"
    page = _render("glassgovernment", raw=raw)["entity/vendor/flock/index.html"].decode()
    assert "</script><b>" not in page


# --- refusals ------------------------------------------------------------------------------

def _refusals(mutate) -> list[str]:
    raw = _raw("glassgovernment")
    mutate(raw["entities"])
    return [why for rid, why in parse(raw).refusals if rid == "entities"]


@pytest.mark.parametrize("mutate, says", [
    (lambda e: e["pages"][0].update(url="https://example.test/elsewhere/entity/vendor/flock/"), "is not under"),
    (lambda e: e["pages"][0].update(url="https://example.test/library/entity/vendor/other/"), "does not end in"),
    (lambda e: e["pages"][0].update(url="https://example.test/library/camera-contract/vendor/flock/"), "a record's"),
    (lambda e: e["pages"][0].update(url="https://example.test/library/assets/vendor/flock/"), "a record's"),
    (lambda e: e["pages"][0].update(type="Vendor"), "no slug type"),
    (lambda e: e["pages"].append(copy.deepcopy(e["pages"][0])), "listed twice"),
    (lambda e: e["pages"].pop(2), "which has no page"),
    (lambda e: e["pages"][0]["alongside"]["items"][0].update(slug="nobody"), "which has no page"),
    (lambda e: e["pages"][0].update(title=""), "title is missing"),
    (lambda e: e["pages"][0]["groups"][0]["documents"][0].update(url="javascript:alert(1)"), "is not {slug, title, url}"),
    (lambda e: e["pages"][0].update(jsonld="x"), "jsonld is not an object"),
    (lambda e: e["pages"][0]["stats"].append({"figure": 3}), "stats is not"),
    (lambda e: e.update(extra=1), "is not {index?"),
])
def test_a_bad_block_is_refused_with_the_reason(mutate, says):
    got = _refusals(mutate)
    assert any(says in why for why in got), got


def test_a_refused_block_stops_the_build():
    raw = _raw("glassgovernment")
    raw["entities"]["pages"][0]["url"] = "https://other.example/x/"
    m = parse(raw)
    assert m.refusals and m.entities is None
    with pytest.raises(ValueError):
        B.render(m, engine=ENGINE, indexer=S.stand_in, pack=_pack("glassgovernment"))


# --- the same template for both sites ----------------------------------------------------

def test_two_sites_with_the_same_knobs_draw_the_same_entity_pages():
    # GG's block served at dd's path: with dd's layout, labels, features and chrome the
    # pages are byte-identical whatever the pack's identity and tokens (test_generic's rule).
    raw = _raw("deflockdane")
    gg, dd = _pack("glassgovernment"), _pack("deflockdane")
    for knob in ("layout", "labels", "features", "chrome"):
        gg[knob] = copy.deepcopy(dd[knob])
    raw["site"].pop("template")
    css = re.compile(rb"assets/room\.[0-9a-f]{12}\.css")
    a = B.render(parse(raw), engine=ENGINE, indexer=S.stand_in, pack=gg)
    b = B.render(parse(raw), engine=ENGINE, indexer=S.stand_in, pack=dd)
    for p in ("entity/vendor/flock/index.html", "entity/agency/test-agency/index.html"):
        assert css.sub(b"", a[p]) == css.sub(b"", b[p])


def test_entities_css_is_scoped_and_paints_tokens_only():
    rules = [r for r in R.ENTITIES_CSS.split("}") if "{" in r]
    for r in rules:
        sel, body = r.split("{", 1)
        sel = re.sub(r"/\*.*?\*/", "", sel, flags=re.DOTALL).strip()
        assert all(s.strip().startswith("#room-content ") for s in sel.split(",")), sel
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb|oklch", body), body


# --- parity.entities -----------------------------------------------------------------------

def _built(tmp_path, site="glassgovernment") -> Path:
    out = tmp_path / site
    B.write(_render(site), out)
    return out


def _live_for(room: dict, site: str) -> dict:
    live = {"site": site, "fetched": "2026-10-15T00:00:00Z", "source": "test", "entities": list(room["entities"]),
            "pages": {k: dict(v) if site == "glassgovernment" else {"documents": v["documents"]}
                      for k, v in room["pages"].items()}}
    if room.get("index") is not None:
        live["index"] = copy.deepcopy(room["index"])
    return live


def test_parity_reads_the_room_it_built(tmp_path):
    room = EP.room_entities(_built(tmp_path))
    assert room["entities"] == ["agency/obrien-sons", "agency/test-agency", "vendor/flock"]
    assert room["pages"]["vendor/flock"] == {"documents": ["big-report", "cfr-text-only", "camera-contract"],
                                            "alongside": ["agency/test-agency"]}
    assert room["index"][0] == {"type": "vendor", "heading": "Vendors", "entities": ["vendor/flock"]}


@pytest.mark.parametrize("site", SITES)
def test_parity_agrees_when_live_matches(tmp_path, site):
    room_dir = _built(tmp_path, site)
    live = _live_for(EP.room_entities(room_dir), site)
    (tmp_path / "live.json").write_text(json.dumps(live))
    rep = EP.run(tmp_path / "live.json", room_dir, ("deflockdane", "glassgovernment"))
    assert rep["ok"], EP.text(rep)
    assert cli.main(["parity", "--entities", str(tmp_path / "live.json"), "--out", str(room_dir)]) == 0


@pytest.mark.parametrize("break_it, says", [
    (lambda L: L["pages"]["vendor/flock"]["documents"].reverse(), "same set, different order"),
    (lambda L: L["pages"]["vendor/flock"]["documents"].append("another-record"), "missing ['another-record']"),
    (lambda L: L["pages"]["vendor/flock"]["alongside"].append("agency/obrien-sons"), "alongside: missing"),
    (lambda L: L["entities"].append("org/aclu"), "missing from the room: org/aclu"),
    (lambda L: L["index"][1]["entities"].reverse(), "order only"),
    (lambda L: L["index"][0].update(heading="Vendor list"), "heading 'Vendor list' live"),
    (lambda L: L["pages"].pop("agency/obrien-sons"), "unchecked"),
    (lambda L: L.update(unfetched={"library/entity/org/aclu/": 404}), "did not answer 200"),
])
def test_parity_names_each_kind_of_difference(tmp_path, break_it, says):
    room_dir = _built(tmp_path)
    live = _live_for(EP.room_entities(room_dir), "glassgovernment")
    break_it(live)
    (tmp_path / "live.json").write_text(json.dumps(live))
    rep = EP.run(tmp_path / "live.json", room_dir, ("deflockdane", "glassgovernment"))
    assert not rep["ok"] and says in EP.text(rep), EP.text(rep)
    assert cli.main(["parity", "--entities", str(tmp_path / "live.json"), "--out", str(room_dir)]) == 1


def test_parity_refuses_a_malformed_live_file_and_a_room_without_entities(tmp_path):
    (tmp_path / "live.json").write_text(json.dumps({"site": "nowhere", "pages": []}))
    with pytest.raises(EP.EntityParityError) as e:
        EP.load_live(tmp_path / "live.json", ("deflockdane", "glassgovernment"))
    assert any("unknown site" in p for p in e.value.problems) and any("missing 'fetched'" in p for p in e.value.problems)
    plain = tmp_path / "plain"
    B.write(B.render(parse(_raw("glassgovernment")), engine=ENGINE, indexer=S.stand_in, pack=_pack("glassgovernment", on=False)), plain)
    good = _live_for(EP.room_entities(_built(tmp_path)), "glassgovernment")
    (tmp_path / "good.json").write_text(json.dumps(good))
    assert cli.main(["parity", "--entities", str(tmp_path / "good.json"), "--out", str(plain)]) == 2


# Live markup as each WordPress room writes it (trimmed from glassgovernment.org on
# 2026-10-15 and from deflock-reading-room's templates/entity-reading-room.php).
GG_INDEX = """<div class="ggrr-rr"><h1>Entities</h1>
<h2 class="ggrr-entities-group__title">Vendors <span class="ggrr-entities-group__n">1</span></h2>
<div class="ggrr-topics-grid"><a class="ggrr-topic-card" href="https://glassgovernment.org/library/entity/vendor/flock/">
<span class="ggrr-topic-card__label">Flock Safety</span><span class="ggrr-topic-card__count">3</span></a></div>
<h2 class="ggrr-entities-group__title">Agencies <span class="ggrr-entities-group__n">2</span></h2>
<div class="ggrr-topics-grid"><a class="ggrr-topic-card" href="https://glassgovernment.org/library/entity/agency/test-agency/">x</a>
<a class="ggrr-topic-card" href="https://glassgovernment.org/library/entity/agency/obrien-sons/">y</a></div></div>"""
GG_PAGE = """<section class="ggrr-entity__also"><h2>Appears alongside</h2><ul class="ggrr-entity__also-list">
<li><a href="https://glassgovernment.org/library/entity/agency/test-agency/"><span>Test Agency</span></a></li></ul></section>
<section class="ggrr-rr-browser"><h3 class="ggrr-cat__title">Second Agency</h3><ul class="ggrr-rr-results">
<li class="ggrr-rr-row"><a class="ggrr-rr-row__link" href="https://glassgovernment.org/library/big-report/">Big Report<span class="ggrr-prov-badge"><span class="visually-hidden">Provenance: </span>Third-party report</span></a></li>
<li class="ggrr-rr-row"><a class="ggrr-rr-row__link" href="https://glassgovernment.org/library/cfr-text-only/">A</a></li></ul>
<h3 class="ggrr-cat__title">Test Agency</h3><ul class="ggrr-rr-results"><li class="ggrr-rr-row">
<a class="ggrr-rr-row__link" href="https://glassgovernment.org/library/camera-contract/">C</a></li></ul></section>
<footer><a href="https://glassgovernment.org/library/elsewhere/">not a row</a></footer>"""
DD_PAGE = """<main id="deflock-reading-room-content"><nav><a href="https://deflockdane.org/reading-room/">&larr; Back</a></nav>
<section class="deflock-reading-room__category-section"><h2>O'Brien &amp; Sons</h2><ul class="deflock-reading-room__entity-list">
<li class="deflock-reading-room__entity-row"><a href="https://deflockdane.org/reading-room/big-report/"><span>Big Report</span></a></li></ul></section>
<section class="deflock-reading-room__category-section"><h2>Test Agency</h2><ul class="deflock-reading-room__entity-list">
<li class="deflock-reading-room__entity-row"><a href="https://deflockdane.org/reading-room/camera-contract/">C</a></li></ul></section></main>"""
DD_SITEMAP = """<urlset><url><loc>https://deflockdane.org/reading-room/entity/vendor/flock/</loc></url>
<url><loc>https://deflockdane.org/reading-room/entity/agency/test-agency/</loc></url></urlset>"""


def _tsv(tmp_path, rows: dict[str, tuple[int, str]]) -> Path:
    lines = ["# fetched 2026-10-15T00:00:00Z GET https://example/<path>"]
    lines += [f"{p}\t{c}\t{base64.b64encode(h.encode()).decode()}" for p, (c, h) in rows.items()]
    (tmp_path / "pages.tsv").write_text("\n".join(lines) + "\n")
    return tmp_path / "pages.tsv"


def test_live_pages_become_the_live_file_gg(tmp_path):
    head, pages = EP.read_pages_tsv(_tsv(tmp_path, {
        "library/entities/": (200, GG_INDEX), "library/entity/vendor/flock/": (200, GG_PAGE),
        "library/entity/org/gone/": (404, "")}))
    live = EP.live_from_pages("glassgovernment", head, pages)
    assert live["index"] == [{"type": "vendor", "heading": "Vendors", "entities": ["vendor/flock"]},
                             {"type": "agency", "heading": "Agencies",
                              "entities": ["agency/test-agency", "agency/obrien-sons"]}]
    assert live["entities"] == ["vendor/flock", "agency/test-agency", "agency/obrien-sons"]
    assert live["pages"]["vendor/flock"] == {"documents": ["big-report", "cfr-text-only", "camera-contract"],
                                            "alongside": ["agency/test-agency"]}
    assert live["unfetched"] == {"library/entity/org/gone/": 404}
    assert live["fetched"] == "2026-10-15T00:00:00Z"
    EP.parse_live(live, ("deflockdane", "glassgovernment"))


def test_live_pages_become_the_live_file_dd_and_agree_with_the_room(tmp_path, capsys):
    tsv = _tsv(tmp_path, {"deflock_rr_entity-sitemap.xml": (200, DD_SITEMAP),
                          "reading-room/entity/vendor/flock/": (200, DD_PAGE),
                          "reading-room/entity/agency/test-agency/": (200, DD_PAGE.split("<section")[0] + "<section"
                                                                      + DD_PAGE.split("<section")[2])})
    assert cli.main(["parity", "--entities-from", str(tsv), "--site", "deflockdane"]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["entities"] == ["vendor/flock", "agency/test-agency"] and "index" not in live
    assert live["pages"]["vendor/flock"] == {"documents": ["big-report", "camera-contract"]}
    (tmp_path / "live.json").write_text(json.dumps(live))
    rep = EP.run(tmp_path / "live.json", _built(tmp_path, "deflockdane"), ("deflockdane", "glassgovernment"))
    assert rep["ok"], EP.text(rep)


def test_a_pages_file_without_its_fetch_line_is_refused(tmp_path):
    (tmp_path / "p.tsv").write_text("library/entities/\t200\t\n")
    with pytest.raises(EP.EntityParityError):
        EP.read_pages_tsv(tmp_path / "p.tsv")


# --- in a browser (skipped where Playwright's Chromium is not installed) -------------------

@pytest.fixture(scope="module")
def entity_rooms(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path_factory.mktemp("entity-rooms")
    B.write(_render("glassgovernment"), root / "library")
    B.write(_render("deflockdane"), root / "reading-room")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            srv.shutdown()
            pytest.skip(f"Playwright Chromium not installed: {e}")
        yield b, base
        b.close()
    srv.shutdown()


PAGES = ("/library/entities/", "/library/entity/vendor/flock/", "/library/entity/agency/obrien-sons/",
         "/reading-room/entity/vendor/flock/")
AXE = """() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}})
  .then(r => r.violations.map(v => v.id + ': ' + v.nodes.map(n => n.target.join(' ')).join(', ')))"""


@pytest.mark.parametrize("width", (375, 1280))
@pytest.mark.parametrize("path", PAGES)
def test_in_a_browser_entity_pages_pass_axe_and_fit(entity_rooms, path, width):
    from tests.reading_room_reader.conftest import axe_source
    b, base = entity_rooms
    for scheme in ("light", "dark"):
        page = b.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme).new_page()
        page.goto(base + path)
        if scheme == "dark" and page.locator("[data-room-toggle]").count():
            page.locator("[data-room-toggle]").click()
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), (path, width)
        page.evaluate(axe_source())
        assert page.evaluate(AXE) == [], (path, width, scheme)
        page.close()


@pytest.mark.parametrize("path", PAGES)
def test_in_a_browser_without_javascript_the_page_reads_whole(entity_rooms, path):
    b, base = entity_rooms
    page = b.new_context(viewport={"width": 375, "height": 812}, java_script_enabled=False).new_page()
    page.goto(base + path)
    assert page.locator("h1").count() == 1
    levels = page.evaluate("() => [...document.querySelectorAll('main h1,main h2,main h3,main h4')]"
                           ".map(h => +h.tagName[1])")
    assert levels[0] == 1 and all(b - a <= 1 for a, b in itertools.pairwise(levels)), levels
    for role in ("banner", "main", "contentinfo"):
        assert page.get_by_role(role).count() == 1, role
    # Every list on the page is named by its heading.
    for ul in page.locator("main ul.room__chips, main ul.room__links").all():
        assert ul.get_attribute("aria-labelledby"), path
        assert ul.is_visible()
    first = page.locator("main [data-room-doc], main [data-room-entity]").first
    assert first.is_visible()
    page.close()


def test_an_entity_page_linking_a_record_the_room_does_not_hold_is_refused():
    raw = _raw("glassgovernment", text_only=False)
    raw["entities"]["pages"][0]["groups"][0]["documents"].append(
        {"slug": "cfr-text-only", "title": "Gone", "url": "https://example.test/library/cfr-text-only/"})
    m = parse(raw)
    assert any("'cfr-text-only' is not a public record in this room" in why for _, why in m.refusals)


def test_a_link_to_another_site_or_a_non_canonical_spelling_of_a_room_record():
    raw = _raw("glassgovernment", text_only=False)
    docs = raw["entities"]["pages"][0]["groups"][0]["documents"]
    docs[:] = [dict(docs[0], url="https://elsewhere.test/library/not-ours/", slug="not-ours")]
    assert not [r for r in parse(raw).refusals if "public record in this room" in r[1]]
    docs[0] = dict(docs[0], slug="not-ours", url="https://EXAMPLE.test/library/./a/../not-ours/")
    assert any("public record in this room" in why for _, why in parse(raw).refusals)
