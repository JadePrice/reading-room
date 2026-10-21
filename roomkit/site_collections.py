"""Collections: the manifest's `collections` block, its refusals, and the paths it serves.

Turned on by a pack's `features.collections` (off unless the pack says so; matrix
rows collections-index, collection-page, index-collections-grid). As with
entities, `gate()` is the one place that decides: a build with the switch off
never sees the block, so nothing it renders changes.

Every word comes from the export, written as the site's own templates write it
(the exporter repeats each formula and names it): headings, counts, stamps, the
year spans, the notices, the JSON-LD, the search and sort labels. roomkit
composes no label and re-orders nothing; the lists arrive in the site's order.

    "collections": {
      "index": {                                   (optional: the site's collections page)
        "url": "<base_url><room_path>collections/",
        "head_title": "...", "title": "...", "empty_text": "...",
        "eyebrow", "lede", "back": {"label", "url"}, "image": {"url", "alt"}   (optional)
        "search": {"label", "placeholder"},                                    (optional)
        "filters": {"label", "group_label", "options": [{"value", "label"}]},  (optional;
                     the first option shows everything; a card with no tags shows under every filter)
        "sort": {"label", "options": [{"value": default|year-asc|year-desc|alpha, "label"}]},  (optional)
        "categories": [{"key": "<slug>", "heading": "...", "stamp"?,
                        "groups": [{"id": "<slug>", "heading": "...",
                                    "collections": [{"slug", "title", "url", "count",
                                                     "code"?, "blurb"?, "years"?, "year"?,
                                                     "tags"?: ["<filter value>"], "match"?}]}]}]
      },
      "pages": [{
        "slug": "<collection>", "url": "<base_url><room_path>.../<collection>/",
        "head_title": "...", "title": "...", "count": "...", "list_label": "...", "empty_text": "...",
        "eyebrow", "back", "stamp", "stamp_kind", "years", "blurb", "description"   (optional)
        "notice": {"heading", "body", "report"?},                                  (optional)
        "search": {"label", "placeholder", "status": "... {shown} ... {total} ..."},(optional)
        "documents": [{"slug", "title", "url", "num",
                       "final"?, "badge"?, "badge_kind"?, "badge_sr"?, "size"?}],
        "jsonld": {...}                                                            (optional)
      }],
      "grid": {                                    (optional: the table on the room's index)
        "heading": "...", "columns": ["Period", "Collection", "Sources", "Description"],
        "sort": {"label", "options": [{"value": default|name|year-desc|year-asc, "label"}]},  (optional)
        "eras": [{"heading": "...",
                  "groups": [{"heading": "...",
                              "rows": [{"slug", "title", "url", "years"?, "year"?,
                                        "sources"?, "sources_line"?, "sources_empty"?,
                                        "blurb"?, "blurb_empty"?}]}]}]
      },
      "source": {"<plugin file>": "<sha256>"}       (optional; not rendered)
    }

A collection slug is the site's key (`sanitize_key`: lowercase letters, digits,
`-` and `_`), so GG's `cointelpro_new_left` is one. Paths are the live ones, and
the static tree serves each at the same path under the mount.

Refused (as manifest refusals, so the whole build stops): a malformed block, a URL
outside the room path or not made of key segments, a page URL that does not end
in its own slug, a path whose first segment is a record's slug or the room's own,
two pages at one path, a page document that is not a public record in this room,
an index card or grid row naming a collection with no page (when the block has
pages) or at another URL, a card tag that is no filter's value, a sort value the
room cannot sort by.
"""

from __future__ import annotations

import re
from dataclasses import replace

from . import entities as E

FEATURE = "collections"
KEY = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
SLUG = E.SLUG
INDEX_SORTS = ("default", "year-asc", "year-desc", "alpha")
GRID_SORTS = ("default", "name", "year-desc", "year-asc")
YEAR = re.compile(r"^\d{1,4}$")
_text, _url_ok, _strings, _links = E._text, E._url_ok, E._strings, E._links


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def gate(m, pack: dict):
    """The manifest as the pack lets the room see it: without its collections when the
    pack does not turn them on. Pages, links, the grid and the assets all follow this."""
    if getattr(m, "collections", None) and not enabled(pack):
        return replace(m, collections=None)
    return m


def rel_path(url: str, room: str) -> str:
    """`collection/cointelpro_cuba/` from the page's live URL, or '' if it is not under
    `room` as key segments."""
    if not url.startswith(room):
        return ""
    rest = url[len(room):]
    segs = rest.split("/")
    if not rest.endswith("/") or len(segs) < 2 or not all(KEY.match(s) for s in segs[:-1]):
        return ""
    return rest


def _sort(s: object, values: tuple[str, ...], where: str, problems: list[str]) -> None:
    if not (isinstance(s, dict) and _text(s.get("label")) and isinstance(s.get("options"), list) and s["options"]
            and all(isinstance(o, dict) and o.get("value") in values and _text(o.get("label")) for o in s["options"])
            and len({o["value"] for o in s["options"]}) == len(s["options"])):
        problems.append(f"{where}.sort needs a label and options of {{value in {list(values)}, label}}, each once")


def _optional_text(obj: dict, keys: tuple[str, ...], where: str, problems: list[str]) -> None:
    _strings(obj, keys, where, problems, optional=True)


def _page(p: dict, where: str, room: str, doc_slugs: set[str], problems: list[str]) -> None:
    _strings(p, ("head_title", "title", "count", "list_label", "empty_text"), where, problems, optional=False)
    _optional_text(p, ("eyebrow", "stamp", "years", "blurb", "description"), where, problems)
    if p.get("stamp_kind") and not SLUG.match(str(p["stamp_kind"])):
        problems.append(f"{where}.stamp_kind is not a slug")
    if "back" in p:
        _links([p["back"]], f"{where}.back", problems, need_url=True)
    n = p.get("notice")
    if n is not None and not (isinstance(n, dict) and _text(n.get("heading")) and _text(n.get("body"))
                              and _text(n.get("report", ""), optional=True)):
        problems.append(f"{where}.notice is not {{heading, body, report?}}")
    s = p.get("search")
    if s is not None and not (isinstance(s, dict) and all(_text(s.get(k)) for k in ("label", "placeholder", "status"))
                              and "{shown}" in s["status"] and "{total}" in s["status"]):
        problems.append(f"{where}.search is not {{label, placeholder, status}} with {{shown}} and {{total}} in status")
    if "jsonld" in p and not isinstance(p["jsonld"], dict):
        problems.append(f"{where}.jsonld is not an object")
    docs = p.get("documents")
    if not isinstance(docs, list):
        problems.append(f"{where}.documents is not a list")
        return
    seen: set[str] = set()
    for d in docs:
        if not (isinstance(d, dict) and SLUG.match(str(d.get("slug", ""))) and _text(d.get("title"))
                and _url_ok(d.get("url")) and _text(d.get("num"))):
            problems.append(f"a {where} document is not {{slug, title, url, num}}")
            continue
        # The page lists records; each must be one this room holds, at its own URL.
        named = E._room_slug(d["url"], room)
        if named != d["slug"] or d["slug"] not in doc_slugs:
            problems.append(f"{where} document {d['slug']!r} is not a public record in this room")
            continue
        if d["slug"] in seen:
            problems.append(f"{where} lists {d['slug']!r} twice")
        seen.add(d["slug"])
        _optional_text(d, ("final", "badge", "badge_sr", "size"), f"{where} document {d['slug']}", problems)
        if d.get("badge_kind") and not SLUG.match(str(d["badge_kind"])):
            problems.append(f"{where} document {d['slug']}: badge_kind is not a slug")


def _member(c: object, where: str, pages: dict[str, str] | None, problems: list[str]) -> dict | None:
    """One index card or grid row: a collection by slug, title and URL."""
    if not (isinstance(c, dict) and KEY.match(str(c.get("slug", ""))) and _text(c.get("title"))
            and _url_ok(c.get("url"))):
        problems.append(f"a {where} entry is not {{slug, title, url}} with a collection key")
        return None
    if pages is not None and pages.get(c["slug"]) != c["url"]:
        problems.append(f"{where} lists {c['slug']!r}, which has no page at {c['url']}")
    if "year" in c and not (isinstance(c["year"], str) and (c["year"] == "" or YEAR.match(c["year"]))):
        problems.append(f"{where} {c['slug']}: year is not a year")
    return c


def _index(ix: dict, pages: dict[str, str] | None, problems: list[str]) -> None:
    where = "collections index"
    _strings(ix, ("head_title", "title", "empty_text"), where, problems, optional=False)
    _optional_text(ix, ("eyebrow", "lede"), where, problems)
    if "back" in ix:
        _links([ix["back"]], f"{where}.back", problems, need_url=True)
    img = ix.get("image")
    if img is not None and not (isinstance(img, dict) and _url_ok(img.get("url")) and _text(img.get("alt"))):
        problems.append(f"{where}.image is not {{url, alt}}")
    s = ix.get("search")
    if s is not None and not (isinstance(s, dict) and _text(s.get("label")) and _text(s.get("placeholder"))):
        problems.append(f"{where}.search is not {{label, placeholder}}")
    if "sort" in ix:
        _sort(ix["sort"], INDEX_SORTS, where, problems)
    tags: set[str] | None = None
    f = ix.get("filters")
    if f is not None:
        if not (isinstance(f, dict) and _text(f.get("label")) and _text(f.get("group_label"))
                and isinstance(f.get("options"), list) and len(f["options"]) >= 2
                and all(isinstance(o, dict) and SLUG.match(str(o.get("value", ""))) and _text(o.get("label"))
                        for o in f["options"])
                and len({o["value"] for o in f["options"]}) == len(f["options"])):
            problems.append(f"{where}.filters is not {{label, group_label, options: [{{value, label}}, ...]}}")
        else:
            tags = {o["value"] for o in f["options"][1:]}
    cats = ix.get("categories")
    if not isinstance(cats, list):
        problems.append(f"{where}.categories is not a list")
        return
    seen: set[str] = set()
    for c in cats:
        if not (isinstance(c, dict) and SLUG.match(str(c.get("key", ""))) and _text(c.get("heading"))
                and _text(c.get("stamp", ""), optional=True) and isinstance(c.get("groups"), list)):
            problems.append(f"a {where} category is not {{key, heading, stamp?, groups}}")
            continue
        for g in c["groups"]:
            if not (isinstance(g, dict) and SLUG.match(str(g.get("id", ""))) and _text(g.get("heading"))
                    and isinstance(g.get("collections"), list) and g["collections"]):
                problems.append(f"a {where} group is not {{id, heading, collections: [...]}} (non-empty)")
                continue
            for card in g["collections"]:
                card = _member(card, where, pages, problems)
                if card is None:
                    continue
                if card["slug"] in seen:
                    problems.append(f"{where} lists {card['slug']!r} twice")
                seen.add(card["slug"])
                _strings(card, ("count",), f"{where} {card['slug']}", problems, optional=False)
                _optional_text(card, ("code", "blurb", "years", "match"), f"{where} {card['slug']}", problems)
                ct = card.get("tags", [])
                if not (isinstance(ct, list) and all(isinstance(t, str) for t in ct)):
                    problems.append(f"{where} {card['slug']}: tags is not a list of text")
                elif ct and (tags is None or not set(ct) <= tags):
                    problems.append(f"{where} {card['slug']}: tags {ct} are not all filter values")


def _grid(gr: object, pages: dict[str, str] | None, problems: list[str]) -> None:
    where = "collections grid"
    if not isinstance(gr, dict):
        problems.append(f"{where} is not an object")
        return
    _strings(gr, ("heading",), where, problems, optional=False)
    cols = gr.get("columns")
    if not (isinstance(cols, list) and len(cols) == 4 and all(_text(c) for c in cols)):
        problems.append(f"{where}.columns is not four headings")
    if "sort" in gr:
        _sort(gr["sort"], GRID_SORTS, where, problems)
    eras = gr.get("eras")
    if not isinstance(eras, list):
        problems.append(f"{where}.eras is not a list")
        return
    seen: set[str] = set()
    for e in eras:
        if not (isinstance(e, dict) and _text(e.get("heading")) and isinstance(e.get("groups"), list)):
            problems.append(f"a {where} era is not {{heading, groups}}")
            continue
        for g in e["groups"]:
            if not (isinstance(g, dict) and _text(g.get("heading")) and isinstance(g.get("rows"), list) and g["rows"]):
                problems.append(f"a {where} group is not {{heading, rows: [...]}} (non-empty)")
                continue
            for r in g["rows"]:
                r = _member(r, where, pages, problems)
                if r is None:
                    continue
                if r["slug"] in seen:
                    problems.append(f"{where} lists {r['slug']!r} twice")
                seen.add(r["slug"])
                _optional_text(r, ("years", "sources", "sources_line", "sources_empty", "blurb", "blurb_empty"),
                               f"{where} {r['slug']}", problems)


def parse(raw: object, base_url: str, room_path: str, doc_slugs: set[str]) -> tuple[dict | None, list[str]]:
    """The checked block (plain dicts, as exported, plus each page's `path`), and
    every problem. A block with problems is not returned."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict) or not set(raw) <= {"index", "pages", "grid", "source"}:
        return None, ["collections is not {index?, pages?, grid?, source?}"]
    src = raw.get("source", {})
    if not (isinstance(src, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in src.items())):
        return None, ["collections.source is not {file: sha256}"]
    room = base_url + room_path
    problems: list[str] = []
    paths: dict[str, str] = {}

    def claim(url: object, where: str, tail: str = "") -> str:
        rest = rel_path(url, room) if isinstance(url, str) else ""
        if not rest:
            problems.append(f"{where}: URL {url!r} is not under {room} as key segments")
            return ""
        if tail and not rest.endswith("/" + tail) and rest != tail:
            problems.append(f"{where}: URL {url!r} does not end in {tail}")
        first = rest.split("/", 1)[0]
        if first in doc_slugs or first in E.RESERVED:
            problems.append(f"{where}: path {rest} starts with {first!r}, a record's or the room's own path")
        if rest in paths:
            problems.append(f"{where}: {rest} is also {paths[rest]}")
        paths[rest] = where
        return rest

    pages = raw.get("pages")
    if pages is not None and not isinstance(pages, list):
        return None, ["collections.pages is not a list"]
    out_pages, by_slug = [], {}
    for p in pages or []:
        if not (isinstance(p, dict) and KEY.match(str(p.get("slug", "")))):
            problems.append("a collections.pages entry has no collection key slug")
            continue
        where = f"collection {p['slug']}"
        if p["slug"] in by_slug:
            problems.append(f"{where}: listed twice")
        by_slug[p["slug"]] = p.get("url")
        rest = claim(p.get("url"), where, p["slug"] + "/")
        _page(p, where, room, doc_slugs, problems)
        out_pages.append({**p, "path": rest})
    known = by_slug if pages is not None else None

    index = raw.get("index")
    out_index = None
    if index is not None:
        if not isinstance(index, dict):
            problems.append("collections.index is not an object")
        else:
            rest = claim(index.get("url"), "collections index")
            _index(index, known, problems)
            out_index = {**index, "path": rest}
    if "grid" in raw:
        _grid(raw["grid"], known, problems)
    if problems:
        return None, problems
    return {"index": out_index, "pages": out_pages, "grid": raw.get("grid")}, []


def served(block: dict | None) -> set[str]:
    """The room-relative paths the block's pages are served at."""
    if not block:
        return set()
    out = {p["path"] for p in block["pages"]}
    if block.get("index"):
        out.add(block["index"]["path"])
    return out
