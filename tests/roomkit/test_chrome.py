"""The room's own header, navigation and footer.

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
from tests.roomkit.shipped import PACKS, SITE_PACKS

SITES = SITE_PACKS
ROOMKIT = Path(R.__file__).resolve().parent
FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex='-1'])"


def _plain(site: str, mount: str | None = None) -> dict[str, bytes]:
    """The golden manifest built in `site`'s pack."""
    m = G._base()
    if site != "default":
        m["site"]["template"] = site
    return B.render(parse(m), engine=G.ENGINE, pack=B.pack_for_site(site), mount=mount)


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
        assert navs[0]["aria-label"] == B.pack_for_site(site)["chrome"]["nav_label"], path


@pytest.mark.parametrize("site", PACKS)
def test_the_skip_link_is_first_and_targets_the_content(site):
    chrome = B.pack_for_site(site)["chrome"]
    for path, soup in _pages(_plain(site)).items():
        first = soup.body.select(FOCUSABLE)[0]
        assert first.name == "a" and first["href"] == "#room-content", path
        assert first.get_text() == chrome["skip_text"], path
        assert soup.find(id="room-content").name == "main"


@pytest.mark.parametrize("site", PACKS)
def test_the_menu_is_a_details_summary_holding_every_link(site):
    chrome = B.pack_for_site(site)["chrome"]
    soup = _pages(_plain(site))["index.html"]
    nav = _site_nav(soup)[0]
    menu = nav.find("details", recursive=False)
    assert menu is not None and menu.find("summary", recursive=False).get_text() == chrome["menu_label"]
    want = [(ln["label"], ln["url"]) for it in chrome["nav"] for ln in it.get("links", [it])]
    assert [(a.get_text(), a["href"]) for a in menu.find_all("a")] == want
    groups = [it["label"] for it in chrome["nav"] if "links" in it]
    assert [d.summary.get_text() for d in menu.find_all("details")] == groups
    assert not soup.find_all("script", src=re.compile("chrome"))  # no JavaScript for the menu


def test_a_notice_renders_under_the_header_and_text_is_escaped():
    pack = copy.deepcopy(B.pack_for_site("default"))
    pack["chrome"]["notice"] = {"text": "Moved <here> & there", "url": "/news/"}
    pack["chrome"]["home"]["label"] = 'A "quoted" <b>name</b>'
    html = B.render(parse(G._base()), engine=G.ENGINE, pack=pack)["index.html"].decode()
    assert '<p class="room-chrome__notice"><a href="/news/">Moved &lt;here&gt; &amp; there</a></p>' in html
    assert ">A &quot;quoted&quot; &lt;b&gt;name&lt;/b&gt;</a>" in html


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
    # A mapped theme's @font-face rules come first (build._fonts_css), one a line.
    faces = re.match(r"(?:@font-face\{[^\n]*\}\n)*", css).group(0)
    assert faces.count("@font-face") == len(B.pack_for_site(site).get("fonts", []))
    assert css[len(faces):].startswith(R.ROOM_CSS + R.chrome_css(B.pack_for_site(site)))
    assert "#room-content,body.room-plain{--room-" in css


def _specificity(sel: str) -> tuple[int, int, int]:
    """CSS specificity (ids, classes/attributes/pseudo-classes, elements/pseudo-elements)."""
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|(?<!:):(?!:)[\w-]+", sel))
    elements = len(re.findall(r"(?:^|[\s>+~])[a-z][a-z0-9]*", sel)) + len(re.findall(r"::[\w-]+", sel))
    return ids, classes, elements


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
                   for sel in CSS.css_selectors(B.pack_for_site(site).get("extra_css", "")) if ":hover" in sel)


@pytest.mark.parametrize("site", PACKS)
def test_button_hover_differs_visibly_and_keeps_its_label_readable(site):
    pack = B.pack_for_site(site)
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
    assert sites == set(PACKS) - set(SITE_PACKS)  # the sites' packs: sites/test_core_cases_on_sites.py
    assert not list(G.GOLDEN.glob("*-shell.json"))
    assert not (ROOMKIT / "shell.py").exists() and not (ROOMKIT / "templates" / "room" / "room-shell.js").exists()


def test_a_pack_without_chrome_draws_only_the_skip_link():
    pack = {k: v for k, v in B.pack_for_site("default").items() if k != "chrome"}
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


def _with_chrome(**chrome) -> dict:
    p = copy.deepcopy(B.pack_for_site("default"))
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


# The widths the polish audit of 2026-10-14 walked, and the tallest header allowed at any
# of them: one row of brand and links (about 70px), a phone's brand with a wrapped tagline
# beside the Menu button (about 93px), or at 320px a site name too long to share its one
# line with the Menu button, which then takes a second row (101px for the two longest site names).
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
        overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        page.close()
        assert g["styled"], (site, width, "room.css did not load")
        assert overflow <= 0, (site, width, "the page scrolls sideways", overflow)
        if B.pack_for_site(site).get("theme"):
            # A mapped theme draws the site's own header (theme_map.py): a logo, links that wrap
            # into rows beside it, the row wider than the page column, as WordPress draws it.
            # Its look is held by parity.style against the reference capture, not by these rules.
            assert g["menu"] or g["tops"], (site, width, "neither the links nor the Menu show")
            continue
        assert g["nameLines"] == 1, (site, width, "the site name wraps")
        if g["menu"]:
            assert g["tops"] == [], (site, width, "links show beside the Menu button")
        else:
            assert g["tops"] and max(g["tops"]) - min(g["tops"]) <= 2, (site, width, "links wrap", g["tops"])
        assert g["height"] <= HEADER_MAX, (site, width, g["height"])
        assert abs(g["brandLeft"] - g["mainLeft"]) <= 1, (site, width, "brand is off the page column", g)
        assert g["headRight"] <= g["mainRight"] + 1, (site, width, "header reaches past the page column", g)


def test_the_inline_width_is_written_into_the_media_query_from_the_pack():
    for site in PACKS:
        pack = B.pack_for_site(site)
        css = R.chrome_css(pack)
        assert f"@media (min-width:{pack['chrome']['inline_from']}){{" in css
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        assert bare.count("@media (min-width:") == 1 and R.CHROME_WIDE_CSS in css
    pack = copy.deepcopy(B.pack_for_site("default"))
    for bad in ("56", "900px", "56em}body{x:y", "var(--w)", ""):
        pack["chrome"]["inline_from"] = bad
        assert any("chrome/inline_from" in x for x in K.validate(pack)), bad
    del pack["chrome"]["inline_from"]
    assert any("'inline_from' is a required property" in x for x in K.validate(pack))


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
    assert visible == B.pack_for_site(site)["labels"]["jump"]
    assert soup.select_one("nav.room__jump")["aria-label"] == visible.rstrip(" :;,.!?…–—")


def test_no_room_text_takes_the_group_noun_from_the_manifest():
    m = G._base()
    m["site"]["index"]["group_label"] = "Zebra"
    html = B.render(parse(m), engine=G.ENGINE, pack=B.pack_for_site("default"))["index.html"].decode()
    assert "zebra" not in html.lower()


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


@pytest.mark.parametrize("site", PACKS)
def test_a_folded_jump_count_follows_the_label_without_its_punctuation(site):
    m = G._base()
    if site != "default":
        m["site"]["template"] = site
    proto = m["documents"][1]
    m["documents"] += [dict(copy.deepcopy(proto), slug=f"g-{i}", title=f"G {i}", index={"group": f"Group {i}"})
                       for i in range(14)]
    pack = B.pack_for_site(site)
    files = B.render(parse(m), engine=G.ENGINE, pack=pack)
    soup = BeautifulSoup(files["index.html"].decode(), "html.parser")
    summary = soup.select_one("nav.room__jump summary").get_text()
    assert re.fullmatch(r".*[^ :;,.!?\u2026\u2013\u2014] \(\d+\)", summary), summary
    assert summary.startswith(pack["labels"]["jump"].rstrip(" :;,.!?\u2026\u2013\u2014") + " (")
    # Every "label (N)" the room composes sits in a nav or a summary; none has punctuation before the count.
    for page in _pages(files).values():
        for el in page.select("nav, summary"):
            assert not re.search(r"[:;,.!?\u2026\u2013\u2014]\s*\(\d+\)", el.get_text()), (site, el.get_text()[:80])
