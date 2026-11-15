"""Facet pages, the sitemap and their parity checks (roomkit/browse.py,
browse_parity.py; matrix rows index-facet-pages and sitemaps)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from roomkit import browse as BR
from roomkit import build as B
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
    m["site"]["template"] = "example"
    if browse:
        m["site"]["index"]["browse"] = copy.deepcopy(BROWSE)
        for d in m["documents"]:
            if d["slug"] in MEMBERS:
                d.setdefault("index", {})["browse"] = copy.deepcopy(MEMBERS[d["slug"]])
    return m


def _pack(facets: bool = True, sitemaps: bool = True) -> dict:
    p = copy.deepcopy(B.pack_for_site("example"))
    p["features"] = {**p.get("features", {}), "facet-pages": facets, "sitemaps": sitemaps}
    return p


def _render(raw: dict | None = None, **kw) -> dict[str, bytes]:
    pk = kw.pop("pack", None) or _pack()
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, indexer=S.stand_in, pack=pk, **kw)


# --- the switches --------------------------------------------------------------

def test_switches_off_build_exactly_the_room_without_a_browse_block():
    off = _pack(facets=False, sitemaps=False)
    assert _render(pack=off) == _render(_raw(browse=False), pack=off)


def test_facet_pages_on_without_a_browse_block_builds_none():
    files = _render(_raw(browse=False), pack=_pack(sitemaps=False))
    assert not [p for p in files if p.startswith(("agency/", "vendor/", "year/"))]
    assert b"data-room-browse" not in files["index.html"]
    assert R.BROWSE_CSS.encode() not in files[B.published(files, "assets/room.css")]


def test_each_facet_root_is_a_page_listing_its_values_and_stays_out_of_the_sitemap():
    files = _render()
    html = files["vendor/index.html"].decode()
    assert 'data-room-facet-root="vendor"' in html
    assert 'href="/reading-room/vendor/flock-safety/"' in html and 'href="/reading-room/vendor/axon/"' in html
    assert '<html lang=' in html
    assert b"/vendor/</loc>" not in files["sitemap.xml"]


@pytest.mark.parametrize("width", (320, 375))
def test_in_a_browser_a_one_word_value_wraps_on_a_narrow_screen(tmp_path, width):
    # site A's type root has "contractutilizationquarterlyactivityreports", one word
    # that pushed /library/type/ 40px past a 375px screen (sweep 2026-10-27).
    sync_api = pytest.importorskip("playwright.sync_api")
    raw = _raw()
    for d in raw["documents"]:
        if d["slug"] == "big-report":
            d["index"]["browse"]["vendor"] = ["contractutilizationquarterlyactivityreports"]
    files = _render(raw)
    html = files["vendor/index.html"].decode()
    assert "contractutilizationquarterlyactivityreports" in html
    css = b"".join(v for p, v in files.items() if p.startswith("assets/") and p.endswith(".css")).decode()
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Playwright Chromium not installed: {e}")
        page = b.new_page(viewport={"width": width, "height": 800})
        page.set_content(re.sub(r'<link rel="stylesheet"[^>]*>', "", html).replace("</head>", f"<style>{css}</style></head>"))
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        b.close()


def test_one_page_per_value_at_its_path_with_its_records_in_manifest_order():
    files = _render()
    pages = sorted(p for p in files if p.startswith(("agency/", "vendor/", "year/")) and p.count("/") == 2)
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
    {"heading": "x", "facets": [{"name": "a", "label": "A", "title": "{value}", "room_only": "yes"}]},
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


def test_sitemap_escapes_and_is_off_without_its_switch():
    assert BR.SITEMAP not in _render(pack=_pack(sitemaps=False))
    assert "&amp;" in BR.sitemap_xml(["https://example.test/a?b=1&c=2"])


def _with_status(raw: dict | None = None) -> dict:
    """site B's status facet: the room's own (room_only), with a badge on each card."""
    raw = raw or _raw()
    raw["site"]["index"]["browse"]["facets"].append(
        {"name": "status", "label": "Status", "title": "Status: {value}", "room_only": True})
    for d in raw["documents"]:
        if d["slug"] in MEMBERS:
            st = "Past" if d["slug"] == "site-photo" else "Current"
            d["index"]["browse"]["status"] = [st]
            d["index"].update(badge=st, badge_kind=st.lower(), badge_sr="Status: ")
    return raw


def test_a_card_shows_its_badge_on_the_index_and_its_facet_pages():
    files = _render(_with_status())
    card = ('<p class="room__card-meta"><span class="room__badge room__badge--current">'
            '<span class="room__sr">Status: </span>Current</span> Contract &middot; 12 pages</p>')
    assert card in files["index.html"].decode() and card in files["status/current/index.html"].decode()
    # The badge is in the card's filter text, so typing "past" finds the past record.
    assert re.search(r'data-room-text="[^"]*\bpast\b[^"]*" data-room-group="Test Agency"', files["index.html"].decode())
    # A row without one draws as before.
    assert b"room__badge" not in _render(_raw())["index.html"]


@pytest.mark.parametrize("bad, says", [
    ({"badge": 1}, "index.badge and index.badge_sr are not strings"),
    ({"badge": "Current", "badge_kind": "Not A Slug"}, "index.badge_kind is not a slug"),
    ({"sort_title": 1}, "index.sort_title is not a string"),
])
def test_a_card_badge_that_is_not_text_is_refused(bad, says):
    raw = _raw()
    raw["documents"][0]["index"].update(bad)
    assert parse(raw).refusals[0][1] == says


# --- features.csp (build.CSP) --------------------------------------------------

def test_csp_header_only_when_the_pack_turns_it_on():
    off = _render()[B.HTACCESS].decode()
    assert "Content-Security-Policy" not in off
    pk = _pack()
    pk["features"]["csp"] = True
    on = _render(pack=pk)[B.HTACCESS].decode()
    assert f'Header always set Content-Security-Policy "{B.CSP}"' in on
    # The room's scripts are external files, so the policy never allows inline ones or eval.
    assert "script-src 'self' 'wasm-unsafe-eval';" in B.CSP
    assert "unsafe-eval" not in B.CSP.replace("wasm-unsafe-eval", "")
    assert "script-src 'self' 'unsafe-inline'" not in B.CSP
    assert "frame-ancestors 'self'" in B.CSP
