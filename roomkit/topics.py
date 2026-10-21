"""Topics (pack features.topics): GG's topics index and topic pages, paged as live.

GG serves /library/topics/ (gg-reading-room templates/archive-ggrr-topics.php: every
approved topic with its count, most first) and /library/topics/<topic>/ with
/page/N/ for each further 50 records (templates/archive-ggrr-topic.php: crumbs, the
record count, rows with date, collection, reading time, agency and a 40-word
summary, numbered paging, DefinedTerm JSON-LD). The exporter writes every page as
the templates do, each formula named there, and the room renders the pages at the
same paths; roomkit sorts, pages and composes nothing.

The manifest block (optional):

    "topics": {
      "index": {"url", "head_title", "title", "subtitle", "empty_text", "back"?: {label, url},
                "topics": [{"slug", "label", "count", "url"}]},
      "pages": [{
        "slug", "page": 1.., "url", "head_title", "title", "subtitle", "empty_text",
        "crumbs"?: [{label, url}], "back"?: {label, url}, "eyebrow"?,
        "search"?: {"label", "placeholder", "param"?},  (live shows it past one page; with
                                                  param and pack features.server-search the
                                                  room renders it as a GET form to the
                                                  topic's live URL, which the site's server
                                                  answers; the room answers nothing)
        "documents": [{"slug", "title", "url", "badge"?, "badge_kind"?, "badge_sr"?,
                       "date"?, "collection"?: {label, url}, "reading_time"?, "agency"?,
                       "summary"?}],
        "pagination"?: {"label", "items": [{"kind": prev|page|current|dots|next, "label", "url"?}]},
        "jsonld"?: {...}
      }],
      "source": {"<plugin file>": "<sha256>"}
    }

Refused: a URL outside the room path or not made of key segments; a page whose URL
is not `topics/<slug>/` (page 1) or `topics/<slug>/page/<n>/`; a topic's pages not
numbered 1..N without gaps; a record that is not one the room holds, at its own
URL; a paging link to a page of the same topic that is not built; an index entry
naming a topic with no page; a duplicate; missing or non-text strings.
"""

from __future__ import annotations

import re
from dataclasses import replace

from . import entities as E
from . import site_collections as CO

FEATURE = "topics"
PARAM = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
KINDS = ("prev", "page", "current", "dots", "next")
_text, _url_ok, _strings, _links = E._text, E._url_ok, E._strings, E._links


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def gate(m, pack: dict):
    """The manifest without its topics when the pack does not turn them on."""
    if getattr(m, "topics", None) and not enabled(pack):
        return replace(m, topics=None)
    return m


def page_path(slug: str, n: int) -> str:
    return f"topics/{slug}/" if n == 1 else f"topics/{slug}/page/{n}/"


def _doc(d: object, where: str, room: str, doc_slugs: set[str], problems: list[str]) -> str | None:
    if not (isinstance(d, dict) and E.SLUG.match(str(d.get("slug", ""))) and _text(d.get("title"))
            and _url_ok(d.get("url"))):
        problems.append(f"a {where} record is not {{slug, title, url}}")
        return None
    if E._room_slug(d["url"], room) != d["slug"] or d["slug"] not in doc_slugs:
        problems.append(f"{where} record {d['slug']!r} is not a public record in this room")
        return None
    _strings(d, ("badge", "badge_sr", "date", "reading_time", "agency", "summary"), f"{where} {d['slug']}",
             problems, optional=True)
    if d.get("badge_kind") and not E.SLUG.match(str(d["badge_kind"])):
        problems.append(f"{where} {d['slug']}: badge_kind is not a slug")
    if "collection" in d:
        _links([d["collection"]], f"{where} {d['slug']}.collection", problems, need_url=True)
    return d["slug"]


def _page(p: dict, where: str, room: str, doc_slugs: set[str], problems: list[str]) -> None:
    _strings(p, ("head_title", "title", "subtitle", "empty_text"), where, problems, optional=False)
    _strings(p, ("eyebrow",), where, problems, optional=True)
    if "back" in p:
        _links([p["back"]], f"{where}.back", problems, need_url=True)
    if "crumbs" in p:
        if not isinstance(p["crumbs"], list):
            problems.append(f"{where}.crumbs is not a list")
        else:
            _links(p["crumbs"][:-1], f"{where}.crumbs", problems, need_url=True)
            _links(p["crumbs"][-1:], f"{where}.crumbs", problems, need_url=False)
    s = p.get("search")
    if s is not None and not (isinstance(s, dict) and set(s) <= {"label", "placeholder", "param"}
                              and _text(s.get("label")) and _text(s.get("placeholder"))
                              and ("param" not in s or (isinstance(s["param"], str) and PARAM.match(s["param"])))):
        problems.append(f"{where}.search is not {{label, placeholder, param?: a lowercase query name}}")
    if "jsonld" in p and not isinstance(p["jsonld"], dict):
        problems.append(f"{where}.jsonld is not an object")
    docs = p.get("documents")
    if not isinstance(docs, list):
        problems.append(f"{where}.documents is not a list")
        return
    seen: set[str] = set()
    for d in docs:
        slug = _doc(d, where, room, doc_slugs, problems)
        if slug in seen:
            problems.append(f"{where} lists {slug!r} twice")
        if slug:
            seen.add(slug)
    pg = p.get("pagination")
    if pg is not None:
        if not (isinstance(pg, dict) and _text(pg.get("label")) and isinstance(pg.get("items"), list) and pg["items"]):
            problems.append(f"{where}.pagination is not {{label, items: [...]}}")
            return
        for it in pg["items"]:
            ok = isinstance(it, dict) and it.get("kind") in KINDS and _text(it.get("label"))
            if ok and it["kind"] in ("prev", "page", "next"):
                ok = _url_ok(it.get("url"))
            if not ok:
                problems.append(f"{where}: a paging item is not {{kind in {list(KINDS)}, label, url (links)}}")


def parse(raw: object, base_url: str, room_path: str, doc_slugs: set[str]) -> tuple[dict | None, list[str]]:
    """{"index", "pages" (each with "path")} and every problem; a block with problems is not returned."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict) or not set(raw) <= {"index", "pages", "source"} or not isinstance(raw.get("pages"), list):
        return None, ["topics is not {index?, pages: [...], source?}"]
    src = raw.get("source", {})
    if not (isinstance(src, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in src.items())):
        return None, ["topics.source is not {file: sha256}"]
    room = base_url + room_path
    problems: list[str] = []
    out_pages, numbers, urls = [], {}, {}
    for p in raw["pages"]:
        if not (isinstance(p, dict) and CO.KEY.match(str(p.get("slug", ""))) and isinstance(p.get("page"), int)
                and not isinstance(p.get("page"), bool) and p["page"] >= 1):
            problems.append("a topics.pages entry is not {slug: a topic key, page: 1.., ...}")
            continue
        where = f"topic {p['slug']} page {p['page']}"
        want = page_path(p["slug"], p["page"])
        rest = CO.rel_path(p.get("url"), room) if isinstance(p.get("url"), str) else ""
        if rest != want:
            problems.append(f"{where}: URL {p.get('url')!r} is not {room}{want}")
            continue
        if want.split("/", 1)[0] in doc_slugs:
            problems.append(f"{where}: a record's slug is 'topics'")
        if p["page"] in numbers.setdefault(p["slug"], set()):
            problems.append(f"{where}: listed twice")
        numbers[p["slug"]].add(p["page"])
        urls[p["url"]] = p["slug"]
        _page(p, where, room, doc_slugs, problems)
        out_pages.append({**p, "path": want})
    for slug, ns in numbers.items():
        if ns != set(range(1, max(ns) + 1)):
            problems.append(f"topic {slug}: pages {sorted(ns)} are not 1..{max(ns)}")
    # A paging link to this topic must land on a built page of it.
    for p in out_pages:
        for it in (p.get("pagination") or {}).get("items", []):
            u = it.get("url")
            if u and u.startswith(room + "topics/" + p["slug"] + "/") and urls.get(u) != p["slug"]:
                problems.append(f"topic {p['slug']} page {p['page']}: paging links {u}, which is not built")
    index = raw.get("index")
    out_index = None
    if index is not None:
        if not isinstance(index, dict):
            problems.append("topics.index is not an object")
        else:
            where = "topics index"
            if not (isinstance(index.get("url"), str) and CO.rel_path(index["url"], room) == "topics/"):
                problems.append(f"{where}: URL {index.get('url')!r} is not {room}topics/")
            _strings(index, ("head_title", "title", "subtitle", "empty_text"), where, problems, optional=False)
            if "back" in index:
                _links([index["back"]], f"{where}.back", problems, need_url=True)
            ts = index.get("topics")
            if not isinstance(ts, list):
                problems.append(f"{where}.topics is not a list")
            else:
                seen: set[str] = set()
                for t in ts:
                    if not (isinstance(t, dict) and CO.KEY.match(str(t.get("slug", ""))) and _text(t.get("label"))
                            and _text(t.get("count")) and _url_ok(t.get("url"))):
                        problems.append(f"a {where} entry is not {{slug, label, count, url}}")
                        continue
                    if t["slug"] in seen:
                        problems.append(f"{where} lists {t['slug']!r} twice")
                    seen.add(t["slug"])
                    if urls.get(t["url"]) != t["slug"] or t["url"] != room + page_path(t["slug"], 1):
                        problems.append(f"{where} lists {t['slug']!r}, which has no page at {t['url']}")
            out_index = {**index, "path": "topics/"}
    if problems:
        return None, problems
    return {"index": out_index, "pages": out_pages}, []


def served(block: dict | None) -> set[str]:
    if not block:
        return set()
    return {p["path"] for p in block["pages"]} | ({block["index"]["path"]} if block.get("index") else set())


def sitemap_urls(block: dict | None) -> list[str]:
    """What GG's topic sitemap provider lists: each topic's first page (not the index, not /page/N/)."""
    return [p["url"] for p in block["pages"] if p["page"] == 1] if block else []
