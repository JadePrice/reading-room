"""Corpus search (pack features.corpus-search): the Pagefind index, the finder
that searches it, its suggestions, and parity.search (plan Task 10; matrix rows
index-fulltext-search, index-suggest).

Unit tests use search.stand_in, as the goldens do. Tests marked with the
`pagefind` fixture run the pinned binary and skip without it; the browser
tests also need Playwright Chromium.
"""

from __future__ import annotations

import copy
import functools
import json
import re
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit import search_parity as SP
from roomkit.manifest import ManifestError, parse
from tests import test_golden as G

WORD = "zephyrine"  # only in page text: never in a title, summary or card
ONLY = "quillwort"  # only in data-dump's search_text: a record with no pages


def _manifest(site: str = "deflockdane") -> dict:
    m = G._base()
    m["site"]["template"] = site
    docs = {d["slug"]: d for d in m["documents"]}
    docs["camera-contract"]["pages"] = [{"n": 1, "text": "Master agreement, page one.", "provenance": "ocr"},
                                        {"n": 2, "text": f"Retention {WORD} schedule <script>x</script>",
                                         "provenance": "ocr"}]
    docs["big-report"]["pages"] = [{"n": 1, "text": f"Appendix {WORD} tables", "provenance": "ocr"}]
    docs["data-dump"]["search_text"] = f"  Ledger of {ONLY} purchases <b>bold</b>  "
    return m


def _pack(site: str = "deflockdane", on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site(site))
    p.setdefault("features", {})[S.FEATURE] = on
    return p


def _render(site="deflockdane", on=True, indexer=S.stand_in, **kw) -> dict[str, bytes]:
    return B.render(parse(_manifest(site)), engine=G.ENGINE, pack=_pack(site, on), indexer=indexer, **kw)


@pytest.fixture(scope="module")
def pagefind():
    try:
        S.binary()
    except S.SearchError as exc:
        pytest.skip(str(exc))


# --- what is indexed ---------------------------------------------------------------


def test_records_carry_every_searchable_field_and_page_anchors_only_where_the_reader_opens_them():
    m = parse(_manifest())
    recs = {r["slug"]: r for r in S.records(m, "/rr/")}
    cc = recs["camera-contract"]
    assert cc["url"] == "/rr/camera-contract/"
    assert cc["citation"] and cc["title"] and cc["summary"] and cc["agency"] and cc["group"] == "Test Agency"
    assert cc["facets"] == {"year": "2026"}
    assert [p["anchor"] for p in cc["pages"]] == ["page-1", "page-2"]
    # memo-text is a txt record: the text reader has no #page-N, so no anchors.
    assert [p["anchor"] for p in recs["memo-text"]["pages"]] == [""]


def test_record_html_indexes_the_fields_filters_and_sort_and_escapes_text():
    m = parse(_manifest())
    html = S.pages(m, "/rr/")["camera-contract/index.html"]
    assert "data-pagefind-body" in html
    assert '<h2 id="page-2">Page 2</h2>' in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html and "<script>x" not in html
    assert '<span data-pagefind-filter="group">Test Agency</span>' in html
    assert '<span data-pagefind-filter="year">2026</span>' in html
    assert '<span data-pagefind-sort="date">2026-01-31</span>' in html
    assert '<div data-pagefind-ignore>' in html  # filters narrow; they add no words
    doc = next(d for d in m.documents if d.slug == "camera-contract")
    for field in (doc.title, doc.summary, doc.agency):
        assert f"<p>{field}</p>" in html or f"<h1>{field}</h1>" in html


def test_the_public_notes_the_record_page_shows_are_searchable():
    # dd's live search reads its notes column (FULLTEXT title, agency, summary,
    # notes, full_text): "ALPR" finds the Middleton record only through its notes.
    data = _manifest()
    data["documents"][0].setdefault("display", {})["notes"] = "Not the ALPR technology. 123-45-6789"
    html = S.pages(parse(data), "/rr/")[f"{data['documents'][0]['slug']}/index.html"]
    assert "<p>Not the ALPR technology. </p>" in html  # masked like every other field


def test_search_text_is_indexed_for_the_record_without_a_page_or_anchor():
    m = parse(_manifest())
    rec = next(r for r in S.records(m, "/rr/") if r["slug"] == "data-dump")
    assert rec["pages"] == [] and rec["text"] == f"Ledger of {ONLY} purchases <b>bold</b>"
    html = S.pages(m, "/rr/")["data-dump/index.html"]
    assert f"<p>Ledger of {ONLY} purchases &lt;b&gt;bold&lt;/b&gt;</p>" in html
    assert "<h2" not in html  # nothing for a hit to report but the record itself
    assert "search_text" not in S.pages(m, "/rr/")["camera-contract/index.html"]


def test_search_text_is_never_shown_or_shipped_outside_the_index():
    files = _render()
    assert "data-dump/pages.json" not in files
    for rel, body in files.items():
        if not rel.startswith("pagefind/"):
            assert ONLY.encode() not in body, rel
    html = files["data-dump/index.html"].decode()
    assert "data-pages-url" not in html


def test_social_security_numbers_never_reach_the_index():
    data = _manifest()
    docs = {d["slug"]: d for d in data["documents"]}
    docs["data-dump"]["search_text"] = f"{ONLY} SSAN: 123-45-6789 born 1939; file 105-3458"
    docs["camera-contract"]["pages"][0]["text"] = "Social Security No.:987-65-4321. Master agreement"
    m = parse(data)
    site = S.pages(m, "/rr/")
    assert "123-45-6789" not in site["data-dump/index.html"] and "SSAN:  born 1939; file 105-3458" in site["data-dump/index.html"]
    assert "987-65-4321" not in site["camera-contract/index.html"]
    # The reader's own page text is the site's, untouched; only the index is masked.
    files = B.render(m, engine=G.ENGINE, pack=_pack(), indexer=S.stand_in)
    pages_json = next(v for k, v in files.items() if k.startswith("camera-contract/pages."))
    assert b"987-65-4321" in pages_json


@pytest.mark.parametrize("value, why", [
    (["x"], "search_text is not a string"),
    ("text", "search_text is only for a record with no pages"),
])
def test_search_text_is_refused_when_malformed_or_beside_pages(value, why):
    data = _manifest()
    doc = next(d for d in data["documents"] if d["slug"] == "camera-contract")
    doc["search_text"] = value
    m = parse(data)
    assert ("camera-contract", why) in m.refusals


# --- the switch ----------------------------------------------------------------------


def test_off_by_default_nothing_ships_and_room_js_keeps_the_finder():
    files = _render(on=False)
    assert not [p for p in files if p.startswith("pagefind/") or "room-search" in p]
    index = files["index.html"].decode()
    assert "data-room-finder" in index and "data-room-search" not in index and 'role="combobox"' not in index
    assert R.SEARCH_CSS not in files[B.published(files, "assets/room.css")].decode()
    assert '"search"' not in files[B.LOCK].decode()


def test_on_ships_the_index_the_finder_script_and_its_styles():
    files = _render(mount="/rr/")
    index = files["index.html"].decode()
    assert 'data-room-search data-room-pagefind="/rr/pagefind/"' in index
    assert "data-room-finder" not in index
    js = B.published(files, "assets/room-search.js")
    assert re.fullmatch(r"assets/room-search\.[0-9a-f]{12}\.js", js) and f'src="/rr/{js}"' in index
    assert R.SEARCH_CSS in files[B.published(files, "assets/room.css")].decode()
    assert json.loads(files["pagefind/input.json"]) == S.pages(parse(_manifest()), "/rr/")
    assert json.loads(files[B.LOCK])["search"]["pagefind"] == "stand-in"
    # Only the index page loads it; record pages do not.
    assert "room-search" not in files["camera-contract/index.html"].decode()


def test_the_search_box_is_a_labelled_combobox_over_a_listbox():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_render()["index.html"].decode(), "html.parser")
    q = soup.find(id="room-q")
    assert q["role"] == "combobox" and q["aria-expanded"] == "false" and q["aria-autocomplete"] == "list"
    assert soup.find("label", attrs={"for": "room-q"}).get_text(strip=True)
    lb = soup.find(id=q["aria-controls"])
    assert lb["role"] == "listbox" and lb.get("aria-label") and lb.has_attr("hidden")
    assert soup.find(id=q["aria-describedby"]).get_text(strip=True)
    count = soup.find(attrs={"data-room-count": True})
    assert count["role"] == "status" and count["aria-live"] == "polite"


def test_an_indexer_writing_outside_pagefind_is_refused():
    with pytest.raises(S.SearchError, match="outside pagefind/"):
        _render(indexer=lambda pages: {"index.html": b"x"})


def test_without_the_pinned_pagefind_the_build_is_refused_with_the_install_command(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pagefind_bin", None)
    with pytest.raises(S.SearchError, match=r"pagefind\[bin\]==1\.5\.2"):
        _render(indexer=None)


def test_another_pagefind_version_is_refused(monkeypatch):
    class Done:
        stdout = "pagefind 1.4.0\n"
    monkeypatch.setattr(S, "_executable", lambda: Path("/bin/true"))
    monkeypatch.setattr(S.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(S.SearchError, match="Pagefind 1.4.0 found, roomkit pins 1.5.2"):
        S.binary()


def test_the_cli_refuses_a_search_build_it_cannot_index(tmp_path, monkeypatch, capsys):
    import sys
    monkeypatch.setitem(sys.modules, "pagefind_bin", None)
    man = tmp_path / "m.json"
    man.write_text(json.dumps(_manifest()))
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.json").write_text(json.dumps(_pack()))
    for f in K.for_site("deflockdane").get("fonts", []):
        (pack / f["src"]).parent.mkdir(parents=True, exist_ok=True)
        (pack / f["src"]).write_bytes((K.PACKS / "deflockdane" / f["src"]).read_bytes())
    rc = cli.main(["build", "--manifest", str(man), "--out", str(tmp_path / "out"), "--site-pack", str(pack)])
    assert rc == 2 and "pagefind" in capsys.readouterr().err.lower()
    assert not (tmp_path / "out").exists()


def test_search_css_paints_with_tokens_only():
    css = re.sub(r"/\*.*?\*/", "", R.SEARCH_CSS, flags=re.DOTALL)
    assert all(sel.startswith("#room-content") for sel in re.findall(r"(?:^|})\s*([^{}@]+)\{", css))
    colors = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgb\(|\boklch\(", css)
    assert colors == [], colors  # only rgba() shadows, like room.css's thumbnails


def test_the_schema_knows_the_switch_and_its_placeholder():
    p = _pack()
    p["labels"]["fulltext_placeholder"] = "Search every page"
    assert K.validate(p) == []
    p["features"][S.FEATURE] = "yes"
    assert any("corpus-search" in x for x in K.validate(p))


# --- the real index ----------------------------------------------------------------------


def test_pagefind_output_is_stable_where_it_can_be_and_ships_no_ui_bundles(pagefind):
    a, b = _render(indexer=None), _render(indexer=None)
    pa = {p for p in a if p.startswith("pagefind/")}
    pb = {p for p in b if p.startswith("pagefind/")}
    # Fragments and index shards are the same bytes; filters and meta carry random value order.
    stable = lambda fs: {p for p in fs if p.split("/")[1] in ("fragment", "index")}
    assert stable(pa) == stable(pb) and all(a[p] == b[p] for p in stable(pa))
    assert len({p.split("/")[1] for p in pa if "filter" in p}) == 1
    names = {p.split("/", 1)[1] for p in pa}
    assert {"pagefind.js", "pagefind-worker.js", "pagefind-entry.json", "wasm.en.pagefind"} <= names
    assert not names & set(S.UNUSED)
    assert json.loads(a["pagefind/pagefind-entry.json"])["version"] == S.PAGEFIND_VERSION
    lock_a, lock_b = json.loads(a[B.LOCK]), json.loads(b[B.LOCK])
    assert lock_a["search"] == lock_b["search"] and lock_a["search"]["pagefind"] == S.PAGEFIND_VERSION
    assert len(lock_a["search"]["input"]) == 64


def test_check_finds_a_search_build_current_though_pagefind_bytes_move(pagefind, tmp_path, capsys):
    man = tmp_path / "m.json"
    man.write_text(json.dumps(_manifest()))
    pack = tmp_path / "pack"
    shutil.copytree(K.PACKS / "deflockdane", pack)
    cfg = json.loads((pack / "pack.json").read_text())
    cfg.setdefault("features", {})[S.FEATURE] = True
    (pack / "pack.json").write_text(json.dumps(cfg))
    out = tmp_path / "room"
    args = ["--manifest", str(man), "--out", str(out), "--site-pack", str(pack)]
    assert cli.main(["build", *args]) == 0
    assert (out / "pagefind" / "pagefind.js").is_file()
    assert cli.main(["check", *args, "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["status", *args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stage"] == "current"
    (out / "pagefind" / "pagefind.js").write_text("tampered")
    assert cli.main(["check", *args, "--json"]) == 1
    capsys.readouterr()


# --- parity.search: the comparison --------------------------------------------------------


def test_a_hit_is_a_slug_or_any_url_of_the_record():
    assert SP.slug_of("camera-contract") == "camera-contract"
    assert SP.slug_of("https://glassgovernment.org/library/camera-contract/") == "camera-contract"
    assert SP.slug_of("/reading-room/camera-contract/#page-3") == "camera-contract"
    assert SP.slug_of("/reading-room/camera-contract/?rr_search=x") == "camera-contract"


def test_live_results_are_refused_when_malformed():
    with pytest.raises(SP.SearchParityError) as e:
        SP.parse_live({"site": "nowhere", "queries": {"x": "not a list", " ": []}, "extra": 1}, ("deflockdane",))
    probs = " | ".join(e.value.problems)
    for want in ("unknown key 'extra'", "missing 'fetched'", "missing 'source'", "unknown site 'nowhere'",
                 "'x': hits are not a list", "an empty query"):
        assert want in probs


def test_compare_counts_only_records_the_room_holds_and_names_each_miss_with_its_rank():
    live = {"a b": ["one", "two", "gone"], "c": ["three"]}
    room = {"a b": ["two", "x", "one"], "c": ["y", "z", "three"]}
    rep = SP.compare(live, room, {"one", "two", "three", "x", "y", "z"}, n=2)
    by = {r["query"]: r for r in rep["queries"]}
    assert by["a b"]["not_in_room"] == ["gone"] and by["a b"]["missing"] == ["one"]
    assert by["a b"]["missing_rank"] == {"one": 3}
    assert by["c"]["missing"] == ["three"] and rep["ok"] is False
    assert rep["recall"] == round(1 / 3, 4)
    assert SP.compare(live, room, {"one", "two", "three"}, n=3)["ok"] is True


QUERY_SETS = sorted((B.REPO_ROOT / "roomkit/search-queries").glob("*.json"))


@pytest.mark.parametrize("path", QUERY_SETS, ids=lambda p: p.name)
def test_every_committed_query_set_is_well_formed_and_dated(path):
    live = SP.load_live(path, ("deflockdane", "glassgovernment"))
    assert path.name.startswith(live["site"] + "-")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", live["fetched"])
    assert len(live["queries"]) >= 10 and all(live["queries"].values())


def test_the_gg_query_sets_are_all_there():
    assert {p.name for p in QUERY_SETS} >= {
        "glassgovernment-2026-10-14.json", "glassgovernment-2026-10-14-wide.json",
        "glassgovernment-2026-10-14-titles.json"}


# --- in a browser -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def room(pagefind, tmp_path_factory):
    """The golden manifest in dd's pack with corpus search on, at /reading-room/, and a Chromium."""
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path_factory.mktemp("search-room")
    B.write(_render(indexer=None, mount="/reading-room/"), root / "reading-room")
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
        yield b, base, root / "reading-room"
        b.close()
    srv.shutdown()


def _open(b, base, width=1280, **ctx):
    page = b.new_context(viewport={"width": width, "height": 900}, **ctx).new_page()
    requests = []
    page.on("request", lambda r: requests.append(r.url) if r.resource_type != "image" else None)
    page.goto(base + "/reading-room/")
    return page, requests


def _type(page, text):
    q = page.get_by_role("combobox", name="Search records")
    q.click()
    q.press_sequentially(text, delay=20)
    return q


def test_text_search_finds_words_only_in_page_text_and_links_to_the_page(room):
    b, base, _ = room
    page, requests = _open(b, base)
    _type(page, WORD)
    page.wait_for_selector(".room__result")
    titles = page.locator(".room__result-title a")
    assert sorted(titles.evaluate_all("els => els.map(a => a.getAttribute('href'))")) == [
        "/reading-room/big-report/", "/reading-room/camera-contract/"]
    links = page.locator(".room__result-pages a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    assert "/reading-room/camera-contract/#page-2" in links
    assert page.locator(".room__result mark").first.inner_text().lower() == WORD
    status = page.get_by_role("status")
    assert status.inner_text() == "2 of 5 records match"
    assert page.locator("[data-room-section]:visible").count() == 0
    assert "q=" + WORD in page.url
    # Everything came from the room itself: no other host, no search route.
    assert all(u.startswith(base) for u in requests), [u for u in requests if not u.startswith(base)]
    assert any("/reading-room/pagefind/pagefind.js" in u for u in requests)
    page.close()


def test_text_search_finds_words_only_in_search_text_and_links_to_the_record(room):
    b, base, _ = room
    page, _ = _open(b, base)
    _type(page, ONLY)
    page.wait_for_selector(".room__result")
    hrefs = page.locator(".room__result-title a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    assert hrefs == ["/reading-room/data-dump/"]
    assert page.locator(".room__result-pages a").count() == 0
    page.close()


def test_facet_filters_narrow_the_text_results(room):
    b, base, _ = room
    page, _ = _open(b, base)
    _type(page, WORD)
    page.wait_for_function("() => document.querySelectorAll('.room__result').length === 2")
    page.get_by_label("Year").select_option("2025")
    page.wait_for_function("() => document.querySelectorAll('.room__result').length === 1")
    assert page.locator(".room__result-title a").get_attribute("href") == "/reading-room/big-report/"
    assert page.get_by_role("status").inner_text() == "1 of 5 records match"
    page.close()


def test_a_shared_search_url_runs_on_load(room):
    b, base, _ = room
    page = b.new_page()
    page.goto(base + f"/reading-room/?q={WORD}&year=2026")
    page.wait_for_selector(".room__result")
    assert page.locator(".room__result").count() == 1
    assert page.locator("#room-q").input_value() == WORD
    page.close()


def test_keyboard_only_suggestions(room):
    b, base, _ = room
    page, _ = _open(b, base)
    q = _type(page, WORD[:6])
    lb = page.get_by_role("listbox", name="Suggestions")
    lb.get_by_text("Top matches").wait_for()
    assert q.get_attribute("aria-expanded") == "true"
    groups = lb.get_by_role("group")
    assert groups.first.get_attribute("aria-labelledby")
    assert page.locator(f"#{groups.first.get_attribute('aria-labelledby')}").text_content().strip() == "Top matches"
    q.press("ArrowDown")
    active = q.get_attribute("aria-activedescendant")
    assert active and page.locator(f"#{active}").get_attribute("aria-selected") == "true"
    first = page.locator(f"#{active}").inner_text()
    q.press("ArrowUp")  # wraps to the last
    assert q.get_attribute("aria-activedescendant") != active
    q.press("ArrowDown")  # and back to the first
    assert q.get_attribute("aria-activedescendant") == active
    q.press("Escape")
    assert lb.is_hidden() and q.get_attribute("aria-expanded") == "false"
    assert q.get_attribute("aria-activedescendant") is None
    q.press("ArrowDown")  # reopens on the first option
    lb.wait_for(state="visible")
    page.wait_for_function("() => document.getElementById('room-q').getAttribute('aria-activedescendant')")
    with page.expect_navigation():
        q.press("Enter")
    assert page.locator("h1").inner_text().startswith(first)
    page.close()


def test_a_group_suggestion_sets_the_filter(room):
    b, base, _ = room
    page, _ = _open(b, base)
    q = _type(page, "second")
    opt = page.locator("#room-suggest").get_by_role("option", name=re.compile(r"^Second Agency"))
    opt.wait_for()
    while page.locator(f"#{q.get_attribute('aria-activedescendant') or 'none'}").count() == 0 or \
            not page.locator(f"#{q.get_attribute('aria-activedescendant')}").inner_text().startswith("Second Agency"):
        q.press("ArrowDown")
    q.press("Enter")
    assert page.locator("#room-f-group").input_value() == "Second Agency"
    assert q.input_value() == ""
    page.wait_for_function("() => /1 of 5/.test(document.querySelector('[data-room-count]').textContent)")
    page.close()


def test_recent_searches_and_recent_documents_on_an_empty_box(room):
    b, base, _ = room
    page, _ = _open(b, base)
    q = _type(page, WORD)
    # Escape on a closed list is the search box's own: it clears the text. Wait for the
    # suggestions, so Escape closes them and the text stays to be submitted.
    page.get_by_role("listbox", name="Suggestions").wait_for(state="visible")
    q.press("Escape")
    q.press("Enter")  # submit: remembered
    q.fill("")
    q.press("ArrowDown")
    lb = page.get_by_role("listbox", name="Suggestions")
    lb.wait_for(state="visible")
    heads = [t.strip() for t in lb.locator(".room__suggest-h").all_text_contents()]
    assert heads == ["Recent searches", "Recent documents"]
    assert page.get_by_role("option", name=WORD).count() == 1
    # Newest record first (camera-contract, 2026-01-31).
    assert lb.get_by_role("group").nth(1).get_by_role("option").first.inner_text() == "Camera Contract"
    page.close()


def test_at_375px_nothing_overflows(room):
    b, base, _ = room
    page, _ = _open(b, base, width=375)
    _type(page, WORD[:6])
    page.get_by_role("listbox").wait_for(state="visible")
    page.wait_for_selector(".room__result")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    box = page.get_by_role("listbox").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    page.close()


def test_without_javascript_the_static_list_stands(room):
    b, base, _ = room
    page, _ = _open(b, base, java_script_enabled=False)
    assert page.locator("[data-room-search]").is_hidden()
    assert page.locator(".room__card").count() == 5
    page.close()


def test_parity_search_reads_the_rooms_own_ranking(room, tmp_path):
    _, _, built = room
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"site": "deflockdane", "fetched": "2026-10-14T00:00:00Z", "source": "test",
                                "queries": {WORD: ["https://example.test/reading-room/camera-contract/",
                                                   "big-report", "not-exported"]}}))
    rep = SP.run(live, built, n=5, sites=("deflockdane",))
    assert rep["ok"] and rep["recall"] == 1.0
    assert rep["queries"][0]["not_in_room"] == ["not-exported"]
    assert cli.main(["parity", "--search", str(live), "--out", str(built), "--top", "5", "--json"]) == 0


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



# --- the site's own suggestion panel (manifest site.index.suggest) ------------------------------

def _suggest() -> dict:
    return {"labels": {"top": "Top matches", "recent_docs": "Recent documents", "recent_searches": "Recent searches"},
            "top": 6, "recent_docs": ["memo-text", "camera-contract"],
            "groups": [{"label": "Try searching", "items": [{"label": "Retention", "query": WORD}], "empty": 6, "typing": 0},
                       {"label": "Agencies", "items": [{"label": "Test Agency", "query": "Test Agency", "count": 1},
                                                       {"label": "</script><!-- x", "query": "x"}],
                        "empty": 1, "typing": 4}],
            # What dd's scoreDoc reads. ZEBRA is in no indexed text: only the scorer can find it.
            "rank": [_rank("camera-contract", "Camera Contract", agency="Test Agency", summary=f"Memo on {ZEBRA}",
                           date="2026-01-31", year="2026", doc_type="contract"),
                     _rank("memo-text", "Memo", date="2024-03-01", year="2024")]}


ZEBRA = "zebracrossing"


def _rank(slug, title, **kw) -> dict:
    return {"slug": slug, "title": title, "agency": "", "summary": "", "date": "", "year": "", "doc_type": "",
            "aliases": [], "vendors": []} | kw


def _with_suggest(sg: object = None) -> dict:
    m = _manifest()
    m["site"].setdefault("index", {})["suggest"] = _suggest() if sg is None else sg
    return m


@pytest.mark.parametrize("mutate, why", [
    (lambda s: s.pop("top"), "is not {labels, top, recent_docs, groups, rank?}"),
    (lambda s: s.update(rank={}), "rank is not a list"),
    (lambda s: s["rank"][0].pop("vendors"), "a rank row is not"),
    (lambda s: s["rank"][0].update(aliases="uw"), "a rank row is not"),
    (lambda s: s["rank"].append(dict(s["rank"][0])), "rank names a record twice"),
    (lambda s: s["labels"].pop("top"), "labels is not"),
    (lambda s: s.update(top=0), "top is not 1 to 50"),
    (lambda s: s.update(recent_docs=["Not A Slug"]), "recent_docs is not a list of slugs"),
    (lambda s: s["groups"][0].update(empty=-1), "a group is not"),
    (lambda s: s["groups"][1]["items"][0].update(count=0), "an item is not"),
    (lambda s: s["groups"][1]["items"][0].update(url="https://x"), "an item is not"),
])
def test_a_site_panel_the_room_cannot_draw_is_refused(mutate, why):
    sg = _suggest()
    mutate(sg)
    with pytest.raises(ManifestError, match=re.escape(why)):
        parse(_with_suggest(sg))


def test_the_panel_names_only_documents_the_room_holds():
    sg = _suggest()
    sg["recent_docs"].append("not-here")
    sg["rank"].append(_rank("gone", "Gone"))
    assert parse(_with_suggest(sg)).refusals == [
        ("site.index.suggest", "recent_docs names 'not-here', which is not a document"),
        ("site.index.suggest", "rank names 'gone', which is not a document")]


def test_the_panel_ships_as_inert_json_beside_the_finder_only_with_search_on():
    files = B.render(parse(_with_suggest()), engine=G.ENGINE, pack=_pack(), indexer=S.stand_in, mount="/rr/")
    html = files["index.html"].decode()
    block = re.search(r'<script type="application/json" data-room-suggest>(.*?)</script>', html, re.DOTALL).group(1)
    assert "<" not in block  # "</script><!--" in a label cannot end or change the block
    data = json.loads(block)
    assert data["recent_docs"] == [{"label": "Memo", "url": "/rr/memo-text/"},
                                   {"label": "Camera Contract", "url": "/rr/camera-contract/"}]
    assert data["groups"][1]["items"][1]["label"] == "</script><!-- x"
    assert data["rank"][1] | {} == _rank("memo-text", "Memo", date="2024-03-01", year="2024") | {
        "label": "Memo", "url": "/rr/memo-text/"}
    off = B.render(parse(_with_suggest()), engine=G.ENGINE, pack=_pack(on=False), mount="/rr/")
    assert "data-room-suggest" not in off["index.html"].decode()


@pytest.fixture(scope="module")
def site_room(room, tmp_path_factory):
    """As `room` (its Chromium), with the site's own suggestion panel."""
    b = room[0]
    root = tmp_path_factory.mktemp("suggest-room")
    B.write(B.render(parse(_with_suggest()), engine=G.ENGINE, pack=_pack(), mount="/reading-room/"),
            root / "reading-room")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield b, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _panel(page) -> list[tuple[str, list[str]]]:
    lb = page.get_by_role("listbox", name="Suggestions")
    lb.wait_for(state="visible")
    return [tuple(g) for g in lb.get_by_role("group").evaluate_all(
        "gs => gs.map(g => [g.querySelector('.room__suggest-h').textContent.trim(),"
        " Array.from(g.querySelectorAll('[role=option]')).map(o => o.childNodes[0].textContent.trim())])")]


def test_the_site_panel_draws_its_groups_in_its_order_and_words(site_room):
    b, base = site_room
    page, _ = _open(b, base)
    q = page.get_by_role("combobox", name="Search records")
    q.press("ArrowDown")
    # No text: the site's recent documents in its order, then each group's `empty` items.
    assert _panel(page) == [("Recent documents", ["Memo", "Camera Contract"]), ("Try searching", ["Retention"]),
                            ("Agencies", ["Test Agency"])]
    # Typing: top matches, then the groups' items that hold the text (Try searching shows none).
    q.press_sequentially("agen", delay=20)
    page.wait_for_function("() => document.querySelector('#room-suggest .room__suggest-h')"
                           " && document.querySelector('#room-suggest .room__suggest-h').textContent === 'Top matches'")
    got = _panel(page)
    assert [g for g, _ in got] == ["Top matches", "Agencies"] and got[1][1] == ["Test Agency"]
    assert "(1 record)" in page.locator("#room-suggest").get_by_role("option", name=re.compile("^Test Agency")).inner_text()
    page.close()


def test_choosing_a_site_suggestion_searches_its_query(site_room):
    b, base = site_room
    page, _ = _open(b, base)
    q = page.get_by_role("combobox", name="Search records")
    q.press("ArrowDown")
    _panel(page)
    page.get_by_role("option", name="Retention").click()
    assert q.input_value() == WORD
    page.wait_for_selector(".room__result")
    assert page.get_by_role("status").inner_text() == "2 of 5 records match"
    page.close()


def _top(site_room, text) -> list[str]:
    """Top matches for `text` typed into a fresh page (no panel left from another query)."""
    page, _ = _open(*site_room)
    page.get_by_role("combobox", name="Search records").press_sequentially(text, delay=20)
    page.wait_for_function("() => document.querySelector('#room-suggest .room__suggest-h')")
    top = dict(_panel(page)).get("Top matches", [])
    page.close()
    return top


def test_top_matches_are_the_sites_own_ranking(site_room):
    # Only the scorer reads the rank rows: no indexed text holds ZEBRA.
    assert _top(site_room, ZEBRA[:6]) == ["Camera Contract"]
    # A title match (Memo: exact title, 120 + 80) outranks a summary match (12), and live's
    # normalize applies (case, punctuation).
    assert _top(site_room, "MEMO!") == ["Memo", "Camera Contract"]
    # A document type matches as the site derived it.
    assert _top(site_room, "contract") == ["Camera Contract"]
