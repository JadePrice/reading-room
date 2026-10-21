"""roomkit server search (pack features.server-search): the site's own search for
readers without JavaScript, rendered as the GET form its server answers today
(manifest site.index.server_search; a topic page's search.param). The room
answers nothing: the form goes to the site's live URL with the site's parameter,
from any mount.

The live forms these stand for: GG templates/index-ggrr-reading-room.php
(.ggrr-rr-nojs-form, name="q") and archive-ggrr-topic.php (.ggrr-search-form,
name="s"); dd class-deflock-reading-room-shortcode.php (name="rr_search").
"""

from __future__ import annotations

import copy
import functools
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from roomkit import build as B
from roomkit import pack as K
from roomkit import search as S
from roomkit.manifest import ManifestError, parse
from tests.roomkit import test_topics as T

SS = {"action": T.ROOM, "param": "q", "label": "Search records",
      "placeholder": "Search by title, agency, collection, or type…", "button": "Search"}


def _raw(ss: dict | None = SS, topic_param: str | None = "s") -> dict:
    m = T._raw()
    if ss is not None:
        m["site"].setdefault("index", {})["server_search"] = ss
    for p in m["topics"]["pages"]:
        if "search" in p and topic_param:
            p["search"]["param"] = topic_param
    return m


def _pack(on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site("glassgovernment"))
    p["features"] = {**p.get("features", {}), "topics": True, "server-search": on}
    return p


def _render(on: bool = True, raw: dict | None = None, **kw) -> dict[str, bytes]:
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=T.ENGINE, indexer=S.stand_in, pack=_pack(on), **kw)


def _forms(b: bytes) -> list[str]:
    return re.findall(r"<form\b[^>]*>.*?</form>", b.decode(), re.DOTALL)


# --- the switch -------------------------------------------------------------------------

def test_switch_off_builds_exactly_the_room_without_the_block():
    assert _render(False) == _render(False, _raw(ss=None, topic_param=None))


def test_switch_on_without_a_block_renders_no_server_form():
    files = _render(True, _raw(ss=None, topic_param=None))
    assert all("room__search--server" not in b.decode() for p, b in files.items() if p.endswith(".html"))


# --- the index ---------------------------------------------------------------------------

def test_the_index_carries_the_sites_form_in_a_noscript():
    page = _render()["index.html"].decode()
    block = re.search(r"<noscript><form class=\"room__search room__search--server\"(.*?)</form></noscript>", page, re.DOTALL)
    assert block, "no <noscript> server form on the index"
    f = block.group(0)
    assert f'action="{T.ROOM}"' in f and 'method="get"' in f and 'role="search"' in f
    assert '<label for="room-nojs-q">Search records</label>' in f and 'id="room-nojs-q" name="q"' in f
    assert 'placeholder="Search by title, agency, collection, or type…"' in f and ">Search</button>" in f
    # The JavaScript finder is untouched: still hidden until a script shows it.
    assert re.search(r'<section class="room__finder"[^>]*\bhidden>', page)


def test_a_staging_mount_still_sends_the_query_to_the_live_url():
    page = _render(mount="/rr-staging/", noindex=True)["index.html"].decode()
    assert f'<noscript><form class="room__search room__search--server" role="search" action="{T.ROOM}"' in page


def test_the_words_are_escaped():
    page = _render(raw=_raw({**SS, "label": "Search <records> & more"}))["index.html"].decode()
    assert "Search &lt;records&gt; &amp; more" in page and "<records>" not in page


@pytest.mark.parametrize("ss, why", [
    ({**SS, "action": "https://elsewhere.test/library/"}, "is not a URL on"),
    ({**SS, "action": T.ROOM + "?x=1"}, "without a query"),
    ({**SS, "action": "javascript:alert(1)"}, "is not a URL on"),
    ({**SS, "param": "Q"}, "lowercase query name"),
    ({**SS, "param": "q&x"}, "lowercase query name"),
    ({k: v for k, v in SS.items() if k != "button"}, "every one a non-empty string"),
    ({**SS, "extra": "x"}, "every one a non-empty string"),
    ({**SS, "label": ""}, "every one a non-empty string"),
])
def test_a_bad_block_is_refused_and_named(ss, why):
    with pytest.raises(ManifestError, match=re.escape("site.index.server_search")) as e:
        parse(_raw(ss))
    assert why in str(e.value)


# --- topic pages ---------------------------------------------------------------------------

def test_a_paged_topic_carries_the_sites_filter_to_page_one_from_every_page():
    files = _render(mount="/rr-staging/", noindex=True)
    for path in ("topics/historical/index.html", "topics/historical/page/3/index.html"):
        (f,) = [x for x in _forms(files[path]) if "room__tsearch" in x]
        assert f'action="{T.ROOM}topics/historical/"' in f and 'method="get"' in f
        assert '<label for="room-tq">Filter documents</label>' in f and 'name="s"' in f
        assert 'placeholder="Filter within this topic…"' in f


def test_a_single_page_topic_still_has_no_filter():
    assert "room__tsearch" not in _render()["topics/fbi-diog/index.html"].decode()


def test_no_param_or_switch_off_means_no_topic_filter():
    assert "room__tsearch" not in _render(raw=_raw(topic_param=None))["topics/historical/index.html"].decode()
    assert "room__tsearch" not in _render(False)["topics/historical/index.html"].decode()


def test_a_bad_topic_param_is_refused():
    why = [w for where, w in parse(_raw(topic_param="s&x")).refusals if where == "topics"]
    assert why and "lowercase query name" in why[0]


# --- the exporters say what the live forms send ----------------------------------------------

def test_the_exporters_send_each_sites_own_parameter_to_its_own_url():
    gg = (T.EXPORTERS / "glassgovernment.php").read_text(encoding="utf-8")
    assert "'server_search' => ['action' => home_url('/library/'), 'param' => 'q'" in gg
    assert "'placeholder' => 'Filter within this topic…', 'param' => 's'" in gg
    dd = (T.EXPORTERS / "deflockdane.php").read_text(encoding="utf-8")
    assert "'server_search' => ['action' => home_url('/reading-room/'), 'param' => 'rr_search'" in dd


def test_only_gg_and_dd_turn_server_search_on():
    on = {s for s in ("default", "glassgovernment", "deflockdane", "hrtarchive") if K.for_site(s).get("features", {}).get("server-search")}
    assert on == {"glassgovernment", "deflockdane"}


# --- in a browser, JavaScript off --------------------------------------------------------------

@pytest.fixture(scope="module")
def nojs_room(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path_factory.mktemp("server-search-room")
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


@pytest.mark.parametrize("path, field, want", [
    ("/library/", "#room-nojs-q", T.ROOM + "?q=camera+contract"),
    ("/library/topics/historical/page/2/", "#room-tq", T.ROOM + "topics/historical/?s=camera+contract"),
])
def test_in_a_browser_without_javascript_the_form_submits_to_the_site(nojs_room, path, field, want):
    b, base = nojs_room
    ctx = b.new_context(viewport={"width": 375, "height": 812}, java_script_enabled=False)
    sent = []
    ctx.route(T.SITE + "/**", lambda route: (sent.append(route.request.url),
                                              route.fulfill(status=200, body="answered", content_type="text/plain")))
    page = ctx.new_page()
    page.goto(base + path)
    box = page.locator(field)
    assert box.is_visible()
    box.fill("camera contract")
    box.press("Enter")
    page.wait_for_url(want)
    assert sent == [want]
    ctx.close()


def test_in_a_browser_with_javascript_the_noscript_form_is_not_shown(nojs_room):
    b, base = nojs_room
    page = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    page.goto(base + "/library/")
    assert page.locator("#room-nojs-q").count() == 0 or not page.locator("#room-nojs-q").is_visible()
    page.close()


def _as_without_javascript(route):
    # What a browser without JavaScript renders: no scripts, <noscript> content shown.
    # (axe itself needs script, so the page is rewritten instead of JS being off.)
    body = route.fetch().text()
    body = re.sub(r"<script\b(?![^>]*application/(?:ld\+)?json)[^>]*>.*?</script>", "", body, flags=re.DOTALL)
    route.fulfill(status=200, body=body.replace("<noscript>", "<div>").replace("</noscript>", "</div>"),
                  content_type="text/html; charset=utf-8")


@pytest.mark.parametrize("js", (True, False))
def test_in_a_browser_the_forms_pass_axe(nojs_room, js):
    from tests.reading_room_reader.conftest import axe_source
    b, base = nojs_room
    for path in ("/library/", "/library/topics/historical/"):
        ctx = b.new_context(viewport={"width": 375, "height": 812})
        if not js:
            ctx.route(base + path, _as_without_javascript)
        page = ctx.new_page()
        page.goto(base + path)
        if not js and path == "/library/":
            assert page.locator("#room-nojs-q").is_visible()
        page.evaluate(axe_source())
        assert page.evaluate(T.AXE) == [], (path, js)
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), path
        ctx.close()
