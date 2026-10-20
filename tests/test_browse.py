"""Facet pages, the sitemap and their parity checks (roomkit/browse.py,
browse_parity.py; matrix rows index-facet-pages and sitemaps)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from roomkit import browse as BR
from roomkit import browse_parity as BP
from roomkit import build as B
from roomkit import cli
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit.manifest import ManifestError, parse

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
ENGINE = GOLDEN / "engine"
ROOM = "https://example.test/reading-room/"

BROWSE = {"heading": "Browse records by", "facets": [
    {"name": "agency", "label": "Agency", "title": "Records from {value}"},
    {"name": "vendor", "label": "Vendor", "title": "Records naming {value}"},
    {"name": "year", "label": "Year", "title": "Records from {value}"}]}
MEMBERS = {
    "camera-contract": {"agency": ["Test Agency"], "vendor": ["Flock Safety", "Axon"], "year": ["2026"]},
    "site-photo": {"agency": ["Test Agency"], "year": ["2024"]},
    "big-report": {"agency": ["O'Brien & Sons"], "vendor": ["Flock Safety"], "year": ["2025"]},
}


def _raw(browse: bool = True) -> dict:
    m = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    m["site"]["template"] = "deflockdane"
    if browse:
        m["site"]["index"]["browse"] = copy.deepcopy(BROWSE)
        for d in m["documents"]:
            if d["slug"] in MEMBERS:
                d.setdefault("index", {})["browse"] = copy.deepcopy(MEMBERS[d["slug"]])
    return m


def _pack(facets: bool = True, sitemaps: bool = True) -> dict:
    p = copy.deepcopy(K.for_site("deflockdane"))
    p["features"] = {**p.get("features", {}), "facet-pages": facets, "sitemaps": sitemaps}
    return p


def _render(raw: dict | None = None, **kw) -> dict[str, bytes]:
    pk = kw.pop("pack", None) or _pack()
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, indexer=S.stand_in, pack=pk, **kw)


def _built(tmp_path: Path, **kw) -> Path:
    out = tmp_path / "room"
    B.write(_render(**kw), out)
    return out


# --- the switches --------------------------------------------------------------

def test_switches_off_build_exactly_the_room_without_a_browse_block():
    off = _pack(facets=False, sitemaps=False)
    assert _render(pack=off) == _render(_raw(browse=False), pack=off)


def test_facet_pages_on_without_a_browse_block_builds_none():
    files = _render(_raw(browse=False), pack=_pack(sitemaps=False))
    assert not [p for p in files if p.startswith(("agency/", "vendor/", "year/"))]
    assert b"data-room-browse" not in files["index.html"]
    assert R.BROWSE_CSS.encode() not in files[B.published(files, "assets/room.css")]


def test_one_page_per_value_at_its_path_with_its_records_in_manifest_order():
    files = _render()
    pages = sorted(p for p in files if p.startswith(("agency/", "vendor/", "year/")))
    assert pages == ["agency/obrien-sons/index.html", "agency/test-agency/index.html",
                     "vendor/axon/index.html", "vendor/flock-safety/index.html",
                     "year/2024/index.html", "year/2025/index.html", "year/2026/index.html"]
    html = files["vendor/flock-safety/index.html"].decode()
    assert 'data-room-facet-page="vendor/flock-safety"' in html
    assert html.index('href="/reading-room/camera-contract/"') < html.index('href="/reading-room/big-report/"')
    assert "<h1 class=\"room__title\">Records naming Flock Safety</h1>" in html
    assert '<link rel="canonical" href="https://example.test/reading-room/vendor/flock-safety/">' in html
    assert R.BROWSE_CSS.encode() in files[B.published(files, "assets/room.css")]


def test_the_index_links_every_facet_page_without_javascript():
    html = _render()["index.html"].decode()
    nav = html[html.index("data-room-browse"):html.index("</nav>", html.index("data-room-browse"))]
    assert "Browse records by" in nav
    for path in ("agency/test-agency/", "agency/obrien-sons/", "vendor/axon/", "vendor/flock-safety/", "year/2026/"):
        assert f'href="/reading-room/{path}"' in nav
    # Facets in the site's order, years newest first.
    assert nav.index('data-room-browse-facet="agency"') < nav.index('data-room-browse-facet="vendor"')
    assert nav.index("year/2026/") < nav.index("year/2024/")
    assert "hidden" not in nav


def test_links_follow_the_mount_and_canonicals_stay_live():
    files = _render(mount="/rr-staging/", noindex=True)
    html = files["year/2025/index.html"].decode()
    assert 'href="/rr-staging/big-report/"' in html
    assert 'href="https://example.test/reading-room/year/2025/"' in html
    assert 'name="robots" content="noindex' in html
    assert 'href="/rr-staging/year/2025/"' in files["index.html"].decode()


@pytest.mark.parametrize("mutate, says", [
    (lambda m: m["documents"][0]["index"]["browse"].update({"agency": ["!!!"]}), "has no slug"),
    (lambda m: m["documents"][1]["index"]["browse"].update({"agency": ["test agency"]}), "are both 'test-agency'"),
    (lambda m: m["documents"][0]["index"]["browse"].update({"color": ["red"]}), "does not"),
    (lambda m: m["site"]["index"]["browse"]["facets"].append(
        {"name": "camera-contract", "label": "X", "title": "{value}"}), "already a path"),
    (lambda m: m["site"]["index"]["browse"]["facets"].append(
        {"name": "assets", "label": "X", "title": "{value}"}), "already a path"),
])
def test_a_browse_block_that_cannot_be_built_is_refused(mutate, says):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValueError, match="browse refused") as exc:
        _render(raw)
    assert says in str(exc.value)


@pytest.mark.parametrize("bad", [
    {"heading": "x", "facets": []},
    {"heading": "x", "facets": [{"name": "Agency", "label": "A", "title": "{value}"}]},
    {"heading": "x", "facets": [{"name": "agency", "label": "A", "title": "no placeholder"}]},
    {"heading": "x", "facets": [{"name": "a", "label": "A", "title": "{value}"}] * 2},
    {"facets": [{"name": "a", "label": "A", "title": "{value}"}]},
])
def test_a_malformed_site_browse_block_is_a_manifest_error(bad):
    raw = _raw()
    raw["site"]["index"]["browse"] = bad
    with pytest.raises(ManifestError, match="browse"):
        parse(raw)


def test_a_record_browse_that_is_not_lists_of_strings_is_refused():
    raw = _raw()
    raw["documents"][0]["index"]["browse"] = {"agency": "Test Agency"}
    assert any("index.browse" in str(r) for r in parse(raw).refusals)


# --- sitemap ---------------------------------------------------------------------

def test_sitemap_lists_every_served_page_by_its_live_url():
    files = _render(mount="/rr-staging/")
    got = BP.locs(files[BR.SITEMAP])
    m = parse(_raw())
    assert got[0] == ROOM
    assert got[1:1 + len(m.documents)] == [f"{ROOM}{d.slug}/" for d in m.documents]
    assert f"{ROOM}vendor/axon/" in got and len(got) == len(set(got)) == 1 + len(m.documents) + 7
    assert BR.SITEMAP in json.loads(files[B.LOCK])["files"]


def test_sitemap_escapes_and_is_off_without_its_switch():
    assert BR.SITEMAP not in _render(pack=_pack(sitemaps=False))
    assert "&amp;" in BR.sitemap_xml(["https://example.test/a?b=1&c=2"])


# --- parity.facet_pages ------------------------------------------------------------

def _live_index(docs: list[dict]) -> str:
    cfg = {"pdfJsUrl": "x", "archiveSearch": {"enabled": True, "docs": docs}}
    return f"<script>\nvar deflockReadingRoomConfig = {json.dumps(cfg)};\n</script>"


LIVE_DOCS = [
    {"slug": "camera-contract", "agency": "Test Agency", "docType": "", "year": "2026", "vendors": ["Flock Safety", "Axon"]},
    {"slug": "site-photo", "agency": "Test Agency", "docType": "", "year": "2024", "vendors": []},
    {"slug": "big-report", "agency": "O'Brien & Sons", "docType": "", "year": "2025", "vendors": ["Flock Safety"]},
]


def _live(docs=LIVE_DOCS) -> dict:
    live = BP.live_from_index("deflockdane", _live_index(docs))
    live["facets"].pop("type")  # the fixture's records have no type
    return live


def test_live_file_from_the_dd_index_payload():
    live = BP.live_from_index("deflockdane", _live_index(LIVE_DOCS))
    assert live["facets"]["vendor"] == {"Axon": ["camera-contract"], "Flock Safety": ["big-report", "camera-contract"]}
    assert live["facets"]["type"] == {}
    with pytest.raises(BP.BrowseParityError):
        BP.live_from_index("deflockdane", "<html></html>")
    with pytest.raises(BP.BrowseParityError):
        BP.live_from_index("glassgovernment", _live_index(LIVE_DOCS))


def test_facet_parity_agrees_with_its_own_room(tmp_path):
    rep = BP.compare_facets(_live(), BP.room_facets(_built(tmp_path, mount="/rr-staging/")))
    assert rep["ok"], rep["differences"]
    assert rep["pages"] == 7


@pytest.mark.parametrize("change, kind", [
    (lambda d: d[0]["vendors"].remove("Axon"), "extra-value"),
    (lambda d: d[1].update({"agency": "O'Brien & Sons"}), "members"),
    (lambda d: d[1]["vendors"].append("Motorola"), "missing-value"),
])
def test_facet_parity_names_each_difference(tmp_path, change, kind):
    docs = copy.deepcopy(LIVE_DOCS)
    change(docs)
    rep = BP.compare_facets(_live(docs), BP.room_facets(_built(tmp_path)))
    assert not rep["ok"] and kind in {d["kind"] for d in rep["differences"]}


def test_facet_parity_names_a_missing_facet_and_an_unlinked_page(tmp_path):
    room = _built(tmp_path)
    live = _live()
    live["facets"]["type"] = {"contract": ["camera-contract"]}
    assert "missing-facet" in {d["kind"] for d in BP.compare_facets(live, BP.room_facets(room))["differences"]}
    idx = room / "index.html"
    idx.write_text(idx.read_text().replace('href="/reading-room/year/2024/"', 'href="#"'))
    kinds = {(d["kind"], d.get("value")) for d in BP.compare_facets(_live(), BP.room_facets(room))["differences"]}
    assert kinds == {("unlinked", "2024")}


# --- parity.sitemaps -----------------------------------------------------------------

def _urlset(urls: list[str]) -> bytes:
    return BR.sitemap_xml(urls).encode()


def test_sitemap_parity_ignores_the_rooms_own_pages_and_urls_outside_it(tmp_path):
    room = _built(tmp_path)
    m = parse(_raw())
    live = tmp_path / "docs.xml"
    live.write_bytes(_urlset([f"{ROOM}{d.slug}/" for d in m.documents] + ["https://example.test/about/"]))
    rep = BP.run_sitemaps([live], room)
    assert rep["ok"], rep
    assert rep["outside_room"] == 1 and rep["room_only"] == 1 + 7


def test_sitemap_parity_names_missing_and_extra(tmp_path):
    room = _built(tmp_path)
    m = parse(_raw())
    live = tmp_path / "docs.xml"
    live.write_bytes(_urlset([f"{ROOM}{d.slug}/" for d in m.documents[1:]] + [f"{ROOM}entity/vendor/axon/"]))
    rep = BP.run_sitemaps([live], room)
    assert rep["missing"] == [f"{ROOM}entity/vendor/axon/"]
    assert rep["extra"] == [f"{ROOM}{m.documents[0].slug}/"]
    assert not rep["ok"]


def test_sitemap_parity_refuses_an_index_a_doctype_and_a_room_without_one(tmp_path):
    with pytest.raises(BP.BrowseParityError, match="urlset"):
        BP.locs(b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>')
    with pytest.raises(BP.BrowseParityError, match="DOCTYPE"):
        BP.locs(b'<!DOCTYPE x [<!ENTITY a "b">]><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>')
    out = tmp_path / "room"
    B.write(_render(pack=_pack(sitemaps=False)), out)
    with pytest.raises(BP.BrowseParityError, match="no sitemap"):
        BP.run_sitemaps([], out)


def test_cli_runs_both_checks(tmp_path, capsys):
    room = _built(tmp_path)
    index = tmp_path / "live-index.html"
    index.write_text(_live_index(LIVE_DOCS))
    assert cli.main(["parity", "--facets-from", str(index), "--site", "deflockdane"]) == 0
    live = json.loads(capsys.readouterr().out)
    live["facets"].pop("type")
    lf = tmp_path / "live.json"
    lf.write_text(json.dumps(live))
    assert cli.main(["parity", "--facet-pages", str(lf), "--out", str(room)]) == 0
    assert "parity.facet_pages OK" in capsys.readouterr().out
    sm = tmp_path / "docs.xml"
    sm.write_bytes(_urlset([f"{ROOM}{d.slug}/" for d in parse(_raw()).documents]))
    assert cli.main(["parity", "--sitemaps", str(sm), "--out", str(room)]) == 0
    assert "parity.sitemaps OK" in capsys.readouterr().out
