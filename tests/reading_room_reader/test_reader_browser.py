"""The shared reader engine, driven in real Chromium against a local site.

The reader shipped for three months with no test at all, and the one saved
browser check (the 2026-09-27 audit's keyboard pass) read the "/ 22" page
total before and after pressing Next, so it passed whether or not the page
moved. Every navigation assertion here reads the page that is actually shown.

Skipped, loudly, when Playwright's Chromium is not installed (same rule as
tests/auditkit/test_probes_in_browser.py).
"""

from __future__ import annotations

import json

import pytest

from tests.reading_room_reader.conftest import PASSAGE, axe_source, page_html

sync_api = pytest.importorskip("playwright.sync_api")
pytest.importorskip("fitz")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001 — any launch failure is "no browser"
            pytest.skip(f"Playwright Chromium not installed: {e}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1024, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    yield pg
    ctx.close()


def status(page) -> str:
    return page.locator(".rr-reader [data-reader-status]").inner_text()


def wait_status(page, text: str) -> None:
    page.wait_for_function(
        "t => { const s = document.querySelector('.rr-reader [data-reader-status]');"
        " return !!s && s.textContent.indexOf(t) !== -1; }",
        arg=text,
    )


def open_pdf(page, reader_site, name="pdf", file="text.pdf", **kw):
    page.goto(reader_site.page(name, page_html(file, "pdf", **kw)))
    wait_status(page, "Page 1 of 3.")


# ---- rendering and navigation -------------------------------------------------

def test_pdf_renders_with_a_text_layer(page, reader_site):
    open_pdf(page, reader_site)
    assert page.locator(".rr-reader__canvas").count() == 1
    page.wait_for_function("document.querySelectorAll('.rr-reader__textlayer span').length > 0")
    assert "camera contract" in page.locator(".rr-reader__textlayer").inner_text().lower()


def test_next_button_actually_changes_the_page(page, reader_site):
    open_pdf(page, reader_site)
    page.get_by_role("button", name="Next page").click()
    wait_status(page, "Page 2 of 3.")
    assert page.locator("input.rr-reader__page-input").input_value() == "2"


def test_hash_deep_link_opens_that_page(page, reader_site):
    page.goto(reader_site.page("deep", page_html("text.pdf", "pdf")) + "#page-3")
    wait_status(page, "Page 3 of 3.")


def test_keyboard_only_paging(page, reader_site):
    open_pdf(page, reader_site)
    page.locator(".rr-reader__stage").focus()
    page.keyboard.press("ArrowRight")
    wait_status(page, "Page 2 of 3.")
    page.keyboard.press("ArrowLeft")
    wait_status(page, "Page 1 of 3.")


def test_image_only_scan_renders_without_a_text_layer(page, reader_site):
    open_pdf(page, reader_site, name="scan", file="scan.pdf")
    assert page.locator(".rr-reader__canvas").count() == 1
    assert page.locator(".rr-reader__textlayer span").count() == 0


def test_pagechange_event_reports_the_shown_page(page, reader_site):
    page.add_init_script(
        "window.__rr = []; document.addEventListener('rr-reader:pagechange',"
        " e => window.__rr.push(e.detail.pages[0]));"
    )
    open_pdf(page, reader_site)
    page.get_by_role("button", name="Next page").click()
    wait_status(page, "Page 2 of 3.")
    assert page.evaluate("window.__rr") == [1, 2]


# ---- search ------------------------------------------------------------------

def test_search_highlights_terms_without_mangling_entities(page, reader_site):
    open_pdf(page, reader_site)
    page.get_by_role("searchbox", name="Search within this document").fill("amp")
    page.wait_for_selector(".rr-reader__find-hit")
    first = page.locator(".rr-reader__find-hit").first
    # The literal ampersand survives as text, and only the real word is marked.
    assert first.inner_text().replace("\n", " ") == "Page 2 Flock & ALPR camera amp contract"
    assert first.locator("mark").all_inner_texts() == ["amp"]


def test_search_hit_jumps_to_its_page(page, reader_site):
    open_pdf(page, reader_site)
    page.get_by_role("searchbox", name="Search within this document").fill("amp")
    page.locator(".rr-reader__find-hit").nth(1).click()
    wait_status(page, "Page 3 of 3.")


# ---- static mode: pages.json searched in the browser ---------------------------

STATIC = {"config": {"docSearchUrl": "", "passageUrl": ""}, "pages_url": "/api/pages.json"}


def _search(page, q):
    return page.evaluate(
        "([q]) => fetch('/api/pages.json').then(r => r.json()).then(j => RRReader.searchPages(j.pages, q))", [q])


def test_static_search_needs_no_search_route(page, reader_site):
    open_pdf(page, reader_site, name="static", **STATIC)
    page.get_by_role("searchbox", name="Search within this document").fill("renewal")
    page.wait_for_selector(".rr-reader__find-hit")
    hits = page.locator(".rr-reader__find-hit").all_inner_texts()
    assert [h.split("\n")[0] for h in hits] == ["Page 2", "Page 3"]
    page.locator(".rr-reader__find-hit").nth(1).click()
    wait_status(page, "Page 3 of 3.")
    # No passage route, no citations: the same as a site that wired none.
    assert page.get_by_role("button", name="Cite the current page").count() == 0


def test_static_search_matches_like_the_site_route(page, reader_site):
    open_pdf(page, reader_site, name="static2", **STATIC)
    def pages(q):
        return [h["page_number"] for h in _search(page, q)]

    assert pages("flock alpr") == [1, 2]           # every word, any order
    assert pages("flock thirty") == [2]            # all words must be on the page
    assert pages("flo") == [1, 2]                  # a word prefix matches
    assert pages("lock") == [1, 2, 3]              # no word starts "lock", so plain text, as the site falls back
    assert pages("lock renewal") == []             # mid-word "lock" fails every-word, and the phrase is absent
    assert pages("flock renewal") == [2]           # a word start satisfies it
    assert pages("ALPR re") == [1, 2]              # short words are ignored, as on the site
    assert pages("e 2: t") == [2]                  # no 3+ letter word: the phrase as plain text
    assert pages("") == [] and pages("zz") == []


def test_static_snippet_is_the_site_snippet(page, reader_site):
    open_pdf(page, reader_site, name="static3", **STATIC)
    long = ("word " * 60) + "needle " + ("tail " * 60)
    hit = page.evaluate("([t]) => RRReader.searchPages([{n: 7, text: t}], 'needle')", [long])[0]
    flat = " ".join(long.split())
    at = flat.index("needle")
    assert hit["page_number"] == 7 and hit["snippet"] == "\u2026" + flat[at - 90: at + 90] + "\u2026"
    short = page.evaluate("([t]) => RRReader.searchPages([{n: 1, text: t}], 'flock')", ["  Flock\n\n camera  "])
    assert [(h["page_number"], h["snippet"]) for h in short] == [(1, "Flock camera")]


def test_static_search_survives_a_missing_pages_file(page, reader_site):
    open_pdf(page, reader_site, name="static4", config=STATIC["config"], pages_url="/api/missing.json")
    box = page.get_by_role("searchbox", name="Search within this document")
    box.fill("renewal")
    page.wait_for_timeout(600)
    assert page.locator(".rr-reader__find-hit").count() == 0
    assert page.locator("[data-reader-fallback]").is_hidden()  # the document itself is untouched
    wait_status(page, "Page 1 of 3.")


# ---- citations ---------------------------------------------------------------

def test_cite_page_shows_the_server_citation(page, reader_site):
    open_pdf(page, reader_site)
    page.get_by_role("button", name="Cite the current page").click()
    panel = page.locator(".rr-reader__cite")
    panel.locator(".rr-reader__cite-ref").filter(has_text="Test Agency").wait_for()
    assert PASSAGE["reference"] in panel.inner_text()
    assert PASSAGE["passage"]["text"] in panel.locator("blockquote").inner_text()
    assert page.evaluate("document.activeElement.classList.contains('rr-reader__cite')")


def test_cite_is_on_for_an_existing_feature_list_without_the_token(page, reader_site):
    # glassgovernment.org's template says data-features="spread,lightbox,fullscreen,search".
    open_pdf(page, reader_site, name="ggfeat", features="spread,lightbox,fullscreen,search")
    assert page.get_by_role("button", name="Cite the current page").count() == 1


def test_no_cite_without_a_passage_route(page, reader_site):
    open_pdf(page, reader_site, name="nocite", config={"passageUrl": ""})
    assert page.get_by_role("button", name="Cite the current page").count() == 0


def test_failed_copy_is_announced_not_silent(page, reader_site):
    page.add_init_script(
        "navigator.clipboard.writeText = () => Promise.reject(new Error('denied'));"
        " document.execCommand = () => false;"
    )
    open_pdf(page, reader_site)
    page.get_by_role("button", name="Cite the current page").click()
    panel = page.locator(".rr-reader__cite")
    panel.locator(".rr-reader__cite-ref").filter(has_text="Test Agency").wait_for()
    panel.get_by_role("button", name="Copy citation").click()
    page.wait_for_function(
        "document.querySelector('.rr-reader__cite .rr-reader__sr-only').textContent.indexOf('Copy failed') === 0"
    )


def test_rr_cite_copies_through_the_legacy_path_when_clipboard_refuses(page, reader_site):
    page.add_init_script(
        "navigator.clipboard.writeText = () => Promise.reject(new Error('denied'));"
        " window.__copied = false; const orig = document.execCommand.bind(document);"
        " document.execCommand = (c) => { if (c === 'copy') { window.__copied = true; return true; } return orig(c); };"
    )
    open_pdf(page, reader_site)
    btn = page.locator("p.cite [data-rr-cite-copy]")
    btn.click()
    page.wait_for_function("window.__copied === true")
    assert btn.inner_text() == "Copied"


def test_slow_load_offers_the_links_then_the_reader_takes_the_page_back(page, reader_site):
    # deflockdane.org, 2026-10-07: a 1.8 MB PDF took 50 s; the links appeared
    # at 20 s as promised, but stayed beside the reader after it arrived.
    page.goto(reader_site.page("slow", page_html("text.pdf", "pdf", file_dir="slow",
                                                 config={"slowLoadMs": 300})))
    page.wait_for_selector(".rr-reader[data-reader-failed='1'] [data-reader-fallback] a.fb-open")
    wait_status(page, "Page 1 of 3.")
    assert page.locator(".rr-reader [data-reader-fallback]").count() == 0
    assert page.locator(".rr-reader").get_attribute("data-reader-failed") is None


def test_poster_shows_page_one_at_once_and_gives_way_to_the_real_page(page, reader_site):
    # pdf.js reads every page entry before it can draw page 1; on a slow link
    # that is most of the file. The site's own page-1 image fills the wait.
    page.goto(reader_site.page("poster", page_html("text.pdf", "pdf", file_dir="slow", poster="/files/page.png")))
    poster = page.locator(".rr-reader__stage img.rr-reader__poster")
    poster.wait_for()
    assert poster.get_attribute("alt") == "Page 1 of Camera Contract, a preview image while the reader loads"
    assert page.locator(".rr-reader__canvas").count() == 0 or not page.locator(".rr-reader__pagebox").first.is_visible()
    wait_status(page, "Page 1 of 3.")
    assert poster.count() == 0
    assert page.locator(".rr-reader__canvas").first.is_visible()


def test_no_poster_for_a_deep_link_to_another_page(page, reader_site):
    page.goto(reader_site.page("poster-deep", page_html("text.pdf", "pdf", file_dir="slow", poster="/files/page.png")) + "#page-2")
    page.wait_for_selector(".rr-reader__stage")
    assert page.locator("img.rr-reader__poster").count() == 0
    wait_status(page, "Page 2 of 3.")


def test_a_broken_poster_is_dropped_and_the_reader_still_loads(page, reader_site):
    page.goto(reader_site.page("poster-bad", page_html("text.pdf", "pdf", file_dir="slow", poster="/files/missing.png")))
    page.wait_for_function("!document.querySelector('img.rr-reader__poster')")
    wait_status(page, "Page 1 of 3.")


# ---- lightbox ----------------------------------------------------------------

def test_lightbox_traps_focus_and_returns_it(page, reader_site):
    open_pdf(page, reader_site, name="lb", features="spread,search,lightbox,fullscreen")
    enlarge = page.get_by_role("button", name="Enlarge reader")
    enlarge.click()
    assert page.locator(".rr-reader").get_attribute("aria-modal") == "true"
    for _ in range(25):
        page.keyboard.press("Tab")
        assert page.evaluate("document.querySelector('.rr-reader').contains(document.activeElement)")
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.classList.contains('rr-reader__btn--enlarge')")


# ---- failure paths: the reader may only add to the page ------------------------

def _fallback_restored(page) -> None:
    page.wait_for_selector(".rr-reader[data-reader-failed='1']")
    assert page.locator(".rr-reader [data-reader-fallback] a.fb-open").is_visible()
    assert page.locator(".rr-reader [data-reader-fallback] a.fb-text").is_visible()


def test_missing_pdfjs_restores_the_fallback_links(page, reader_site):
    page.goto(reader_site.page("nopdfjs", page_html("text.pdf", "pdf", config={"pdfJsUrl": "/pdfjs/missing.js"})))
    _fallback_restored(page)


def test_corrupt_pdf_restores_the_fallback_links(page, reader_site):
    page.goto(reader_site.page("corrupt", page_html("corrupt.pdf", "pdf")))
    _fallback_restored(page)


def test_unsupported_type_leaves_the_fallback_in_place(page, reader_site):
    page.goto(reader_site.page("docx", page_html("thing.docx", "docx")))
    wait_status(page, "Inline preview is not available")
    assert page.locator("[data-reader-fallback] a.fb-open").is_visible()


def test_without_javascript_the_fallback_links_are_there(browser, reader_site):
    ctx = browser.new_context(java_script_enabled=False)
    pg = ctx.new_page()
    pg.goto(reader_site.page("nojs", page_html("text.pdf", "pdf")))
    assert pg.locator("[data-reader-fallback] a.fb-open").is_visible()
    ctx.close()


# ---- image and text modules ---------------------------------------------------

def test_image_module_uses_the_title_for_alt_text(page, reader_site):
    page.goto(reader_site.page("img", page_html("page.png", "png")))
    img = page.locator("img.rr-reader__image")
    img.wait_for()
    page.wait_for_function("document.querySelector('img.rr-reader__image').complete")
    assert img.get_attribute("alt") == "Scan of Camera Contract"


def test_broken_image_restores_the_fallback_links(page, reader_site):
    page.goto(reader_site.page("imgbad", page_html("nope.png", "png")))
    _fallback_restored(page)


def test_text_module_shows_markup_as_source(page, reader_site):
    page.goto(reader_site.page("txt", page_html("notes.txt", "txt")))
    pre = page.locator("pre.rr-reader__text")
    pre.wait_for()
    assert "<b>shown as source, not bold</b>" in pre.inner_text()
    assert pre.locator("b").count() == 0
    assert pre.get_attribute("tabindex") == "0"


def test_table_module_renders_grid_and_cites_row(page, reader_site):
    page.goto(reader_site.page("tbl", page_html("data.csv", "csv", modules=("rr-reader-table",))))
    tbl = page.locator("table.rr-reader__grid")
    tbl.wait_for()
    headers = [th.inner_text().strip() for th in page.locator("table.rr-reader__grid th").all()]
    assert headers == ["#", "Year", "Agency", "Amount"]
    assert "Showing 1–2 of 2 rows" in page.locator(".rr-reader__table-count").inner_text()
    # Click row 1
    page.locator("td.rr-reader__grid-row-num").first.click()
    cite_bar = page.locator(".rr-reader__table-citation")
    cite_bar.wait_for()
    assert "Row 1" in cite_bar.inner_text()


# ---- hostile input (roadmap T3): text stays text, never markup or a formula -----

PWN = '<img src=x onerror="window.__pwned=1">'


def test_hostile_csv_cells_render_as_text(page, reader_site):
    # Formula leads (= + - @), markup, a quoted field with a comma and a doubled quote,
    # a ragged row and an unclosed quote at the end of the file.
    (reader_site.dir / "files" / "hostile.csv").write_text(
        'Name,Value\n"=HYPERLINK(""http://x.test"",""click"")",+1+1\n-2+3,@SUM(A1)\n'
        '"<img src=x onerror=""window.__pwned=1"">","a, ""b"""\nonly-one\n"never closed,x\n', encoding="utf-8")
    page.goto(reader_site.page("tbl-hostile", page_html("hostile.csv", "csv", modules=("rr-reader-table",))))
    page.locator("table.rr-reader__grid").wait_for()
    cells = [c.inner_text() for c in page.locator("table.rr-reader__grid tbody td:not(.rr-reader__grid-row-num)").all()]
    for literal in ('=HYPERLINK("http://x.test","click")', "+1+1", "-2+3", "@SUM(A1)", PWN, 'a, "b"'):
        assert literal in cells, literal
    assert page.locator("table.rr-reader__grid img").count() == 0
    assert page.evaluate("window.__pwned") is None
    # A copied row citation starts with the record's title, never with a cell's formula.
    page.locator("td.rr-reader__grid-row-num").first.click()
    assert page.locator(".rr-reader__table-citation-text").inner_text().startswith("Camera Contract, Row 1")


def test_a_csv_over_the_cap_falls_back_to_the_links(page, reader_site):
    (reader_site.dir / "files" / "huge.csv").write_text("a,b\n" + "1,2\n" * 1_400_000, encoding="utf-8")  # 5.6 MB
    page.goto(reader_site.page("tbl-huge", page_html("huge.csv", "csv", modules=("rr-reader-table",))))
    wait_status(page, "too large")
    assert page.locator(".rr-reader table, .rr-reader__table-filter, .rr-reader__table-pager").count() == 0
    assert page.locator("[data-reader-fallback] .fb-open").is_visible()


def test_a_text_file_over_the_cap_falls_back_to_the_links(page, reader_site):
    (reader_site.dir / "files" / "huge.txt").write_text("x" * (1024 * 1024 + 10), encoding="utf-8")
    page.goto(reader_site.page("txt-huge", page_html("huge.txt", "txt")))
    wait_status(page, "too large")
    assert page.locator("pre.rr-reader__text").count() == 0
    assert page.locator("[data-reader-fallback] .fb-open").is_visible()


def test_hostile_ocr_box_text_renders_as_text(page, reader_site):
    (reader_site.dir / "files" / "hostile-pages.json").write_text(json.dumps({
        "slug": "test-doc", "total": 1,
        "pages": [{"n": 1, "provenance": "<i>ocr</i>", "text": PWN,
                   "boxes": [{"box": [0.1, 0.1, 0.2, 0.3], "text": PWN, "confidence": 0.9}]}]}), encoding="utf-8")
    page.goto(reader_site.page("img-hostile", page_html("page.png", "png", pages_url="/files/hostile-pages.json")))
    page.locator(".rr-reader__transcript-token").first.wait_for(state="attached")
    assert page.locator(".rr-reader__transcript-token").first.text_content().strip() == PWN
    assert page.locator(".rr-reader__box").first.get_attribute("title") == PWN
    assert page.locator(".rr-reader__transcript-badge").first.text_content() == "<i>ocr</i>"
    assert page.locator(".rr-reader__transcript-pane img, .rr-reader__transcript-pane i, .rr-reader__box-overlay img").count() == 0
    assert page.evaluate("window.__pwned") is None


# ---- accessibility -------------------------------------------------------------

def test_axe_finds_no_violations_in_the_reader(page, reader_site):
    open_pdf(page, reader_site, name="axe", features="spread,search,lightbox,fullscreen")
    page.get_by_role("searchbox", name="Search within this document").fill("amp")
    page.wait_for_selector(".rr-reader__find-hit")
    page.get_by_role("button", name="Cite the current page").click()
    page.locator(".rr-reader__cite-ref").filter(has_text="Test Agency").wait_for()

    page.evaluate(axe_source())
    result = page.evaluate(
        """() => axe.run('.rr-reader', {
             runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'] }
           }).then(r => r.violations.map(v => v.id + ': ' + v.nodes.map(n => n.target.join(' ')).join(', ')))"""
    )
    assert result == []


# deflockdane.org's bridge (deflock-reading-room.css). 0.4.0's translucent
# search mark passed axe on the light defaults and failed live on this one.
DARK_BRIDGE = """<style>body{background:#0b0e14;color:#dce3ed}
.rr-reader{--rr-paper:#10131a;--rr-paper-raised:#181d26;--rr-ink:#dce3ed;--rr-ink-soft:#94a3b8;
--rr-ink-faint:#7a8799;--rr-rule:#3a4455;--rr-accent:#046bd2;--rr-focus:#cbd5e1;background:var(--rr-paper);color:var(--rr-ink)}</style>"""


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_axe_search_hits_pass_on_light_and_dark_consumers(page, reader_site, theme):
    head = DARK_BRIDGE if theme == "dark" else ""
    open_pdf(page, reader_site, name=f"axe-{theme}", head=head)
    page.get_by_role("searchbox", name="Search within this document").fill("amp")
    page.wait_for_selector(".rr-reader__find-hit mark")
    page.evaluate(axe_source())
    result = page.evaluate(
        """() => axe.run('.rr-reader__find-results', { runOnly: { type: 'rule', values: ['color-contrast'] } })
             .then(r => r.violations.map(v => v.nodes.map(n => n.target.join(' ')).join(', ')))"""
    )
    assert result == []


def test_controls_meet_the_44px_target(page, reader_site):
    open_pdf(page, reader_site, name="targets", features="spread,search,lightbox,fullscreen")
    small = page.evaluate(
        """() => Array.from(document.querySelectorAll('.rr-reader button, .rr-reader input'))
             .filter(e => e.offsetParent !== null)
             .map(e => [e.getAttribute('aria-label') || e.textContent, e.getBoundingClientRect()])
             .filter(([, r]) => r.height < 44 || r.width < 44)
             .map(([n, r]) => n + ' ' + Math.round(r.width) + 'x' + Math.round(r.height))"""
    )
    assert small == []


# ---- 0.7.0: spans in static search, a page's own citation, the fallback -------

def _py_locate(text: str, query: str):
    """GGRR_Search::locate over GGRR_Search::terms, in code points (the reference)."""
    import re
    terms = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 3]
    low = "".join(c.lower() if len(c.lower()) == 1 else c for c in text)
    found = [(low.find(t), len(t)) for t in terms if low.find(t) >= 0]
    if not found:
        return None, None
    at, n = min(found)
    return at, at + n


def test_static_hits_carry_the_span_the_site_route_gives(page, reader_site):
    open_pdf(page, reader_site, name="span", **STATIC)
    cases = [
        ("Ünïcode Café, CAMERA then flock", "flock camera"),   # the earliest term wins, case-insensitive
        ("\U0001F693 police flock", "flock"),                     # an astral character counts as one, as mb_* counts
        ("Flock & ALPR renewal", "renewal"),
        ("Page 2: the thing", "e 2: t"),                          # no 3+ letter term: plain-text hit, no span
    ]
    for text, q in cases:
        hit = page.evaluate("([t, q]) => RRReader.searchPages([{n: 1, text: t}], q)[0]", [text, q])
        want = _py_locate(text, q)
        assert (hit["offset_start"], hit["offset_end"]) == want, (text, q, hit)
        if want[0] is not None:
            assert text[want[0]:want[1]].lower() in q.lower()


def _cited_pages(reader_site) -> str:
    from tests.reading_room_reader.conftest import STATIC_PAGES
    pages = json.loads(json.dumps(STATIC_PAGES))
    for p in pages["pages"]:
        p["cite"] = {"reference": f"Test Agency. \"Camera Contract.\" 2026, p. {p['n']}. Test Room, "
                                  f"https://example.test/library/test-doc/#page-{p['n']}.",
                     "provenance_level": "page", "ocr_confidence": None}
    (reader_site.dir / "api" / "pages-cite.json").write_text(json.dumps(pages))
    return "/api/pages-cite.json"


def _passage_requests(page) -> list:
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/api/passage" in r.url else None)
    return seen


def test_cite_page_shows_the_page_cite_with_no_request(page, reader_site):
    seen = _passage_requests(page)
    open_pdf(page, reader_site, name="citepage", pages_url=_cited_pages(reader_site))
    page.get_by_role("button", name="Cite the current page").click()
    panel = page.locator(".rr-reader__cite")
    panel.locator(".rr-reader__cite-ref").filter(has_text="p. 1.").wait_for()
    assert "#page-1" in panel.locator(".rr-reader__cite-ref").inner_text()
    assert panel.locator("blockquote").is_hidden() and panel.locator(".rr-reader__cite-note").is_hidden()
    assert "Provenance: page" in panel.locator(".rr-reader__cite-prov").inner_text()
    assert panel.get_by_role("button", name="Copy citation").is_visible()
    assert page.evaluate("document.activeElement.classList.contains('rr-reader__cite')")
    assert seen == []


def test_a_hit_cite_sends_its_span_to_the_route(page, reader_site):
    seen = _passage_requests(page)
    open_pdf(page, reader_site, name="citehit", pages_url=_cited_pages(reader_site))
    page.get_by_role("searchbox", name="Search within this document").fill("renewal")
    page.wait_for_selector(".rr-reader__find-hit")
    page.get_by_role("button", name="Cite this passage on page 2").click()
    page.locator(".rr-reader__cite blockquote").filter(has_text="retain").wait_for()
    text = STATIC_PAGES_TEXT(2)
    at = text.lower().index("renewal")
    assert len(seen) == 1 and f"page=2&start={at}&end={at + 7}" in seen[0]


def STATIC_PAGES_TEXT(n: int) -> str:
    from tests.reading_room_reader.conftest import STATIC_PAGES
    return next(p["text"] for p in STATIC_PAGES["pages"] if p["n"] == n)


@pytest.mark.parametrize("failure", ["500", "unreachable", "not-found", "timeout"])
def test_a_failed_passage_falls_back_to_the_page_citation(page, reader_site, failure):
    if failure == "500":
        page.route("**/api/passage*", lambda r: r.fulfill(status=500, body="no"))
    elif failure == "not-found":
        page.route("**/api/passage*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                         body=json.dumps({"found": False, "error": "not_found"})))
    elif failure == "timeout":
        page.route("**/api/passage*", lambda r: None)   # never answered
    config = {"citeTimeoutMs": 700}
    if failure == "unreachable":
        config["passageUrl"] = "http://127.0.0.1:9/passage"
    open_pdf(page, reader_site, name=f"citefail-{failure}", pages_url=_cited_pages(reader_site), config=config)
    page.get_by_role("searchbox", name="Search within this document").fill("renewal")
    page.wait_for_selector(".rr-reader__find-hit")
    page.get_by_role("button", name="Cite this passage on page 3").click()
    panel = page.locator(".rr-reader__cite")
    panel.locator(".rr-reader__cite-note").filter(has_text="could not be resolved here").wait_for(timeout=5000)
    assert "p. 3." in panel.locator(".rr-reader__cite-ref").inner_text()
    assert panel.locator("blockquote").is_hidden()
    assert panel.get_by_role("button", name="Copy quote").count() == 0
    assert panel.get_by_role("button", name="Copy citation").is_visible()
    assert "Durable key" not in panel.inner_text()
    page.wait_for_function("() => /citing page 3/.test(document.querySelector('.rr-reader__cite [role=status]').textContent)")


def test_without_a_page_cite_a_failure_still_says_so(page, reader_site):
    page.route("**/api/passage*", lambda r: r.fulfill(status=500, body="no"))
    open_pdf(page, reader_site, name="citefail-nocite", **STATIC | {"config": {"docSearchUrl": ""}})
    page.get_by_role("searchbox", name="Search within this document").fill("renewal")
    page.wait_for_selector(".rr-reader__find-hit")
    page.get_by_role("button", name="Cite this passage on page 2").click()
    page.locator(".rr-reader__cite-ref").filter(has_text="no citation is offered").wait_for()
    assert page.locator(".rr-reader__cite-note").is_hidden()


def test_pdf_js_is_opened_with_eval_disabled(page, reader_site):
    """CVE-2024-4367: pdf.js <= 4.1.392 evals font data; the pinned 3.x has no
    fix, so every getDocument must carry isEvalSupported:false."""
    # The lib's exports are non-writable, so stand a Proxy in front of window.pdfjsLib.
    wrap = (
        "\n;(function(){var l=window.pdfjsLib;window.__rrGetDocumentArgs=[];"
        "window.pdfjsLib=new Proxy(l,{get:function(t,k){if(k==='getDocument'){"
        "return function(a){window.__rrGetDocumentArgs.push(a);return t.getDocument(a);};}"
        "return t[k];}});})();\n"
    )

    def tap(route):
        resp = route.fetch()
        route.fulfill(response=resp, body=resp.text() + wrap)

    page.route("**/pdfjs/pdf.min.js", tap)
    open_pdf(page, reader_site)
    args = page.evaluate("window.__rrGetDocumentArgs")
    assert args, "the reader never called getDocument"
    assert all(isinstance(a, dict) and a.get("isEvalSupported") is False for a in args)
