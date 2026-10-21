"""parity.topics: does the room hold the site's topics, as the site shows them?

Matrix row `topics` (GG): on the topics page the same topics in the same order
with the same labels and counts; per topic and per page (/page/N/) the same
crumbs, heading, record count, records in order (each with its title, badge,
date, collection, reading time, agency and summary), paging links and JSON-LD.
Every page of every topic is compared, not a sample.

The live side is an input file, never fetched here. Two steps, as for collections:

1. `exporters/fetch-entity-pages.sh` GETs the live pages (read-only, paced):
   `library/topics/` and every `library/topics/<t>/` and `.../page/<n>/`.
2. `roomkit parity --topics-from PAGES.tsv --site glassgovernment` turns them
   into the live file (`live_from_pages`), which reads WordPress's markup:

    {
      "site": "glassgovernment", "fetched": "...", "source": "...",
      "index": {"title", "subtitle", "topics": [[slug, label, count], ...]},
      "pages": {"<topic>/<n>": {"crumbs": [...], "eyebrow", "title", "subtitle",
                                "documents": [{"slug", "title", "badge", "date", "collection",
                                               "reading_time", "agency", "summary"}],
                                "pagination": [[kind, label, "<path under the room>"], ...],
                                "jsonld": {...}}},
      "unfetched": {"<path>": <http code>}
    }

The room side is the built room on disk, read into the same shape from its own
markup (templates/room/topics.html, topic.html); its links are read under its
mount, so a staging build compares. `ok` only when every part is equal, every
live page was fetched and is built, and every topic the live topics page lists
has a fetched first page; a room page with no live page is `unchecked`, not ok.

Not compared: the in-topic ?s= form (the room does not render it; parity-matrix.yaml
topics) and the row's heading level (h3 live, h2 in the room, which has no h2 above it).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import collection_parity as CP
from .collection_parity import find, first, text

KEYS = {"site", "fetched", "source", "notes", "index", "pages", "unfetched"}


class TopicParityError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _under(href: str, root: str) -> str:
    """The link's path under the room root ('/library/' live, the mount in the room)."""
    path = unquote(urlsplit(href).path)
    return path.removeprefix(root)


def _jsonld(root: CP.Node) -> dict:
    for s in find(root, "script"):
        if s.attrs.get("type") == "application/ld+json":
            try:
                obj = json.loads("".join(k for k in s.kids if isinstance(k, str)))
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("@type") == "DefinedTerm":
                return obj
    return {}


# --- each side's markup, read into one shape ---------------------------------------

def read_index(html: str, side: str) -> dict:
    root = CP.tree(html)
    if side == "live":
        head = first(root, "div", "ggrr-rr__header")
        cards = [(CP.last_segment(a.attrs.get("href", "")), text(first(a, cls="ggrr-topic-card__label")),
                  text(first(a, cls="ggrr-topic-card__count"))) for a in find(root, "a", "ggrr-topic-card")]
        return {"title": text(first(head, "h1")), "subtitle": text(first(head, cls="ggrr-rr__subtitle")),
                "topics": [list(c) for c in cards]}
    cards = [(a.attrs.get("data-room-topic", ""), text(first(a, cls="room__tcard-label")),
              text(first(a, cls="room__tcard-count"))) for a in find(root, "a", "room__tcard")]
    return {"title": text(first(root, "h1", "room__title")), "subtitle": text(first(root, cls="room__tsub")),
            "topics": [list(c) for c in cards]}


def _live_row(a: CP.Node) -> dict:
    link = first(a, "a", "ggrr-doc-row__link")
    h = first(a, "h3", "ggrr-doc-row__title")
    return {"slug": CP.last_segment(link.attrs.get("href", "")) if link else "",
            "title": text(h, skip=("ggrr-prov-badge",)), "badge": text(first(h, cls="ggrr-prov-badge")),
            "date": text(first(a, cls="ggrr-doc-row__date")), "collection": text(first(a, cls="ggrr-doc-row__collection")),
            "reading_time": text(first(a, cls="ggrr-doc-row__reading-time")),
            "agency": text(first(a, cls="ggrr-doc-row__agency")), "summary": text(first(a, cls="ggrr-doc-row__summary"))}


def _room_row(li: CP.Node) -> dict:
    h = first(li, "h2", "room__trow-title")
    return {"slug": li.attrs.get("data-room-doc", ""), "title": text(h, skip=("room__badge",)),
            "badge": text(first(h, cls="room__badge")), "date": text(first(li, cls="room__trow-date")),
            "collection": text(first(li, cls="room__trow-collection")), "reading_time": text(first(li, cls="room__trow-time")),
            "agency": text(first(li, cls="room__trow-agency")), "summary": text(first(li, cls="room__trow-summary"))}


def _kind(n: CP.Node, side: str) -> str:
    c = n.classes()
    if side == "live":
        return next((k for k in ("prev", "next", "current", "dots") if k in c), "page")
    return next((k for k in ("prev", "next", "current", "dots") if f"room__pager-{k}" in c), "page")


def read_page(html: str, side: str, root_path: str) -> dict:
    root = CP.tree(html)
    if side == "live":
        head = first(root, "div", "ggrr-rr__header")
        crumbs = first(head, "nav", "ggrr-document__breadcrumbs")
        crumb_labels = [text(k) for k in (crumbs.kids if crumbs else []) if isinstance(k, CP.Node) and "sep" not in k.classes()]
        nav = first(root, "nav", "ggrr-pagination")
        items = [k for k in (nav.kids if nav else []) if isinstance(k, CP.Node)]
        return {"crumbs": crumb_labels, "eyebrow": text(first(head, cls="ggrr-rr__eyebrow")), "title": text(first(head, "h1")),
                "subtitle": text(first(head, cls="ggrr-rr__subtitle")),
                "documents": [_live_row(a) for a in find(root, "article", "ggrr-doc-row")],
                "pagination": [[_kind(k, side), text(k), _under(k.attrs["href"], root_path) if "href" in k.attrs else ""]
                               for k in items],
                "jsonld": _jsonld(root)}
    crumbs = first(root, "nav", "room__crumbs")
    nav = first(root, "nav", "room__pager")
    items = [first(li, "a") or first(li, "span") for li in (find(nav, "li") if nav else [])]
    return {"crumbs": [text(li) for li in (find(crumbs, "li") if crumbs else [])],
            "eyebrow": text(first(root, cls="room__eyebrow")), "title": text(first(root, "h1", "room__title")),
            "subtitle": text(first(root, cls="room__tsub")),
            "documents": [_room_row(li) for li in find(root, "li", "room__trow")],
            "pagination": [[_kind(k, side), text(k), _under(k.attrs["href"], root_path) if "href" in k.attrs else ""]
                           for k in items if k is not None],
            "jsonld": _jsonld(root)}


def _key(parts: list[str]) -> str | None:
    """'<topic>/<n>' for topics/<t>/ or topics/<t>/page/<n>/ (parts after the room)."""
    if len(parts) == 2 and parts[0] == "topics":
        return f"{parts[1]}/1"
    if len(parts) == 4 and parts[0] == "topics" and parts[2] == "page" and parts[3].isdigit():
        return f"{parts[1]}/{int(parts[3])}"
    return None


def live_from_pages(site: str, head: dict, pages: dict[str, tuple[int, str]]) -> dict:
    """The live file from fetched pages: the topics page and every topic page."""
    if site != "glassgovernment":
        raise TopicParityError([f"no live topics markup known for site {site!r}"])
    out: dict = {"site": site, **head, "index": None, "pages": {}, "unfetched": {}}
    for path, (code, html) in sorted(pages.items()):
        if code != 200:
            out["unfetched"][path] = code
            continue
        parts = [p for p in path.strip("/").split("/") if p]
        if parts[:1] != ["library"]:
            continue
        if parts == ["library", "topics"]:
            out["index"] = read_index(html, "live")
        elif (k := _key(parts[1:])):
            out["pages"][k] = read_page(html, "live", "/library/")
    return out


def load_live(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TopicParityError([f"{path}: {exc}"]) from exc
    if not isinstance(data, dict) or not set(data) <= KEYS or not isinstance(data.get("pages"), dict):
        raise TopicParityError([f"{path} is not a topics live file (topic_parity.py documents it)"])
    return data


def room_topics(room: Path) -> dict:
    lock = json.loads((room / "room.lock.json").read_text(encoding="utf-8"))
    mount = lock.get("mount") or "/"
    out: dict = {"index": None, "pages": {}}
    ix = room / "topics" / "index.html"
    if ix.is_file():
        out["index"] = read_index(ix.read_text(encoding="utf-8"), "room")
    for p in sorted((room / "topics").rglob("index.html")) if (room / "topics").is_dir() else []:
        k = _key(["topics", *p.parent.relative_to(room / "topics").parts])
        if k:
            out["pages"][k] = read_page(p.read_text(encoding="utf-8"), "room", mount)
    return out


def compare(live: dict, room: dict) -> dict:
    lp, rp = live["pages"], room["pages"]
    pages = {}
    for k in sorted(set(lp) | set(rp)):
        if k not in rp:
            pages[k] = "missing from the room"
        elif k not in lp:
            pages[k] = "unchecked (no live page)"
        elif lp[k] != rp[k]:
            pages[k] = "differs: " + CP._first_diff(lp[k], rp[k], k)
        else:
            pages[k] = "same"
    unpaged = [t[0] for t in (live.get("index") or {}).get("topics", []) if f"{t[0]}/1" not in lp]
    if live.get("index") is None:
        index = "not in the live file"
    elif room.get("index") is None:
        index = "missing from the room"
    else:
        index = "same" if live["index"] == room["index"] else "differs: " + CP._first_diff(live["index"], room["index"], "index")
    ok = all(v == "same" for v in pages.values()) and index == "same" and not live.get("unfetched") and not unpaged
    return {"ok": ok, "fetched": live.get("fetched", ""), "index": index, "pages": pages,
            "same": sum(v == "same" for v in pages.values()), "total": len(pages),
            "unfetched": live.get("unfetched", {}), "unpaged": unpaged}


def run(live_path, room: Path) -> dict:
    if not (room / "room.lock.json").is_file():
        raise TopicParityError([f"{room} is not a built room (no room.lock.json)"])
    return compare(load_live(live_path), room_topics(room))


def text_report(rep: dict) -> str:
    lines = [(f"{'PASSES' if rep['ok'] else 'FAILS'}: topic pages {rep['same']}/{rep['total']} same"
              f"{' (live fetched ' + rep['fetched'] + ')' if rep['fetched'] else ''}"),
             f"   topics page: {rep['index']}"]
    lines += [f"   topics/{k}: {v}" for k, v in rep["pages"].items() if v != "same"]
    lines += [f"   unfetched: {p} ({c})" for p, c in rep["unfetched"].items()]
    lines += [f"   listed on the live topics page, no first page fetched: {s}" for s in rep["unpaged"]]
    return "\n".join(lines)
