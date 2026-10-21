"""The room's own header, navigation and footer (plan Task 5).

Every page draws its chrome from the pack's `chrome`: landmarks, a skip link
first, one labelled site nav whose menu folds into details/summary on narrow
screens (no JavaScript), focus styles from tokens. The captured WordPress shell
it replaced is retired (D7 superseded, 2026-10-14).
"""

from __future__ import annotations

import copy
import functools
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from roomkit import build as B
from roomkit import color as C
from roomkit import css as CSS
from roomkit import pack as K
from roomkit import room as R
from roomkit import view as V
from roomkit.manifest import parse
from tests.roomkit import test_golden as G

PACKS = ("default", "deflockdane", "glassgovernment", "hrtarchive")
SITES = PACKS[1:]
ROOMKIT = Path(R.__file__).resolve().parent
FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex='-1'])"


def _plain(site: str, mount: str | None = None) -> dict[str, bytes]:
    """The golden manifest built in `site`'s pack."""
    m = G._base()
    if site != "default":
        m["site"]["template"] = site
    return B.render(parse(m), engine=G.ENGINE, pack=K.for_site(site), mount=mount)


def _pages(files: dict[str, bytes]) -> dict[str, BeautifulSoup]:
    return {p: BeautifulSoup(b.decode(), "html.parser") for p, b in files.items() if p.endswith(".html")}


def _css(files: dict[str, bytes]) -> str:
    return files[B.published(files, "assets/room.css")].decode()


def _site_nav(soup: BeautifulSoup):
    return [n for n in soup.find_all("nav") if not n.find_parent("main")]


# --- landmarks, skip link, nav, menu ------------------------------------------------

@pytest.mark.parametrize("site", PACKS)
def test_every_page_has_the_four_landmarks(site):
    for path, soup in _pages(_plain(site)).items():
        body = soup.body
        assert body.find("header", class_="room-chrome", recursive=False), path
        assert body.find("main", id="room-content", recursive=False), path
        assert body.find("footer", class_="room-chrome", recursive=False), path
        navs = _site_nav(soup)
        assert len(navs) == 1 and navs[0].find_parent("header"), path
        assert navs[0]["aria-label"] == K.for_site(site)["chrome"]["nav_label"], path


@pytest.mark.parametrize("site", PACKS)
def test_the_skip_link_is_first_and_targets_the_content(site):
    chrome = K.for_site(site)["chrome"]
    for path, soup in _pages(_plain(site)).items():
        first = soup.body.select(FOCUSABLE)[0]
        assert first.name == "a" and first["href"] == "#room-content", path
        assert first.get_text() == chrome["skip_text"], path
        assert soup.find(id="room-content").name == "main"


@pytest.mark.parametrize("site", PACKS)
def test_the_menu_is_a_details_summary_holding_every_link(site):
    chrome = K.for_site(site)["chrome"]
    soup = _pages(_plain(site))["index.html"]
    nav = _site_nav(soup)[0]
    menu = nav.find("details", recursive=False)
    assert menu is not None and menu.find("summary", recursive=False).get_text() == chrome["menu_label"]
    want = [(ln["label"], ln["url"]) for it in chrome["nav"] for ln in it.get("links", [it])]
    assert [(a.get_text(), a["href"]) for a in menu.find_all("a")] == want
    groups = [it["label"] for it in chrome["nav"] if "links" in it]
    assert [d.summary.get_text() for d in menu.find_all("details")] == groups
    assert not soup.find_all("script", src=re.compile("chrome"))  # no JavaScript for the menu


def test_the_header_and_footer_say_what_the_pack_says():
    chrome = K.for_site("hrtarchive")["chrome"]
    soup = _pages(_plain("hrtarchive"))["index.html"]
    home = soup.find("a", class_="room-chrome__home")
    assert (home.get_text(), home["href"]) == (chrome["home"]["label"], chrome["home"]["url"])
    foot = soup.body.find("footer", class_="room-chrome")
    assert [p.get_text() for p in foot.find_all("p")] == chrome["footer_text"]
    assert [(a.get_text(), a["href"]) for a in foot.find_all("a")] == \
        [(ln["label"], ln["url"]) for col in chrome["footer"] for ln in col["links"]]
    dd = _pages(_plain("deflockdane"))["index.html"]
    assert dd.find(class_="room-chrome__tagline").get_text() == K.for_site("deflockdane")["chrome"]["tagline"]


def test_a_notice_renders_under_the_header_and_text_is_escaped():
    pack = copy.deepcopy(K.for_site("default"))
    pack["chrome"]["notice"] = {"text": "Moved <here> & there", "url": "/news/"}
    pack["chrome"]["home"]["label"] = 'A "quoted" <b>name</b>'
    html = B.render(parse(G._base()), engine=G.ENGINE, pack=pack)["index.html"].decode()
    assert '<p class="room-chrome__notice"><a href="/news/">Moved &lt;here&gt; &amp; there</a></p>' in html
    assert ">A &quot;quoted&quot; &lt;b&gt;name&lt;/b&gt;</a>" in html


def test_doc_header_actions_renders_meta_and_links():
    m_data = copy.deepcopy(G._base())
    doc = m_data["documents"][0]
    doc["display"]["header"] = {
        "meta": ["FBI", '"Cuban Matters"', "1962–1970"],
        "original_url": "/library/cointelpro-cuba-01/file/?original=1",
        "ia_url": "https://archive.org/details/cointelpro-cuba-01",
        "category": "historical",
    }
    pack = K.for_site("glassgovernment")
    rendered = B.render(parse(m_data), engine=G.ENGINE, pack=pack)
    page_html = rendered["camera-contract/index.html"].decode()

    # 1. Agency, collection, year span in header
    assert '<div class="room__header-meta room__header-meta--historical">' in page_html
    assert '<p class="room__file-meta">' in page_html
    assert "<span>FBI</span>" in page_html
    assert '<span>&quot;Cuban Matters&quot;</span>' in page_html
    assert "<span>1962–1970</span>" in page_html

    # 2. Open original file link with ?original=1
    assert 'href="/library/cointelpro-cuba-01/file/?original=1"' in page_html
    assert "Open original file" in page_html

    # 3. Internet Archive stamp matching live
    assert 'href="https://archive.org/details/cointelpro-cuba-01"' in page_html
    assert "Internet Archive" in page_html

    # Test pending status
    doc["display"]["header"]["ia_url"] = ""
    doc["display"]["header"]["ia_pending"] = True
    page_pending = B.render(parse(m_data), engine=G.ENGINE, pack=pack)["camera-contract/index.html"].decode()
    assert 'aria-label="Internet Archive backup pending"' in page_pending
    assert "backup pending" in page_pending


# --- styles ---------------------------------------------------------------------------

def test_chrome_css_is_scoped_and_paints_only_tokens():
    sels = CSS.css_selectors(R.CHROME_CSS + R.CHROME_WIDE_CSS)
    assert sels and all(s.startswith(CSS.PLAIN_BODY) for s in sels), [s for s in sels if not s.startswith("body")]
    bare = re.sub(r"/\*.*?\*/", "", R.CHROME_CSS + R.CHROME_WIDE_CSS, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?|oklch|oklab|lab|lch)\(", bare)
    for prop in ("color", "background", "border", "border-bottom", "border-top", "outline"):
        for value in re.findall(rf"[;{{]{prop}:([^;}}]+)", bare):
            # currentColor is the element's own (token) text color, e.g. the summary's caret
            assert "var(--room-" in value or "currentColor" in value or value.strip() in ("0", "none"), (prop, value)


def test_focus_styles_come_from_the_focus_token():
    rules = re.findall(r"([^{}]*:focus[^{}]*)\{([^}]*)\}", R.CHROME_CSS)
    sels = ",".join(s for s, _ in rules)
    for want in (".room__skip:focus", ".room-chrome a:focus-visible", ".room-chrome summary:focus-visible"):
        assert want in sels
    # Every focus rule that draws a ring draws it in the focus token (the skip link's own
    # :focus rule only moves it on screen).
    assert all("var(--room-focus)" in body for _, body in rules if "outline" in body)
    assert all("outline" in body or set(re.findall(r"([a-z-]+):", body)) <= {"left", "top"} for _, body in rules)


@pytest.mark.parametrize("site", PACKS)
def test_a_plain_build_carries_the_chrome_styles_and_tokens_on_the_body(site):
    css = _css(_plain(site))
    assert css.startswith(R.ROOM_CSS + R.chrome_css(K.for_site(site)))
    assert "#room-content,body.room-plain{--room-" in css


def test_the_body_follows_the_toggle_and_the_backdrop():
    gg = _css(_plain("glassgovernment"))
    assert 'body.room-plain:has(#room-content[data-room-theme="dark"]){' in gg
    assert 'body.room-plain:not(:has(#room-content[data-room-theme="light"])){' in gg
    assert "body.room-plain{background:#08090b}" in _css(_plain("deflockdane"))
    assert "body.room-plain{background:" not in _css(_plain("hrtarchive"))  # no backdrop: page-bg paints it



def _specificity(sel: str) -> tuple[int, int, int]:
    """CSS specificity (ids, classes/attributes/pseudo-classes, elements/pseudo-elements)."""
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|(?<!:):(?!:)[\w-]+", sel))
    elements = len(re.findall(r"(?:^|[\s>+~])[a-z][a-z0-9]*", sel)) + len(re.findall(r"::[\w-]+", sel))
    return ids, classes, elements


def test_on_wide_screens_the_menu_summary_hiding_rule_wins_the_cascade():
    # The review bug of 2026-10-14: `.room-chrome summary{display:flex}` outranked the
    # wide-screen `display:none`, so "Menu" stayed a full-width box above the links.
    css = re.sub(r"/\*.*?\*/", "", R.chrome_css(K.for_site("deflockdane")), flags=re.DOTALL)
    wide = css[css.index("@supports selector(::details-content)"):]
    wide = wide[:wide.index("}}") + 2]
    hide = [sel for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", wide) if "display:none" in body]
    assert len(hide) == 1 and "room-chrome__menu-label" in hide[0]
    rivals = [sel for rule, body in re.findall(r"(?:^|(?<=\}))\s*([^{}@]+)\{([^{}]*)\}", css) if "display:" in body
              for sel in rule.split(",") if re.search(r"summary(?![\w:-])|room-chrome__menu-label", sel)
              and "display:none" not in body]
    assert rivals, "expected the summary's own display rule"
    for sel in rivals:
        assert _specificity(hide[0].strip()) > _specificity(sel.strip()), (hide[0], sel)


def test_every_summary_draws_a_caret_that_turns_when_open():
    assert 'summary::after{content:"";' in R.CHROME_CSS and "details[open]>summary::after{" in R.CHROME_CSS
    assert "summary::-webkit-details-marker{display:none}" in R.CHROME_CSS


def _scheme_tokens(pack: dict) -> list[tuple[str, dict]]:
    out = [("light", pack["tokens"])]
    if pack.get("tokens_dark"):
        out.append(("dark", {**pack["tokens"], **pack["tokens_dark"]}))
    return out


def _hover_rules() -> dict[str, dict[str, str]]:
    """The button hover rules in chrome.css: which token paints what."""
    rules = {}
    for sel, body in re.findall(r"([^{}]+\.room__btn(?:--ghost)?:hover)\{([^}]*)\}", R.CHROME_CSS):
        props = dict(re.findall(r"([a-z-]+):var\(--room-([a-z-]+)\)", body))
        rules["ghost" if "--ghost" in sel else "filled"] = props
    return rules


def test_button_hover_is_drawn_from_tokens_for_every_pack():
    rules = _hover_rules()
    assert rules == {"filled": {"background": "surface", "border-color": "accent", "color": "ink"},
                     "ghost": {"background": "accent", "border-color": "accent", "color": "on-accent"}}
    for site in PACKS:  # extra_css cannot win: it is #room-content-scoped, the hover rule outranks it
        assert all(_specificity("body.room-plain #room-content .room__btn:hover") > _specificity(sel)
                   for sel in CSS.css_selectors(K.for_site(site).get("extra_css", "")) if ":hover" in sel)


@pytest.mark.parametrize("site", PACKS)
def test_button_hover_differs_visibly_and_keeps_its_label_readable(site):
    pack = K.for_site(site)
    rules = _hover_rules()
    for scheme, toks in _scheme_tokens(pack):
        page, problems = K._page_bg(toks, pack["identity"].get("backdrop", ""), scheme)
        assert not problems
        solid = {n: C.over(C.parse(toks[n]), page) for n in ("surface", "accent", "ink", "on-accent")}
        # filled: base is accent with on-accent text, on a panel; hover is the panel color with ink
        hover_bg, hover_fg = solid[rules["filled"]["background"]], solid[rules["filled"]["color"]]
        assert hover_bg != solid["accent"] and C.contrast(hover_bg, solid["accent"]) >= 3.0, (scheme, "filled")
        assert C.contrast(hover_fg, hover_bg) >= 4.5, (scheme, "filled label")
        # ghost: base is transparent (page or panel shows through); hover fills with accent
        g_bg, g_fg = solid[rules["ghost"]["background"]], solid[rules["ghost"]["color"]]
        for base in (page, solid["surface"]):
            assert C.contrast(g_bg, base) >= 3.0, (scheme, "ghost")
        assert C.contrast(g_fg, g_bg) >= 4.5, (scheme, "ghost label")


# --- every pack is pinned; nothing is captured -----------------------------------------

def test_every_pack_has_a_golden_file_and_none_is_shell_built():
    sites = {(G.CASES[c]()[0].site.template or "default") for c in G.CASES}
    assert sites == set(PACKS)
    assert not list(G.GOLDEN.glob("*-shell.json"))
    assert not (ROOMKIT / "shell.py").exists() and not (ROOMKIT / "templates" / "room" / "room-shell.js").exists()


def test_a_pack_without_chrome_draws_only_the_skip_link():
    pack = {k: v for k, v in K.for_site("default").items() if k != "chrome"}
    soup = _pages(B.render(parse(G._base()), engine=G.ENGINE, pack=pack))["index.html"]
    assert str(soup.body.select(FOCUSABLE)[0]) == '<a class="room__skip" href="#room-content">Skip to the content</a>'
    assert not soup.find(class_="room-chrome")
    # A caller that gives page_view no chrome gets the same.
    assert V.page_view("room/404.html", {}, "/r/", V.head("x", True), [])["chrome"] == V.chrome_view({})


# --- generic: no site branching ----------------------------------------------------------

def test_no_template_or_room_module_names_a_site():
    files = sorted((ROOMKIT / "templates" / "room").rglob("*")) + \
        [ROOMKIT / f for f in ("view.py", "room.py", "css.py", "build.py")]
    for f in files:
        if f.is_file():
            text = f.read_text(encoding="utf-8").lower()
            for site in SITES:
                assert site not in text, f"{f.name} names {site}"


def test_the_chrome_view_never_reads_identity():
    pack = copy.deepcopy(K.for_site("deflockdane"))
    before = V.chrome_view(pack)
    pack["identity"] = {"site": "elsewhere", "name": "Elsewhere", "base_url": "https://elsewhere.example"}
    assert V.chrome_view(pack) == before


# --- the packs' chrome and the schema -----------------------------------------------------

@pytest.mark.parametrize("site", SITES)
def test_site_chrome_is_absolute_and_says_where_it_came_from(site):
    chrome = K.for_site(site)["chrome"]
    urls = [chrome["home"]["url"]] + [ln["url"] for it in chrome["nav"] for ln in it.get("links", [it])] \
        + [ln["url"] for col in chrome.get("footer", []) for ln in col["links"]]
    assert all(u.startswith("https://") for u in urls), [u for u in urls if not u.startswith("https://")]
    src = chrome["source"]
    assert src["url"].startswith(K.for_site(site)["identity"]["base_url"] + "/") and src["date"] == "2026-10-14"


def _with_chrome(**chrome) -> dict:
    p = copy.deepcopy(K.for_site("default"))
    p["chrome"] = {"home": {"label": "Home", "url": "/"}, "skip_text": "Skip", "nav_label": "Site",
                   "menu_label": "Menu", "inline_from": "48em", **chrome}
    return p


def test_the_schema_accepts_every_chrome_field():
    p = _with_chrome(tagline="t", nav=[{"label": "A", "url": "/a/"}, {"label": "G", "links": [{"label": "B", "url": "/b/"}]}],
                     notice={"text": "n", "url": "https://x.example/"}, footer=[{"links": [{"label": "C", "url": "/c/"}]},
                     {"heading": "H", "links": [{"label": "D", "url": "/d/"}]}], footer_text=["f"],
                     source={"url": "https://x.example/", "date": "2026-10-14", "note": "n"})
    assert K.validate(p) == []


@pytest.mark.parametrize("mutate, why", [
    (lambda c: c.pop("home"), "chrome: 'home' is a required property"),
    (lambda c: c.pop("skip_text"), "chrome: 'skip_text' is a required property"),
    (lambda c: c.pop("nav_label"), "chrome: 'nav_label' is a required property"),
    (lambda c: c.pop("menu_label"), "chrome: 'menu_label' is a required property"),
    (lambda c: c.update(skip_text=""), "chrome/skip_text"),
    (lambda c: c.update(nav=[{"label": "A", "url": "/a/", "links": [{"label": "B", "url": "/b/"}]}]), "chrome/nav/0"),
    (lambda c: c.update(nav=[{"label": "A"}]), "chrome/nav/0"),
    (lambda c: c.update(nav=[{"label": "G", "links": []}]), "chrome/nav/0/links"),
    (lambda c: c.update(nav=[{"label": "G", "links": [{"label": "B", "url": "javascript:x"}]}]), "chrome/nav/0/links/0/url"),
    (lambda c: c.update(footer=[{"heading": "H", "links": []}]), "chrome/footer/0/links"),
    (lambda c: c.update(footer_text=[""]), "chrome/footer_text/0"),
    (lambda c: c.update(source={"url": "http://x.example/", "date": "2026-10-14"}), "chrome/source/url"),
    (lambda c: c.update(source={"url": "https://x.example/", "date": "14 Oct 2026"}), "chrome/source/date"),
    (lambda c: c.update(logo="x.svg"), "chrome: Additional properties are not allowed ('logo'"),
])
def test_the_schema_refuses_bad_chrome(mutate, why):
    p = _with_chrome()
    mutate(p["chrome"])
    problems = K.validate(p)
    assert any(why in x for x in problems), problems


def test_a_backdrop_cannot_break_out_of_its_css_rule():
    p = copy.deepcopy(K.for_site("deflockdane"))
    p["identity"]["backdrop"] = "#000}body{display:none"
    assert any("identity/backdrop" in x for x in K.validate(p))


# --- in a browser (skipped where Playwright's Chromium is not installed) --------------

def test_in_a_browser_the_menu_is_inline_wide_and_folded_narrow(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    B.write(_plain("deflockdane"), tmp_path / "reading-room")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/reading-room/"
    chrome = K.for_site("deflockdane")["chrome"]
    top = [it["label"] for it in chrome["nav"] if "url" in it]
    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"Playwright Chromium not installed: {e}")
            nav = "header nav.room-chrome__nav"
            wide = b.new_context(viewport={"width": 1280, "height": 900}, java_script_enabled=False).new_page()
            wide.goto(url)
            assert not wide.locator("summary.room-chrome__menu-label").is_visible()
            for label in top:
                assert wide.locator(nav).get_by_role("link", name=label, exact=True).is_visible()
            assert wide.locator(f"{nav} summary", has_text="Maps").is_visible()
            wide.locator(f"{nav} summary", has_text="Maps").click()
            assert wide.locator(nav).get_by_role("link", name="Statewide ALPR Map").is_visible()
            # hover changes the button (JS on: the finder's buttons are shown by room.js)
            js = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
            js.goto(url)
            btn = js.locator("#room-content .room__btn[type=submit]")
            before = btn.evaluate("e => getComputedStyle(e).backgroundColor")
            btn.hover()
            assert btn.evaluate("e => getComputedStyle(e).backgroundColor") != before
            narrow = b.new_context(viewport={"width": 375, "height": 812}, java_script_enabled=False).new_page()
            narrow.goto(url)
            menu = narrow.locator("summary.room-chrome__menu-label")
            assert menu.is_visible()
            assert not narrow.locator(nav).get_by_role("link", name=top[0], exact=True).is_visible()
            menu.click()
            assert narrow.locator(nav).get_by_role("link", name=top[0], exact=True).is_visible()
            b.close()
    finally:
        srv.shutdown()


# The widths the polish audit of 2026-10-14 walked, and the tallest header allowed at any
# of them: one row of brand and links (about 70px), a phone's brand with a wrapped tagline
# beside the Menu button (about 93px), or at 320px a site name too long to share its one
# line with the Menu button, which then takes a second row (101px for GG and hrtarchive).
AUDIT_WIDTHS = (320, 375, 768, 900, 1024, 1280, 1440)
HEADER_MAX = 110

_GEOMETRY = """() => {
  const hd = document.querySelector('header.room-chrome');
  const nav = hd.querySelector('nav');
  const tops = [...nav.querySelectorAll('.room-chrome__links > li')].filter(l => l.checkVisibility())
    .map(l => l.getBoundingClientRect().top);
  return {styled: getComputedStyle(document.body).margin === '0px', height: hd.getBoundingClientRect().height,
          // line boxes of the site name's text (the link itself is a flex item, so one box)
          nameLines: (() => { const r = document.createRange(); r.selectNodeContents(hd.querySelector('.room-chrome__home'));
                              return new Set([...r.getClientRects()].map(x => Math.round(x.top))).size; })(),
          menu: nav.querySelector('summary.room-chrome__menu-label').checkVisibility(), tops,
          // the page column is .room__shell: the brand starts on its left edge and nothing in the
          // header's row reaches past its right edge
          brandLeft: hd.querySelector('.room-chrome__home').getBoundingClientRect().left,
          mainLeft: document.querySelector('main .room__shell').getBoundingClientRect().left,
          mainRight: document.querySelector('main .room__shell').getBoundingClientRect().right,
          headRight: Math.max(...[...hd.querySelectorAll('.room-chrome__bar > *')].map(e => e.getBoundingClientRect().right))};
}"""

_DROPDOWNS = """() => {
  if (getComputedStyle(document.body).margin !== '0px') return null;  // room.css did not load
  const bar = document.querySelector('header.room-chrome .room-chrome__bar');
  const r = bar.getBoundingClientRect(), cs = getComputedStyle(bar);
  const box = [r.left + parseFloat(cs.paddingLeft), r.right - parseFloat(cs.paddingRight)];
  return [...bar.querySelectorAll('.room-chrome__group > details')].map(d => {
    d.open = true;
    const u = d.querySelector('ul').getBoundingClientRect();
    d.open = false;
    return {label: d.querySelector('summary').textContent, left: u.left, right: u.right, box};
  });
}"""


@pytest.fixture(scope="module")
def browser_rooms(tmp_path_factory):
    """Every pack's plain room served on 127.0.0.1, and a Chromium; skipped without one."""
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path_factory.mktemp("rooms")
    for site in PACKS:
        B.write(_plain(site, mount=f"/{site}/reading-room/"), root / site / "reading-room")
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
        yield b, {site: f"{base}/{site}/reading-room/" for site in PACKS}
        b.close()
    srv.shutdown()


@pytest.mark.parametrize("site", PACKS)
def test_in_a_browser_the_header_is_the_menu_or_one_row_and_stays_compact(browser_rooms, site):
    b, urls = browser_rooms
    for width in AUDIT_WIDTHS:
        page = b.new_page(viewport={"width": width, "height": 900})
        page.goto(urls[site])
        g = page.evaluate(_GEOMETRY)
        page.close()
        assert g["styled"], (site, width, "room.css did not load")
        assert g["nameLines"] == 1, (site, width, "the site name wraps")
        if g["menu"]:
            assert g["tops"] == [], (site, width, "links show beside the Menu button")
        else:
            assert g["tops"] and max(g["tops"]) - min(g["tops"]) <= 2, (site, width, "links wrap", g["tops"])
        assert g["height"] <= HEADER_MAX, (site, width, g["height"])
        assert abs(g["brandLeft"] - g["mainLeft"]) <= 1, (site, width, "brand is off the page column", g)
        assert g["headRight"] <= g["mainRight"] + 1, (site, width, "header reaches past the page column", g)


@pytest.mark.parametrize("width", [1024, 1280])
def test_in_a_browser_open_dropdowns_stay_inside_the_header_content_box(browser_rooms, width):
    b, urls = browser_rooms
    checked = 0
    for site in PACKS:
        page = b.new_page(viewport={"width": width, "height": 900})
        page.goto(urls[site])
        drops = page.evaluate(_DROPDOWNS)
        assert drops is not None, (site, width, "room.css did not load")
        for d in drops:
            left, right = d["box"]
            assert d["right"] <= right + 0.5 and d["left"] >= left - 0.5, (site, width, d)
            checked += 1
        page.close()
    assert checked >= 2  # dd's Maps and Open Records


def test_the_inline_width_is_written_into_the_media_query_from_the_pack():
    for site in PACKS:
        pack = K.for_site(site)
        css = R.chrome_css(pack)
        assert f"@media (min-width:{pack['chrome']['inline_from']}){{" in css
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        assert bare.count("@media (min-width:") == 1 and R.CHROME_WIDE_CSS in css
    pack = copy.deepcopy(K.for_site("default"))
    for bad in ("56", "900px", "56em}body{x:y", "var(--w)", ""):
        pack["chrome"]["inline_from"] = bad
        assert any("chrome/inline_from" in x for x in K.validate(pack)), bad
    del pack["chrome"]["inline_from"]
    assert any("'inline_from' is a required property" in x for x in K.validate(pack))


# --- count nouns: required labels, never a built plural ------------------------------------

@pytest.mark.parametrize("label", ["group", "group_singular", "groups_plural", "record_singular", "record_plural"])
def test_a_pack_without_a_count_noun_is_refused(label):
    pack = copy.deepcopy(K.for_site("deflockdane"))
    del pack["labels"][label]
    assert f"labels: '{label}' is a required property" in K.validate(pack)
    pack.pop("labels")
    assert "(pack): 'labels' is a required property" in K.validate(pack)


def _index_soup(n_groups: int, n_docs: int, pack: dict | None = None) -> BeautifulSoup:
    m = G._base()
    proto = m["documents"][1]
    m["documents"] = [dict(copy.deepcopy(proto), slug=f"d-{i}", title=f"D {i}",
                           index={"group": f"Group {i % n_groups}"}) for i in range(n_docs)]
    m["site"]["index"]["groups"] = []
    html = B.render(parse(m), engine=G.ENGINE, pack=pack or K.for_site("hrtarchive"))["index.html"]
    return BeautifulSoup(html.decode(), "html.parser")


def test_a_count_of_one_takes_the_singular_and_more_the_plural():
    one = _index_soup(1, 1)
    stats = [li.get_text(" ", strip=True) for li in one.select(".room__stats li")]
    assert stats[:2] == ["1 record", "1 agency"]
    assert one.select_one("[data-room-count]").get_text() == "1 record"
    many = _index_soup(4, 5)
    stats = [li.get_text(" ", strip=True) for li in many.select(".room__stats li")]
    assert stats[:2] == ["5 records", "4 agencies"]
    assert many.select_one("[data-room-count]").get_text() == "5 records"


def test_the_header_count_may_name_records_apart_from_the_result_count():
    # GG's header says "455 documents" over a result count of "455 records".
    pack = copy.deepcopy(K.for_site("hrtarchive"))
    pack["labels"].update(stats_singular="document", stats_plural="documents")
    assert K.validate(pack) == []
    for n, noun in ((1, "document"), (5, "documents")):
        soup = _index_soup(1, n, pack)
        assert soup.select(".room__stats li")[0].get_text(" ", strip=True) == f"{n} {noun}"
        assert soup.select_one("[data-room-count]").get_text() == f"{n} record{'s' * (n != 1)}"


def test_no_template_view_or_room_script_builds_a_plural():
    view = (ROOMKIT / "view.py").read_text(encoding="utf-8")
    assert not re.search(r'\+\s*"s"', view)
    assert not re.search(r'"s"\)|\? ""', R.ROOM_JS) and 'getAttribute(total === 1 ? "data-room-one"' in R.ROOM_JS
    for f in (ROOMKIT / "templates" / "room").glob("*.html"):
        assert not re.search(r"\}s\{%|%\}s\{%|endif %\}s|\{% if [^%]*!= 1 %\}s", f.read_text(encoding="utf-8")), f.name


# --- the jump nav is named by its visible label (WCAG 2.5.3) -------------------------------

def _jump_visible(soup: BeautifulSoup) -> str:
    nav = soup.select_one("nav.room__jump")
    head = nav.select_one(".room__jump-label") or nav.select_one("summary")
    return re.sub(r"\s*\(\d+\)$", "", head.get_text())  # a folded list's summary adds the count


@pytest.mark.parametrize("site", PACKS)
def test_the_jump_nav_is_named_by_its_visible_label(site):
    soup = _pages(_plain(site))["index.html"]
    visible = _jump_visible(soup)
    assert visible == K.for_site(site)["labels"]["jump"]
    assert soup.select_one("nav.room__jump")["aria-label"] == visible.rstrip(" :;,.!?…–—")


def test_no_room_text_takes_the_group_noun_from_the_manifest():
    m = G._base()
    m["site"]["index"]["group_label"] = "Zebra"
    html = B.render(parse(m), engine=G.ENGINE, pack=K.for_site("default"))["index.html"].decode()
    assert "zebra" not in html.lower()


def test_a_pack_without_a_jump_label_is_refused():
    pack = copy.deepcopy(K.for_site("glassgovernment"))
    del pack["labels"]["jump"]
    assert "labels: 'jump' is a required property" in K.validate(pack)


@pytest.mark.parametrize("site", PACKS)
def test_in_a_browser_the_jump_nav_accessible_name_matches_its_heading(browser_rooms, site):
    b, urls = browser_rooms
    page = b.new_page(viewport={"width": 1280, "height": 900})
    page.goto(urls[site])
    visible = page.locator("nav.room__jump .room__jump-label, nav.room__jump summary").first.text_content()
    name = re.sub(r"\s*\(\d+\)$", "", visible).rstrip(" :;,.!?…–—")
    # get_by_role matches on the computed accessible name
    assert page.get_by_role("navigation", name=name, exact=True).count() == 1, (site, name)
    page.close()


def test_the_count_nouns_reach_the_live_count():
    soup = _pages(_plain("deflockdane"))["index.html"]
    count = soup.select_one("[data-room-count]")
    assert (count["data-room-one"], count["data-room-other"]) == ("record", "records")
    files = _plain("deflockdane")
    assert files[B.published(files, "assets/room.js")].decode() == R.ROOM_JS


def test_the_retired_shell_only_label_is_refused():
    pack = copy.deepcopy(K.for_site("deflockdane"))
    pack["labels"]["shell_jump"] = "Jump to jurisdiction:"
    assert any("Additional properties are not allowed ('shell_jump'" in x for x in K.validate(pack))


def test_in_a_browser_the_finder_count_uses_the_pack_nouns(browser_rooms, tmp_path):
    b, _ = browser_rooms
    pack = copy.deepcopy(K.for_site("hrtarchive"))
    pack["labels"].update(record_singular="page", record_plural="pages")
    B.write(B.render(parse(G._base()), engine=G.ENGINE, pack=pack), tmp_path / "reading-room")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        page = b.new_page()
        page.goto(f"http://127.0.0.1:{srv.server_address[1]}/reading-room/")
        count = page.locator("[data-room-count]")
        page.locator("#room-q").fill("memo")
        page.locator("#room-q").press("Enter")
        page.wait_for_function("() => / match$/.test(document.querySelector('[data-room-count]').textContent)")
        assert re.fullmatch(r"\d+ of 5 pages match", count.text_content()), count.text_content()
        page.close()
    finally:
        srv.shutdown()


@pytest.mark.parametrize("site", PACKS)
def test_a_folded_jump_count_follows_the_label_without_its_punctuation(site):
    m = G._base()
    if site != "default":
        m["site"]["template"] = site
    proto = m["documents"][1]
    m["documents"] += [dict(copy.deepcopy(proto), slug=f"g-{i}", title=f"G {i}", index={"group": f"Group {i}"})
                       for i in range(14)]
    pack = K.for_site(site)
    files = B.render(parse(m), engine=G.ENGINE, pack=pack)
    soup = BeautifulSoup(files["index.html"].decode(), "html.parser")
    summary = soup.select_one("nav.room__jump summary").get_text()
    assert re.fullmatch(r".*[^ :;,.!?\u2026\u2013\u2014] \(\d+\)", summary), summary
    assert summary.startswith(pack["labels"]["jump"].rstrip(" :;,.!?\u2026\u2013\u2014") + " (")
    # Every "label (N)" the room composes sits in a nav or a summary; none has punctuation before the count.
    for page in _pages(files).values():
        for el in page.select("nav, summary"):
            assert not re.search(r"[:;,.!?\u2026\u2013\u2014]\s*\(\d+\)", el.get_text()), (site, el.get_text()[:80])

