"""roomkit collections (pack features.collections): GG's collections page, collection
pages and the index's collections table, from the export's `collections` block
(roomkit/site_collections.py), and parity.collections (collection_parity.py).

The live side of the parity tests is markup written the way the plugin's templates
write it (index-ggrr-collections.php, archive-ggrr-collection.php,
index-ggrr-reading-room.php at gg-reading-room 03c8cd2), so the two readers are
shown to agree on the same content.
"""

from __future__ import annotations

import base64
import copy
import functools
import html
import itertools
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from roomkit import browse as BR
from roomkit import build as B
from roomkit import cli
from roomkit import collection_parity as CP
from roomkit import gate as G
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit import site_collections as CO
from roomkit.manifest import parse

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
ENGINE = GOLDEN / "engine"


def _block() -> dict:
    return json.loads((HERE / "fixtures" / "collections-glassgovernment.json").read_text(encoding="utf-8"))["collections"]


def _raw(block: dict | None = None, collections: bool = True) -> dict:
    m = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    m["site"]["template"] = "glassgovernment"
    m["site"]["room_path"] = "/library/"
    if collections:
        m["collections"] = block if block is not None else _block()
    return m


def _pack(on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site("glassgovernment"))
    p["features"] = {**p.get("features", {}), "collections": on}
    return p


def _render(on: bool = True, raw: dict | None = None, **kw) -> dict[str, bytes]:
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, indexer=S.stand_in, pack=_pack(on), **kw)


def _refusals(block: dict) -> list[str]:
    return [why for where, why in parse(_raw(block)).refusals if where == "collections"]


def _main(b: bytes) -> str:
    s = b.decode()
    return s[s.index("<main"):s.index("</main>")]


# --- the switch ------------------------------------------------------------------------

def test_switch_off_builds_exactly_the_room_without_collections():
    assert B.render(parse(_raw()), engine=ENGINE, indexer=S.stand_in, pack=_pack(False)) == \
        B.render(parse(_raw(collections=False)), engine=ENGINE, indexer=S.stand_in, pack=_pack(False))


def test_switch_off_keeps_the_golden_bytes():
    from tests.roomkit import test_golden as TG
    _, kw = TG.CASES["glassgovernment"]()
    files = B.render(parse(_raw()), engine=ENGINE, indexer=S.stand_in, pack=_pack(False), **kw)
    got = b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))
    pack_line = re.compile(rb'\n "pack": "[0-9a-f]{64}",\n')
    assert pack_line.sub(b"\n", got) == pack_line.sub(b"\n", (GOLDEN / "glassgovernment.txt").read_bytes())


def test_only_gg_turns_collections_on():
    # GG turned it on 2026-10-21, after parity.collections passed 40/40 against a fresh export.
    assert CO.enabled(K.for_site("glassgovernment"))
    for site in ("default", "deflockdane", "hrtarchive"):
        assert not CO.enabled(K.for_site(site)), site


def test_switch_on_without_a_block_ships_nothing():
    files = _render(raw=_raw(collections=False))
    assert not [p for p in files if p.startswith(("collection/", "collections/")) or "room-collections" in p]
    assert R.COLLECTIONS_CSS not in files[B.published(files, "assets/room.css")].decode()
    assert "room__cgrid" not in files["index.html"].decode()


def test_switch_on_ships_the_pages_script_and_stylesheet():
    files = _render()
    assert {"collections/index.html", "collection/cointelpro_new_left/index.html", "collection/agloso/index.html",
            "collection/empty-one/index.html"} <= set(files)
    assert R.COLLECTIONS_CSS in files[B.published(files, "assets/room.css")].decode()
    js = B.published(files, "assets/room-collections.js")
    assert files[js] == R.ROOM_COLLECTIONS_JS.encode()
    # The script goes where a control needs it: the collections page, a collection
    # page with a search, the index (its table sort); not the page without a search.
    for p in ("index.html", "collections/index.html", "collection/cointelpro_new_left/index.html"):
        assert f'src="/library/{js}"' in files[p].decode(), p
    assert "room-collections" not in files["collection/agloso/index.html"].decode()


def test_the_sitemap_and_the_gate_cover_every_collection_page(tmp_path):
    files = _render()
    urls = BR.urls(CO.gate(parse(_raw()), _pack()), [])
    assert {"https://example.test/library/collections/", "https://example.test/library/collection/agloso/",
            "https://example.test/library/collection/cointelpro_new_left/",
            "https://example.test/library/collection/empty-one/"} <= set(urls)
    sm = files["sitemap.xml"].decode()
    assert "https://example.test/library/collection/empty-one/" in sm
    B.write(files, tmp_path / "room")
    rep = G.run(tmp_path / "room")
    assert rep["ok"], rep


# --- what the pages say --------------------------------------------------------------

def test_collections_page_in_the_exported_order_with_every_word():
    main = _main(_render()["collections/index.html"])
    for words in ("Declassified collections", "The Reading Room", "Public records, served whole.", "Search archive",
                  "Search collections or keywords...", "Quick filters:", 'aria-label="Filter collections"',
                  "Federal Agencies", "Local Police", "Sort by:", "Year (Oldest First)", "Alphabetical",
                  "← Reading Room", "Federal File", "COINTELPRO", "1968–1971", "3 files", "0 files"):
        assert words in main, words
    order = [m for m in re.findall(r'data-room-collection="([^"]+)"', main)]
    assert order == ["cointelpro_new_left", "agloso", "empty-one"]
    assert main.index(">Historical") < main.index(">Other")
    assert 'id="g-cointelpro"' in main and 'data-room-tags="federal"' in main
    assert 'data-room-ccontrols hidden' in main  # shown by room-collections.js


def test_collection_page_heading_notice_and_records_in_order():
    main = _main(_render()["collection/cointelpro_new_left/index.html"])
    for words in ("Collection", "3 files, in order", "Federal File", "1968–1971", "Read with care",
                  "These files name private people.", "Report a problem.", "Search this collection",
                  "Filter 3 files by title", 'data-room-cstatus="{shown} of {total} files"', "9.1 MB", "512 KB",
                  '<span class="room__sr">Provenance: </span>Government record', ">Final<",
                  'aria-label="&quot;New Left&quot; files"'):
        assert words in main, words
    assert re.findall(r'data-room-doc="([^"]+)"', main) == ["big-report", "camera-contract", "memo-text"]
    assert re.findall(r'room__file-num">([^<]+)', main) == ["01", "02", "07"]
    assert 'href="/library/big-report/"' in main  # into the room


def test_a_collection_without_meta_shows_its_description_and_the_empty_one_says_so():
    files = _render()
    agloso = _main(files["collection/agloso/index.html"])
    assert "The Attorney General&#x27;s list." in agloso and "room__stamp" not in agloso and "data-room-csearch" not in agloso
    empty = _main(files["collection/empty-one/index.html"])
    assert "No files in this collection yet." in empty and "room__files" not in empty


def test_collection_page_head_title_canonical_and_jsonld():
    page = _render()["collection/agloso/index.html"].decode()
    assert "<title>AGLOSO – Glass Government</title>" in page
    assert '<link rel="canonical" href="https://example.test/library/collection/agloso/">' in page
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL).group(1))
    assert ld == _block()["pages"][1]["jsonld"]
    assert "<title>Reading Room – Glass Government</title>" in _render()["collections/index.html"].decode()


def test_index_table_eras_groups_rows_and_fallbacks():
    idx = _render()["index.html"].decode()
    grid = idx[idx.index("data-room-cgrid"):idx.index("</section>", idx.index("data-room-cgrid"))]
    assert re.findall(r'scope="rowgroup">([^<]+)', grid) == ["Historical", "COINTELPRO", "Other", "Other"]
    assert re.findall(r'<tr data-room-collection="([^"]+)"', grid) == ["cointelpro_new_left", "agloso", "empty-one"]
    for words in ("Period", "Description", "Grouped (default)", "Name (A–Z)", "FBI Records: The Vault",
                  "Sources: Federal Register, NARA", '<span class="room__sr">Source not recorded.</span>',
                  '<span class="room__sr">No description available.</span>', 'href="/library/collection/agloso/"'):
        assert words in grid, words
    assert 'data-room-cgrid-sortbox hidden' in grid
    # The table sits after the header, before the finder, as on the live index.
    assert idx.index("</header>") < idx.index("data-room-cgrid") < idx.index("data-room-finder")


def test_the_mount_moves_every_link_and_the_canonicals_stay_live():
    files = _render(mount="/rr-staging/", noindex=True)
    page = files["collection/cointelpro_new_left/index.html"].decode()
    assert 'href="/rr-staging/big-report/"' in page and 'href="/rr-staging/collections/"' in page
    assert 'rel="canonical" href="https://example.test/library/collection/cointelpro_new_left/"' in page
    assert 'href="/rr-staging/collection/agloso/"' in files["index.html"].decode()


# --- what the manifest refuses ---------------------------------------------------------

def _edit(fn) -> dict:
    b = _block()
    fn(b)
    return b


@pytest.mark.parametrize("fn, why", [
    (lambda b: b["pages"][0]["documents"].append(
        {"slug": "not-here", "title": "X", "url": "https://example.test/library/not-here/", "num": "09"}),
     "'not-here' is not a public record in this room"),
    (lambda b: b["pages"][0]["documents"].append(dict(b["pages"][0]["documents"][0])), "lists 'big-report' twice"),
    (lambda b: b["pages"][0].update(url="https://example.test/library/collection/other/"), "does not end in"),
    (lambda b: b["pages"][0].update(url="https://example.test/library/camera-contract/cointelpro_new_left/"),
     "a record's or the room's own path"),
    (lambda b: b["pages"].pop(), "'empty-one', which has no page"),
    (lambda b: b["index"]["categories"][0]["groups"][0]["collections"][0].update(tags=["environmental"]),
     "are not all filter values"),
    (lambda b: b["index"]["categories"][0]["groups"][0]["collections"][0].update(year=1968), "year is not a year"),
    (lambda b: b["index"]["sort"]["options"].append({"value": "random", "label": "Random"}), ".sort needs"),
    (lambda b: b["grid"]["columns"].pop(), "columns is not four headings"),
    (lambda b: b["grid"]["eras"][0]["groups"][0]["rows"].append(dict(b["grid"]["eras"][0]["groups"][0]["rows"][0])),
     "grid lists 'cointelpro_new_left' twice"),
    (lambda b: b["pages"][0].update(search={"label": "S", "placeholder": "P", "status": "{shown} files"}),
     "with {shown} and {total}"),
    (lambda b: b["pages"][0].update(notice={"heading": "H"}), "notice is not"),
    (lambda b: b.update(extra=1), "collections is not {index?, pages?, grid?, source?}"),
])
def test_a_bad_block_is_refused_and_named(fn, why):
    got = _refusals(_edit(fn))
    assert any(why in g for g in got), got


def test_a_refused_block_builds_nothing():
    m = parse(_raw(_edit(lambda b: b["grid"]["columns"].pop())))
    assert m.refusals and m.collections is None


def test_a_collection_page_cannot_also_be_an_entity_page():
    raw = _raw()
    raw["entities"] = json.loads((HERE / "fixtures" / "entities-glassgovernment.json").read_text(encoding="utf-8"))["entities"]
    raw["entities"]["pages"] = []
    raw["entities"]["index"]["url"] = "https://example.test/library/collections/"
    raw["entities"]["index"]["groups"] = []
    got = [why for where, why in parse(raw).refusals if where == "collections"]
    assert any("is also an entity page" in g for g in got), parse(raw).refusals


# --- parity.collections ----------------------------------------------------------------

def _e(s: str) -> str:
    return html.escape(s, quote=True)


def live_collections_page(b: dict) -> str:
    """index-ggrr-collections.php's markup for the block's index."""
    out = ['<nav class="ggrr-index__list" aria-label="Collections">']
    for c in b["index"]["categories"]:
        stamp = f'<span class="ggrr-cat__stamp">{_e(c["stamp"])}</span>' if c.get("stamp") else ""
        out.append(f'<section class="ggrr-cat ggrr-cat--{c["key"]}"><header class="ggrr-cat__head">'
                   f'<h2 class="ggrr-cat__title">{_e(c["heading"])}</h2> {stamp}</header>')
        for g in c["groups"]:
            out.append(f'<div class="ggrr-group" id="g-{g["id"]}"><h3 class="ggrr-group__title">{_e(g["heading"])}</h3>'
                       '<ul class="ggrr-ledger ggrr-folder-grid">')
            for it in g["collections"]:
                blurb = f'<p class="ggrr-folder-card__blurb">{_e(it["blurb"])}</p>' if it.get("blurb") else ""
                years = f'<span class="ggrr-ledger__years">{_e(it["years"])}</span>' if it.get("years") else ""
                out.append(f'<li class="ggrr-ledger__row ggrr-folder-card"><div class="ggrr-folder-card__tab">'
                           f'<span class="ggrr-folder-card__tab-code">{_e(it.get("code", ""))}</span></div>'
                           f'<h4 class="ggrr-ledger__title"><a class="ggrr-ledger__link" href="{_e(it["url"])}">'
                           f'{_e(it["title"])}</a></h4>{blurb}<div class="ggrr-folder-card__footer">{years} '
                           f'<span class="ggrr-ledger__count">{_e(it["count"])}</span></div></li>')
            out.append("</ul></div>")
        out.append("</section>")
    return "".join(out) + "</nav>"


def live_collection_page(p: dict) -> str:
    """archive-ggrr-collection.php's markup for one page."""
    head = [(f'<header class="ggrr-hub__head"><p class="ggrr-rr__eyebrow">{_e(p["eyebrow"])}</p>'
             f'<h1 class="ggrr-hub__title">{_e(p["title"])}</h1><p class="ggrr-hub__count">{_e(p["count"])}</p>')]
    if p.get("stamp"):
        head.append(f'<p class="ggrr-collection__period"><span class="ggrr-cat__stamp ggrr-cat--{p["stamp_kind"]}">'
                    f'{_e(p["stamp"])}</span> <span class="ggrr-ledger__years">{_e(p.get("years", ""))}</span></p>')
    if p.get("blurb"):
        head.append(f'<p class="ggrr-collection__blurb">{_e(p["blurb"])}</p>')
    elif p.get("description"):
        head.append(f'<p class="ggrr-index__intro">{_e(p["description"])}</p>')
    head.append("</header>")
    n = p.get("notice")
    if n:
        rep = f'<p class="ggrr-sensitivity__report">{_e(n["report"])}</p>' if n.get("report") else ""
        head.append(f'<aside class="ggrr-sensitivity"><h2 class="ggrr-sensitivity__head">{_e(n["heading"])}</h2>'
                    f'<p class="ggrr-sensitivity__body">{_e(n["body"])}</p>{rep}</aside>')
    files = []
    for d in p["documents"]:
        final = f'<span class="ggrr-fileitem__final">{_e(d["final"])}</span>' if d.get("final") else ""
        badge = (f'<span class="ggrr-prov-badge ggrr-prov-badge--{d["badge_kind"]}"><span class="visually-hidden">'
                 f'{_e(d["badge_sr"])}</span>{_e(d["badge"])}</span>') if d.get("badge") else ""
        size = f'<span class="ggrr-fileitem__size">{_e(d["size"])}</span>' if d.get("size") else ""
        files.append(f'<a class="ggrr-fileitem" href="{_e(d["url"])}"><span class="ggrr-fileitem__num">{d["num"]}</span>'
                     f'<span class="ggrr-fileitem__title">{_e(d["title"])}{final}{badge}</span>{size}</a>')
    body = (f'<nav class="ggrr-filelist" aria-label="{_e(p["list_label"])}">{"".join(files)}</nav>' if files
            else '<p class="ggrr-rr__empty">No files in this collection yet.</p>')
    ld = f'<script type="application/ld+json">{json.dumps(p["jsonld"])}</script>'
    return ld + "".join(head) + body


def live_index_page(gr: dict) -> str:
    """index-ggrr-reading-room.php section 1's markup for the block's grid."""
    rows = []
    for e in gr["eras"]:
        rows.append(f'<tr class="gg-card__era"><th colspan="4" scope="rowgroup">{_e(e["heading"])}</th></tr>')
        for g in e["groups"]:
            rows.append(f'<tr class="gg-card__group"><th colspan="4" scope="rowgroup">{_e(g["heading"])}</th></tr>')
            for r in g["rows"]:
                line = f'<span class="gg-card__coll-sources">{_e(r["sources_line"])}</span>' if r.get("sources_line") else ""
                src = _e(r["sources"]) if r.get("sources") else f'<span class="visually-hidden">{_e(r["sources_empty"])}</span>'
                blurb = _e(r["blurb"]) if r.get("blurb") else f'<span class="visually-hidden">{_e(r["blurb_empty"])}</span>'
                years = f'<span class="gg-card__year">{_e(r["years"])}</span>' if r.get("years") else ""
                rows.append(f'<tr class="gg-card__row"><td class="gg-card__col-period">{years}</td>'
                            f'<td class="gg-card__coll"><a href="{_e(r["url"])}">{_e(r["title"])}</a>{line}</td>'
                            f'<td class="gg-card__col-sources">{src}</td><td class="gg-card__col-blurb">{blurb}</td></tr>')
    return ('<table class="gg-card__grid"><thead><tr><th scope="col" class="gg-card__col-period">Period</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _tsv(tmp_path, b: dict, drop: str = "") -> Path:
    pages = {"library/": (200, live_index_page(b["grid"])), "library/collections/": (200, live_collections_page(b))}
    for p in b["pages"]:
        if p["slug"] != drop:
            pages[f"library/collection/{p['slug']}/"] = (200, live_collection_page(p))
    lines = ["# fetched 2026-10-20T00:00:00Z GET https://example.test/<path>"]
    lines += [f"{k}\t{c}\t{base64.b64encode(h.encode()).decode()}" for k, (c, h) in pages.items()]
    (tmp_path / "pages.tsv").write_text("\n".join(lines) + "\n")
    return tmp_path / "pages.tsv"


def _room(tmp_path) -> Path:
    B.write(_render(), tmp_path / "room")
    return tmp_path / "room"


def _live(tmp_path, capsys, b: dict | None = None, drop: str = "") -> Path:
    assert cli.main(["parity", "--collections-from", str(_tsv(tmp_path, b or _block(), drop)),
                     "--site", "glassgovernment"]) == 0
    (tmp_path / "live.json").write_text(capsys.readouterr().out)
    return tmp_path / "live.json"


def test_the_live_markup_and_the_room_agree(tmp_path, capsys):
    room = _room(tmp_path)
    live = _live(tmp_path, capsys)
    rep = CP.run(live, room)
    assert rep["ok"], CP.text_report(rep)
    assert rep["same"] == rep["total"] == 3 and rep["parts"] == {"index": "same", "grid": "same"}
    assert cli.main(["parity", "--collections", str(live), "--out", str(room)]) == 0
    assert "PASSES: collection pages 3/3 same" in capsys.readouterr().out


def test_the_live_reader_reads_every_field():
    p = CP.read_page(live_collection_page(_block()["pages"][0]), "live")
    assert p == {"title": '"New Left"', "count": "3 files, in order", "stamp": "Federal File", "years": "1968–1971",
                 "lede": "FBI counterintelligence against campus organizing.",
                 "notice": ["Read with care", "These files name private people.", "Report a problem."],
                 "documents": ["big-report", "camera-contract", "memo-text"], "nums": ["01", "02", "07"],
                 "sizes": ["9.1 MB", "512 KB", ""], "badges": ["Provenance: Government record", "Final", ""],
                 "jsonld": _block()["pages"][0]["jsonld"]}


@pytest.mark.parametrize("change, where", [
    (lambda b: b["pages"][0]["documents"].reverse(), "collection/cointelpro_new_left/: differs"),
    (lambda b: b["pages"][1].update(count="2 files, in order"), "collection/agloso/: differs"),
    (lambda b: b["index"]["categories"][0]["groups"][0]["collections"].reverse(), "index: differs"),
    (lambda b: b["grid"]["eras"][0]["groups"][0]["rows"][0].update(sources="NARA"), "grid: differs"),
])
def test_a_live_difference_fails_and_says_where(tmp_path, capsys, change, where):
    room = _room(tmp_path)
    b = _block()
    change(b)
    rep = CP.run(_live(tmp_path, capsys, b), room)
    assert not rep["ok"] and where in CP.text_report(rep), CP.text_report(rep)


def test_an_unfetched_live_page_is_not_a_pass(tmp_path, capsys):
    rep = CP.run(_live(tmp_path, capsys, drop="agloso"), _room(tmp_path))
    assert not rep["ok"]
    assert rep["pages"]["agloso"] == "unchecked (no live page)" and rep["unpaged"] == ["agloso"]


def test_a_pages_file_for_another_site_is_refused(tmp_path):
    with pytest.raises(CP.CollectionParityError):
        CP.live_from_pages("deflockdane", {"fetched": "x", "source": "y"}, {})


# --- in a browser (skipped where Playwright's Chromium is not installed) -------------------

@pytest.fixture(scope="module")
def coll_room(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path_factory.mktemp("coll-room")
    B.write(_render(), root / "library")
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


PAGES = ("/library/", "/library/collections/", "/library/collection/cointelpro_new_left/",
         "/library/collection/agloso/", "/library/collection/empty-one/")
AXE = """() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}})
  .then(r => r.violations.map(v => v.id + ': ' + v.nodes.map(n => n.target.join(' ')).join(', ')))"""


@pytest.mark.parametrize("width", (375, 1280))
@pytest.mark.parametrize("path", PAGES)
def test_in_a_browser_collection_pages_pass_axe_and_fit(coll_room, path, width):
    from tests.reading_room_reader.conftest import axe_source
    b, base = coll_room
    for scheme in ("light", "dark"):
        page = b.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme).new_page()
        errors = []
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        page.goto(base + path)
        if scheme == "dark" and page.locator("[data-room-toggle]").count():
            page.locator("[data-room-toggle]").click()
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), (path, width)
        page.evaluate(axe_source())
        assert page.evaluate(AXE) == [], (path, width, scheme)
        assert errors == [], errors
        page.close()


@pytest.mark.parametrize("path", PAGES[1:])
def test_in_a_browser_without_javascript_every_collection_reads_and_no_control_shows(coll_room, path):
    b, base = coll_room
    page = b.new_context(viewport={"width": 375, "height": 812}, java_script_enabled=False).new_page()
    page.goto(base + path)
    assert page.locator("h1").count() == 1
    levels = page.evaluate("() => [...document.querySelectorAll('main h1,main h2,main h3,main h4')].map(h => +h.tagName[1])")
    assert levels[0] == 1 and all(y - x <= 1 for x, y in itertools.pairwise(levels)), levels
    for sel in ("[data-room-ccontrols]", "[data-room-csearch]"):
        if page.locator(sel).count():
            assert not page.locator(sel).is_visible(), sel
    assert all(li.is_visible() for li in page.locator("main [data-room-collection], main [data-room-doc]").all())
    page.close()


def test_in_a_browser_the_collections_page_filters_searches_and_sorts(coll_room):
    b, base = coll_room
    page = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    page.goto(base + "/library/collections/")
    shown = lambda: page.evaluate("() => [...document.querySelectorAll('[data-room-collection]')]"
                                  ".filter(e => !e.closest('[hidden]')).map(e => e.dataset.roomCollection)")
    assert page.locator("[data-room-ccontrols]").is_visible()
    assert shown() == ["cointelpro_new_left", "agloso", "empty-one"]
    # A filter keeps its tagged cards and every untagged one; an emptied category hides.
    page.click("[data-room-cfilter=police]")
    assert page.get_attribute("[data-room-cfilter=police]", "aria-pressed") == "true"
    assert shown() == ["agloso", "empty-one"]
    page.click("[data-room-cfilter=federal]")
    assert shown() == ["cointelpro_new_left", "agloso"]
    assert not page.locator("[data-room-ccat=uncategorized]").is_visible()
    page.click("[data-room-cfilter=all]")
    page.fill("[data-room-cq]", "campus")
    assert shown() == ["cointelpro_new_left"]
    page.fill("[data-room-cq]", "")
    # Sorting is within a group; no year last.
    page.select_option("[data-room-csort]", "year-asc")
    assert shown() == ["agloso", "cointelpro_new_left", "empty-one"]
    page.select_option("[data-room-csort]", "alpha")
    assert shown() == ["cointelpro_new_left", "agloso", "empty-one"]  # '"' sorts before 'A'
    page.select_option("[data-room-csort]", "default")
    assert shown() == ["cointelpro_new_left", "agloso", "empty-one"]
    page.close()


def test_in_a_browser_a_collection_page_filters_by_title(coll_room):
    b, base = coll_room
    page = b.new_context().new_page()
    page.goto(base + "/library/collection/cointelpro_new_left/")
    page.fill("[data-room-cfq]", "memo")
    assert page.evaluate("() => [...document.querySelectorAll('.room__files li')].filter(l => !l.hidden).length") == 1
    assert page.text_content("[data-room-cstatus]") == "1 of 3 files"
    page.fill("[data-room-cfq]", "")
    assert page.text_content("[data-room-cstatus]") == ""
    page.close()


def test_in_a_browser_the_index_table_sorts_and_returns_to_grouped(coll_room):
    b, base = coll_room
    page = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    page.goto(base + "/library/")
    rows = lambda: page.evaluate("() => [...document.querySelectorAll('[data-room-cgrid] tbody tr')]"
                                 ".filter(r => !r.hidden).map(r => r.dataset.roomCollection || 'head')")
    assert rows() == ["head", "head", "cointelpro_new_left", "agloso", "head", "head", "empty-one"]
    page.select_option("[data-room-cgrid-sort]", "year-desc")
    assert rows() == ["cointelpro_new_left", "agloso", "empty-one"]
    page.select_option("[data-room-cgrid-sort]", "name")
    assert rows() == ["cointelpro_new_left", "agloso", "empty-one"]
    page.select_option("[data-room-cgrid-sort]", "default")
    assert rows() == ["head", "head", "cointelpro_new_left", "agloso", "head", "head", "empty-one"]
    page.close()


def test_on_a_narrow_screen_the_sources_move_under_the_title(coll_room):
    b, base = coll_room
    page = b.new_context(viewport={"width": 375, "height": 812}).new_page()
    page.goto(base + "/library/")
    assert not page.locator(".room__cgrid-src").first.is_visible()
    assert page.locator(".room__cgrid-srcline").first.is_visible()
    page.close()
