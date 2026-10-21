"""roomkit topics (pack features.topics): GG's topics page and every page of every
topic, from the export's `topics` block (roomkit/topics.py), and
parity.topics (topic_parity.py).

The live side of the parity tests is markup written the way the plugin's templates
write it (archive-ggrr-topics.php, archive-ggrr-topic.php), so the two readers are
shown to agree on the same content. The block pages two records a page so the
paging is exercised without fifty records; the exporter's 50 is checked as text.
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
from roomkit import gate as G
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit import topic_parity as TOP
from roomkit import topics as TP
from roomkit.manifest import parse

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
ENGINE = GOLDEN / "engine"
EXPORTERS = HERE.parents[1] / "roomkit" / "exporters"
SITE = "https://example.test"
ROOM = SITE + "/library/"

BADGE = {"badge": "Government record", "badge_kind": "government", "badge_sr": "Provenance: "}
DOCS = {
    "camera-contract": {"title": "Camera Contract", "date": "January 2, 2026", "reading_time": "3 min", "agency": "Test Agency",
                        "collection": {"label": "Contracts", "url": ROOM + "collection/contracts/"},
                        "summary": "A camera contract & its renewal…", **BADGE},
    "site-photo": {"title": "Site Photo", "date": "Not listed yet"},
    "big-report": {"title": "Big Report", "agency": "Second Agency", "summary": "Pages of findings."},
    "data-dump": {"title": "Data Dump", **BADGE},
    "memo-text": {"title": "Memo", "date": "March 3, 1971"},
}


def _url(slug: str, n: int = 1) -> str:
    return ROOM + TP.page_path(slug, n)


def _paging(slug: str, n: int, total_pages: int) -> dict | None:
    # archive-ggrr-topic.php's loop, range 2.
    if total_pages < 2:
        return None
    items = [{"kind": "prev", "label": "← Previous", "url": _url(slug, n - 1)}] if n > 1 else []
    dots = False
    for i in range(1, total_pages + 1):
        if i == n:
            items.append({"kind": "current", "label": str(i)})
            dots = False
        elif i in (1, total_pages) or n - 2 <= i <= n + 2:
            items.append({"kind": "page", "label": str(i), "url": _url(slug, i)})
            dots = False
        elif not dots:
            items.append({"kind": "dots", "label": "…"})
            dots = True
    if n < total_pages:
        items.append({"kind": "next", "label": "Next →", "url": _url(slug, n + 1)})
    return {"label": "Page navigation", "items": items}


def _topic(slug: str, label: str, members: list[str], per: int = 2) -> list[dict]:
    total = len(members)
    pages = max(1, -(-total // per))
    out = []
    for n in range(1, pages + 1):
        p = {"slug": slug, "page": n, "url": _url(slug, n), "head_title": f"{slug.replace('-', ' ').title()} – Glass Government",
             "crumbs": [{"label": "Home", "url": SITE + "/"}, {"label": "Reading Room", "url": ROOM},
                        {"label": "Topics", "url": ROOM + "topics/"}, {"label": label}],
             "back": {"label": "← Reading Room", "url": ROOM}, "eyebrow": "Topic", "title": label,
             "subtitle": f"{total} document{'' if total == 1 else 's'}", "empty_text": "No documents found for this topic.",
             "jsonld": {"@context": "https://schema.org", "@type": "DefinedTerm", "name": label,
                        "description": f"{total} document{'' if total == 1 else 's'} tagged with {label} in the Glass Government Reading Room",
                        "url": _url(slug), "inDefinedTermSet": "Glass Government Reading Room Topics"},
             "documents": [{"slug": s, "url": ROOM + s + "/", **DOCS[s]} for s in members[(n - 1) * per:n * per]]}
        if total > per:
            p["search"] = {"label": "Filter documents", "placeholder": "Filter within this topic…"}
        if (pg := _paging(slug, n, pages)):
            p["pagination"] = pg
        out.append(p)
    return out


def _block() -> dict:
    topics = [("historical", "Historical", ["camera-contract", "site-photo", "big-report", "data-dump", "memo-text"]),
              ("fbi-diog", "FBI Diog", ["big-report"]),
              ("pfas_records", "PFAS Records", ["memo-text", "camera-contract"])]
    return {
        "index": {"url": ROOM + "topics/", "head_title": "Topics – Glass Government",
                  "back": {"label": "← Reading Room", "url": ROOM}, "title": "Topics",
                  "subtitle": "3 subjects across the collection", "empty_text": "No topics found.",
                  "topics": [{"slug": s, "label": s.replace("_", " ").replace("-", " ").title(), "count": str(len(m)),
                              "url": _url(s)} for s, _, m in topics]},
        "pages": [p for s, label, m in topics for p in _topic(s, label, m)],
        "source": {"templates/archive-ggrr-topic.php": "0" * 64},
    }


def _raw(block: dict | None = None, topics: bool = True) -> dict:
    m = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    m["site"]["template"] = "glassgovernment"
    m["site"]["room_path"] = "/library/"
    if topics:
        m["topics"] = block if block is not None else _block()
    return m


def _pack(on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site("glassgovernment"))
    p["features"] = {**p.get("features", {}), "topics": on}
    return p


def _render(on: bool = True, raw: dict | None = None, **kw) -> dict[str, bytes]:
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, indexer=S.stand_in, pack=_pack(on), **kw)


def _refusals(block: dict) -> list[str]:
    return [why for where, why in parse(_raw(block)).refusals if where == "topics"]


def _main(b: bytes) -> str:
    s = b.decode()
    return s[s.index("<main"):s.index("</main>")]


# --- the switch ------------------------------------------------------------------------

def test_switch_off_builds_exactly_the_room_without_topics():
    assert _render(False) == _render(False, _raw(topics=False))


def test_switch_off_keeps_the_golden_bytes():
    from tests.roomkit import test_golden as TG
    _, kw = TG.CASES["glassgovernment"]()
    files = B.render(parse(_raw()), engine=ENGINE, indexer=S.stand_in, pack=_pack(False), **kw)
    got = b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))
    pack_line = re.compile(rb'\n "pack": "[0-9a-f]{64}",\n')
    assert pack_line.sub(b"\n", got) == pack_line.sub(b"\n", (GOLDEN / "glassgovernment.txt").read_bytes())


def test_only_gg_turns_topics_on():
    # GG turned it on 2026-10-21, after parity.topics passed 74/74 against a fresh export.
    assert TP.enabled(K.for_site("glassgovernment"))
    for site in ("default", "deflockdane", "hrtarchive"):
        assert not TP.enabled(K.for_site(site)), site


def test_switch_on_without_a_block_ships_nothing():
    files = _render(raw=_raw(topics=False))
    assert not [p for p in files if p.startswith("topics/")]
    assert R.TOPICS_CSS not in files[B.published(files, "assets/room.css")].decode()


def test_switch_on_builds_every_page_of_every_topic_and_the_stylesheet():
    files = _render()
    assert {p for p in files if p.startswith("topics/")} == {
        "topics/index.html", "topics/historical/index.html", "topics/historical/page/2/index.html",
        "topics/historical/page/3/index.html", "topics/fbi-diog/index.html", "topics/pfas_records/index.html"}
    assert R.TOPICS_CSS in files[B.published(files, "assets/room.css")].decode()
    # Nothing for the pages to run: no script of their own.
    assert "room-collections" not in files["topics/historical/index.html"].decode()


def test_the_sitemap_lists_the_index_and_first_pages_as_the_sites_provider_does(tmp_path):
    files = _render()
    urls = set(BR.urls(TP.gate(parse(_raw()), _pack()), []))
    assert {ROOM + "topics/", _url("historical"), _url("fbi-diog"), _url("pfas_records")} <= urls
    assert not {u for u in urls if "/page/" in u}
    B.write(files, tmp_path / "room")
    rep = G.run(tmp_path / "room")
    assert rep["ok"], rep


def test_sitemap_parity_takes_the_topics_index_as_the_rooms_own(tmp_path):
    # GG's topic provider lists each topic's first page, not the topics index.
    from roomkit import browse_parity as BP
    room = _room(tmp_path)
    live = [u for u in BP.locs((room / "sitemap.xml").read_bytes(), "room") if u != ROOM + "topics/"]
    (tmp_path / "live.xml").write_text(BR.sitemap_xml(live))
    rep = BP.run_sitemaps([tmp_path / "live.xml"], room)
    assert rep["ok"] and not rep["extra"], rep
    (tmp_path / "live.xml").write_text(BR.sitemap_xml(live + [ROOM + "topics/historical/page/9/"]))
    assert BP.run_sitemaps([tmp_path / "live.xml"], room)["missing"] == [ROOM + "topics/historical/page/9/"]


# --- what the pages say ----------------------------------------------------------------

def test_topics_page_in_the_exported_order_with_counts():
    main = _main(_render()["topics/index.html"])
    assert "<h1 class=\"room__title\">Topics</h1>" in main and "3 subjects across the collection" in main
    got = re.findall(r'data-room-topic="([^"]+)"><span class="room__tcard-label">([^<]+)</span><span class="room__tcard-count">([^<]+)<', main)
    assert got == [("historical", "Historical", "5"), ("fbi-diog", "Fbi Diog", "1"), ("pfas_records", "Pfas Records", "2")]
    assert 'href="/library/topics/historical/"' in main and 'href="/library/">← Reading Room' in main


def test_a_topic_page_has_crumbs_heading_rows_and_paging():
    main = _main(_render()["topics/historical/page/2/index.html"])
    assert re.findall(r"<li>(?:<a[^>]*>|<span[^>]*>)([^<]+)", main.split("room__crumbs")[1].split("</nav>")[0]) == \
        ["Home", "Reading Room", "Topics", "Historical"]
    assert '<p class="room__eyebrow">Topic</p>' in main and "5 documents" in main
    assert re.findall(r'class="room__trow" data-room-doc="([^"]+)"', main) == ["big-report", "data-dump"]
    assert '<span class="room__trow-agency">Second Agency</span>' in main and "Pages of findings." in main
    pager = main.split('class="room__pager"')[1]
    assert re.findall(r'class="room__pager-(\w+)"(?: href="([^"]*)")?[^>]*>([^<]+)', pager) == [
        ("prev", "/library/topics/historical/", "← Previous"), ("page", "/library/topics/historical/", "1"),
        ("current", "", "2"), ("page", "/library/topics/historical/page/3/", "3"),
        ("next", "/library/topics/historical/page/3/", "Next →")]
    assert 'aria-current="page">2<' in pager


def test_a_row_shows_every_meta_field_escaped_and_the_badge_after_the_title():
    main = _main(_render()["topics/historical/index.html"])
    row = main.split('data-room-doc="camera-contract"')[1].split("</li>")[0]
    assert ('<a href="/library/camera-contract/">Camera Contract</a> <span class="room__badge room__badge--government">'
            '<span class="room__sr">Provenance: </span>Government record</span>') in row
    for part in ('<span class="room__trow-date">January 2, 2026</span>', 'href="https://example.test/library/collection/contracts/">Contracts</a>',
                 '<span class="room__trow-time">3 min</span>', '<span class="room__trow-agency">Test Agency</span>',
                 "A camera contract &amp; its renewal…"):
        assert part in row, part


def test_a_single_page_topic_has_no_paging_and_no_search():
    main = _main(_render()["topics/fbi-diog/index.html"])
    assert "room__pager" not in main and "<form" not in main and "Filter within" not in main
    assert "1 document<" in main


def test_head_title_canonical_and_jsonld_per_page():
    page = _render()["topics/historical/page/3/index.html"].decode()
    assert "<title>Historical – Glass Government</title>" in page
    assert f'rel="canonical" href="{ROOM}topics/historical/page/3/"' in page
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL).group(1))
    assert ld["@type"] == "DefinedTerm" and ld["url"] == _url("historical") and ld["description"].startswith("5 documents")


def test_the_mount_moves_every_link_and_the_canonicals_stay_live():
    files = _render(mount="/rr-staging/", noindex=True)
    page = files["topics/historical/page/2/index.html"].decode()
    assert 'href="/rr-staging/big-report/"' in page and 'href="/rr-staging/topics/historical/page/3/"' in page
    assert 'href="/rr-staging/topics/"' in page
    assert f'rel="canonical" href="{ROOM}topics/historical/page/2/"' in page


# --- what the manifest refuses ---------------------------------------------------------

def _edit(fn) -> dict:
    b = _block()
    fn(b)
    return b


@pytest.mark.parametrize("fn, why", [
    (lambda b: b["pages"][0]["documents"].append({"slug": "not-here", "title": "Gone", "url": ROOM + "not-here/"}),
     "record 'not-here' is not a public record in this room"),
    (lambda b: b["pages"][0].update(url=ROOM + "topics/historical/page/1/"), "is not https://example.test/library/topics/historical/"),
    (lambda b: b["pages"][1].update(url=SITE + "/elsewhere/topics/historical/page/2/"), "is not https://example.test/library/topics/historical/page/2/"),
    (lambda b: b["pages"].pop(1), "pages [1, 3] are not 1..3"),
    (lambda b: b["pages"].append(copy.deepcopy(b["pages"][0])), "listed twice"),
    (lambda b: b["pages"][0]["documents"].append(dict(b["pages"][0]["documents"][0])), "lists 'camera-contract' twice"),
    (lambda b: b["index"]["topics"].append({"slug": "ghost", "label": "Ghost", "count": "1", "url": _url("ghost")}),
     "lists 'ghost', which has no page"),
    (lambda b: b["pages"][0]["pagination"]["items"].append({"kind": "page", "label": "9", "url": _url("historical", 9)}),
     "paging links https://example.test/library/topics/historical/page/9/, which is not built"),
    (lambda b: b["pages"][0]["pagination"]["items"].append({"kind": "jump", "label": "x"}), "a paging item is not"),
    (lambda b: b["pages"][0]["pagination"]["items"].append({"kind": "next", "label": "x", "url": "javascript:x"}), "a paging item is not"),
    (lambda b: b["pages"][0].update(subtitle=""), "subtitle is missing or empty"),
    (lambda b: b["pages"][0].update(slug="Bad Slug"), "is not {slug: a topic key"),
    (lambda b: b["pages"][0].update(page=True), "is not {slug: a topic key"),
    (lambda b: b["index"].update(url=ROOM + "topic/"), "is not https://example.test/library/topics/"),
    (lambda b: b.update(extra=1), "topics is not {index?, pages: [...], source?}"),
])
def test_a_bad_block_is_refused_and_named(fn, why):
    got = _refusals(_edit(fn))
    assert any(why in g for g in got), got


def test_a_refused_block_builds_nothing():
    m = parse(_raw(_edit(lambda b: b["pages"].pop(1))))
    assert m.topics is None and m.refusals


# --- the exporter (read as text: the gate has no php) ------------------------------------

def test_the_gg_exporter_writes_topics_with_the_live_templates_formulas():
    src = (EXPORTERS / "glassgovernment.php").read_text(encoding="utf-8")
    block = src[src.index("// --- topics:"):src.index("// --- passages:")]
    for formula in (
        "GGRR_Storage::get_documents_by_topic($topic, $per_page, ($topic_page - 1) * $per_page, '')",
        "GGRR_Storage::get_topic_document_count($tslug, '')",
        "ggrr_holdings_topic_summary()",
        "ucwords(str_replace(['_', '-'], ' ', $topic)) . ' – Glass Government'",
        "in_array($seg, $acronyms, true) ? strtoupper($seg) : ucfirst($seg)",
        "sprintf(_n('%d document', '%d documents', $total, 'ggrr'), $total)",
        "' subjects across the collection'",
        "if ($total > $per_page)",
        "html_entity_decode(wp_trim_words($summary, 40), ENT_QUOTES)",
        "$T::format_display_date($date)",
        "(int) $doc['reading_time'] . ' min'",
        "$range = 2;",
        "'inDefinedTermSet' => 'Glass Government Reading Room Topics'",
        "roomkit_gg_topic_page($tslug, $n, $ttotal, 50)",
    ):
        assert formula in block, formula
    assert "($slice === null || $slice['offset'] === 0)" in block
    assert "+ ($topics ? ['topics' => $topics] : [])" in src


# --- parity.topics: live markup as the templates write it ----------------------------------

def _e(s: str) -> str:
    return html.escape(s, quote=True)


def live_topics_page(b: dict) -> str:
    ix = b["index"]
    cards = "".join(f'<a class="ggrr-topic-card" href="{_e(t["url"])}"> <span class="ggrr-topic-card__label">{_e(t["label"])}</span>'
                    f' <span class="ggrr-topic-card__count">{_e(t["count"])}</span> </a>' for t in ix["topics"])
    return ('<html><body><div class="ggrr-rr" data-ggrr-theme-root><div class="ggrr-rr__header">'
            f'<a class="ggrr-rr__back" href="{ROOM}">&larr; Reading Room</a><h1>Topics</h1>'
            f'<p class="ggrr-rr__subtitle">{_e(ix["subtitle"])}</p></div><div class="ggrr-rr__body">'
            f'<div class="ggrr-topics-grid">{cards}</div></div></div></body></html>')


def live_topic_page(p: dict) -> str:
    rows = []
    for d in p["documents"]:
        badge = (f'<span class="ggrr-prov-badge ggrr-prov-badge--{d["badge_kind"]}"><span class="visually-hidden">'
                 f'{_e(d["badge_sr"])}</span>{_e(d["badge"])}</span>') if d.get("badge") else ""
        meta = ""
        if d.get("date"):
            meta += f'<span class="ggrr-doc-row__date">{_e(d["date"])}</span>'
        if d.get("collection"):
            meta += f'<span class="ggrr-doc-row__collection"> <a href="{_e(d["collection"]["url"])}">{_e(d["collection"]["label"])}</a> </span>'
        if d.get("reading_time"):
            meta += f'<span class="ggrr-doc-row__reading-time">{_e(d["reading_time"])}</span>'
        if d.get("agency"):
            meta += f'<span class="ggrr-doc-row__agency">{_e(d["agency"])}</span>'
        summary = f'<p class="ggrr-doc-row__summary">{_e(d["summary"])}</p>' if d.get("summary") else ""
        rows.append(f'<article class="ggrr-doc-row ggrr-cat--historical"><a href="{_e(d["url"])}" class="ggrr-doc-row__link">'
                    f'<h3 class="ggrr-doc-row__title">{_e(d["title"])}{badge}</h3></a>'
                    f'<div class="ggrr-doc-row__meta">{meta}</div>{summary}</article>')
    pager = ""
    if p.get("pagination"):
        out = []
        for it in p["pagination"]["items"]:
            if it["kind"] == "current":
                out.append(f'<span aria-current="page" class="page-numbers current">{it["label"]}</span>')
            elif it["kind"] == "dots":
                out.append('<span class="page-numbers dots">&hellip;</span>')
            else:
                cls = {"prev": "prev page-numbers", "next": "next page-numbers"}.get(it["kind"], "page-numbers")
                out.append(f'<a class="{cls}" href="{_e(it["url"])}">{_e(it["label"])}</a>')
        pager = f'<nav class="ggrr-pagination" aria-label="Page navigation"> {"".join(out)} </nav>'
    crumbs = (f'<nav class="ggrr-document__breadcrumbs" aria-label="Breadcrumb"> <a href="{SITE}/">Home</a> <span class="sep">/</span>'
              f' <a href="{ROOM}">Reading Room</a> <span class="sep">/</span> <a href="{ROOM}topics/">Topics</a>'
              f' <span class="sep">/</span> <span aria-current="page">{_e(p["title"])}</span> </nav>')
    form = ('<form class="ggrr-search-form" method="GET"><input class="ggrr-search-input" type="text" name="s" '
            'placeholder="Filter within this topic&hellip;" aria-label="Filter documents"></form>') if p.get("search") else ""
    ld = json.dumps(p["jsonld"], indent=4)
    return (f'<html><head><script type="application/ld+json">{ld}</script></head><body><div class="ggrr-rr" data-ggrr-theme-root>'
            f'<div class="ggrr-rr__header">{crumbs}<a class="ggrr-rr__back" href="{ROOM}">&larr; Reading Room</a>'
            f'<div class="ggrr-rr__eyebrow">Topic</div><h1>{_e(p["title"])}</h1><p class="ggrr-rr__subtitle"> {_e(p["subtitle"])} </p>'
            f'{form}</div><div class="ggrr-rr__body">{"".join(rows) or "<p>No documents found for this topic.</p>"}{pager}'
            '</div></div></body></html>')


def _tsv(tmp_path, b: dict, drop: str = "") -> Path:
    pages = {"library/topics/": (200, live_topics_page(b))}
    for p in b["pages"]:
        path = "library/" + TP.page_path(p["slug"], p["page"])
        if path != drop:
            pages[path] = (200, live_topic_page(p))
    lines = ["# fetched 2026-10-21T00:00:00Z GET https://example.test/<path>"]
    lines += [f"{k}\t{c}\t{base64.b64encode(h.encode()).decode()}" for k, (c, h) in pages.items()]
    (tmp_path / "pages.tsv").write_text("\n".join(lines) + "\n")
    return tmp_path / "pages.tsv"


def _room(tmp_path, **kw) -> Path:
    B.write(_render(**kw), tmp_path / "room")
    return tmp_path / "room"


def _live(tmp_path, capsys, b: dict | None = None, drop: str = "") -> Path:
    assert cli.main(["parity", "--topics-from", str(_tsv(tmp_path, b or _block(), drop)), "--site", "glassgovernment"]) == 0
    (tmp_path / "live.json").write_text(capsys.readouterr().out)
    return tmp_path / "live.json"


def test_the_live_markup_and_the_room_agree(tmp_path, capsys):
    room = _room(tmp_path)
    live = _live(tmp_path, capsys)
    rep = TOP.run(live, room)
    assert rep["ok"], TOP.text_report(rep)
    assert rep["same"] == rep["total"] == 5 and rep["index"] == "same"
    assert cli.main(["parity", "--topics", str(live), "--out", str(room)]) == 0
    assert "PASSES: topic pages 5/5 same" in capsys.readouterr().out


def test_a_staging_mount_compares_the_same(tmp_path, capsys):
    room = _room(tmp_path, mount="/rr-staging/", noindex=True)
    rep = TOP.run(_live(tmp_path, capsys), room)
    assert rep["ok"], TOP.text_report(rep)


def test_the_live_reader_reads_every_field():
    p = TOP.read_page(live_topic_page(_block()["pages"][0]), "live", "/library/")
    assert p["crumbs"] == ["Home", "Reading Room", "Topics", "Historical"] and p["subtitle"] == "5 documents"
    assert p["documents"][0] == {"slug": "camera-contract", "title": "Camera Contract", "badge": "Provenance: Government record",
                                 "date": "January 2, 2026", "collection": "Contracts", "reading_time": "3 min",
                                 "agency": "Test Agency", "summary": "A camera contract & its renewal…"}
    assert p["pagination"][0] == ["current", "1", ""] and p["pagination"][-1] == ["next", "Next →", "topics/historical/page/2/"]
    assert p["jsonld"]["name"] == "Historical"


@pytest.mark.parametrize("change, where", [
    (lambda b: b["pages"][1]["documents"].reverse(), "historical/2.documents[0]"),
    (lambda b: b["pages"][0]["documents"][0].update(summary="Changed."), "historical/1.documents[0].summary"),
    (lambda b: b["pages"][0]["pagination"]["items"].pop(), "historical/1.pagination"),
    (lambda b: b["index"]["topics"].reverse(), "index.topics[0]"),
])
def test_a_live_difference_fails_and_says_where(tmp_path, capsys, change, where):
    room = _room(tmp_path)
    b = _block()
    change(b)
    rep = TOP.run(_live(tmp_path, capsys, b), room)
    assert not rep["ok"] and where in TOP.text_report(rep), TOP.text_report(rep)
    assert cli.main(["parity", "--topics", str(tmp_path / "live.json"), "--out", str(room)]) == 1


def test_an_unfetched_or_unlisted_live_page_is_not_a_pass(tmp_path, capsys):
    room = _room(tmp_path)
    rep = TOP.run(_live(tmp_path, capsys, drop="library/topics/historical/page/3/"), room)
    assert not rep["ok"] and rep["pages"]["historical/3"] == "unchecked (no live page)"
    rep = TOP.run(_live(tmp_path, capsys, drop="library/topics/fbi-diog/"), room)
    assert not rep["ok"] and rep["unpaged"] == ["fbi-diog"]


def test_a_pages_file_for_another_site_is_refused(tmp_path):
    assert cli.main(["parity", "--topics-from", str(_tsv(tmp_path, _block())), "--site", "deflockdane"]) == 2


# --- in a browser ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def topic_room(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path_factory.mktemp("topic-room")
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


PAGES = ("/library/topics/", "/library/topics/historical/", "/library/topics/historical/page/2/", "/library/topics/fbi-diog/")
AXE = """() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}})
  .then(r => r.violations.map(v => v.id + ': ' + v.nodes.map(n => n.target.join(' ')).join(', ')))"""


@pytest.mark.parametrize("width", (375, 1280))
@pytest.mark.parametrize("path", PAGES)
def test_in_a_browser_topic_pages_pass_axe_and_fit(topic_room, path, width):
    from tests.reading_room_reader.conftest import axe_source
    b, base = topic_room
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


def test_in_a_browser_without_javascript_the_paging_walks_every_page(topic_room):
    b, base = topic_room
    page = b.new_context(viewport={"width": 375, "height": 812}, java_script_enabled=False).new_page()
    page.goto(base + "/library/topics/")
    page.get_by_role("link", name=re.compile("^Historical")).click()
    seen = []
    while True:
        seen += [li.get_attribute("data-room-doc") for li in page.locator("main .room__trow").all()]
        levels = page.evaluate("() => [...document.querySelectorAll('main h1,main h2,main h3')].map(h => +h.tagName[1])")
        assert levels[0] == 1 and all(y - x <= 1 for x, y in itertools.pairwise(levels)), levels
        nxt = page.locator("main .room__pager-next")
        if not nxt.count():
            break
        nxt.click()
    assert seen == ["camera-contract", "site-photo", "big-report", "data-dump", "memo-text"]
    page.close()
