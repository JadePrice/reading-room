"""parity.collections: does the room hold the site's collections, as the site shows them?

Matrix rows `collections-index`, `collection-page` and `index-collections-grid`
(GG): the same categories, groups and collections in the same order with the same
counts and spans on the collections page; per collection the same heading block,
notice, records in order (with their numbers, sizes and badges) and JSON-LD; and
on the index the same table of eras, groups and rows with the same sources and
descriptions. Every collection is compared, not a sample.

The live side is an input file, never fetched here. Two steps, as for entities:

1. `exporters/fetch-entity-pages.sh` GETs the live pages (read-only, paced):
   `library/`, `library/collections/` and every `library/collection/<key>/`.
2. `roomkit parity --collections-from PAGES.tsv --site glassgovernment` turns
   them into the live file (`live_from_pages`), which reads WordPress's markup:

    {
      "site": "glassgovernment", "fetched": "...", "source": "...",
      "index": [{"heading", "stamp", "groups": [{"heading",
                 "collections": [{"slug", "title", "years", "count", "blurb"}]}]}],
      "pages": {"<key>": {"title", "count", "stamp", "years", "lede",
                          "notice": [heading, body, report] or [],
                          "documents": ["<slug>", ...], "nums": [...], "sizes": [...],
                          "badges": ["Final|Provenance: Government record", ...],
                          "jsonld": {...}}},
      "grid": [{"heading", "groups": [{"heading",
                "rows": [{"slug", "title", "years", "sources", "blurb"}]}]}],
      "unfetched": {"<path>": <http code>}
    }

The room side is the built room on disk, read into the same shape from its own
markup (templates/room/collections.html, collection.html,
partials/collections-grid.html). `ok` only when every part is equal and every
live collection page was fetched and is built; a room page with no live page to
compare is `unchecked`, which is not ok.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import entity_parity as EP

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
KEYS = {"site", "fetched", "source", "notes", "index", "pages", "grid", "unfetched"}


class CollectionParityError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --- a small tree, enough to read two sites' markup by class ------------------------

class Node:
    __slots__ = ("attrs", "kids", "tag")

    def __init__(self, tag: str, attrs: dict):
        self.tag, self.attrs, self.kids = tag, attrs, []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].kids.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def tree(html: str) -> Node:
    t = _Tree()
    t.feed(html)
    return t.root


def find(n: Node, tag: str | None = None, cls: str | None = None, attr: str | None = None) -> list[Node]:
    out = []
    for k in n.kids:
        if isinstance(k, Node):
            if (tag is None or k.tag == tag) and (cls is None or cls in k.classes()) and (attr is None or attr in k.attrs):
                out.append(k)
            out.extend(find(k, tag, cls, attr))
    return out


def first(n: Node | None, tag: str | None = None, cls: str | None = None, attr: str | None = None) -> Node | None:
    if n is None:
        return None
    got = find(n, tag, cls, attr)
    return got[0] if got else None


def text(n: Node | None, skip: tuple[str, ...] = ()) -> str:
    """The node's text, whitespace collapsed, without children that have a class in `skip`."""
    if n is None:
        return ""
    parts: list[str] = []

    def walk(x):
        for k in x.kids:
            if isinstance(k, str):
                parts.append(k)
            elif k.tag not in ("script", "style") and not (k.classes() & set(skip)):
                walk(k)
    walk(n)
    return " ".join("".join(parts).split())


def last_segment(url: str) -> str:
    return unquote(urlsplit(url).path).rstrip("/").rsplit("/", 1)[-1]


def _jsonld(root: Node) -> dict:
    for s in find(root, "script"):
        if s.attrs.get("type") == "application/ld+json":
            try:
                obj = json.loads("".join(k for k in s.kids if isinstance(k, str)))
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("@type") == "Collection":
                return obj
    return {}


# --- each side's markup, read into one shape ---------------------------------------

MARKUP = {
    "live": {
        "cat": ("section", "ggrr-cat"), "cat_h": ("h2", "ggrr-cat__title"), "stamp": "ggrr-cat__stamp",
        "group": ("div", "ggrr-group"), "group_h": ("h3", "ggrr-group__title"),
        "card": ("li", "ggrr-folder-card"), "card_link": ("a", "ggrr-ledger__link"),
        "card_years": "ggrr-ledger__years", "card_count": "ggrr-ledger__count", "card_blurb": "ggrr-folder-card__blurb",
        "title": ("h1", "ggrr-hub__title"), "count": "ggrr-hub__count", "years": "ggrr-ledger__years",
        "lede": ("ggrr-collection__blurb", "ggrr-index__intro"),
        "notice": ("aside", "ggrr-sensitivity"), "notice_report": "ggrr-sensitivity__report",
        "file": ("a", "ggrr-fileitem"), "num": "ggrr-fileitem__num", "size": "ggrr-fileitem__size",
        "badges": ("ggrr-fileitem__final", "ggrr-prov-badge"),
        "table": ("table", "gg-card__grid"), "era": "gg-card__era", "grp": "gg-card__group", "row": "gg-card__row",
        "row_name": "gg-card__coll", "row_years": "gg-card__col-period", "row_src": "gg-card__col-sources",
        "row_blurb": "gg-card__col-blurb", "row_skip": ("gg-card__coll-sources",),
    },
    "room": {
        "cat": ("section", "room__ccat"), "cat_h": ("h2", None), "stamp": "room__stamp",
        "group": ("div", "room__cgroup"), "group_h": ("h3", None),
        "card": ("li", "room__ccard"), "card_link": ("a", None),
        "card_years": "room__cyears", "card_count": "room__ccount", "card_blurb": "room__blurb",
        "title": ("h1", "room__title"), "count": "room__ccount", "years": "room__cyears",
        "lede": ("room__lede",),
        "notice": ("aside", "room__notice"), "notice_report": "room__notice-report",
        "file": ("a", "room__file"), "num": "room__file-num", "size": "room__file-size",
        "badges": ("room__badge",),
        "table": ("table", "room__cgrid-table"), "era": "room__cgrid-era", "grp": "room__cgrid-group", "row": None,
        "row_name": "room__cgrid-name", "row_years": "room__cgrid-period", "row_src": "room__cgrid-src",
        "row_blurb": "room__cgrid-blurb", "row_skip": ("room__cgrid-srcline",),
    },
}


def read_index(html: str, side: str) -> list[dict]:
    mk = MARKUP[side]
    root = tree(html)
    out = []
    for cat in find(root, *mk["cat"]):
        h = first(cat, *mk["cat_h"])
        groups = []
        for g in find(cat, *mk["group"]):
            cards = []
            for li in find(g, *mk["card"]):
                a = first(li, *mk["card_link"])
                cards.append({"slug": last_segment(a.attrs.get("href", "")) if a else "", "title": text(a),
                              "years": text(first(li, None, mk["card_years"])),
                              "count": text(first(li, None, mk["card_count"])),
                              "blurb": text(first(li, "p", mk["card_blurb"]))})
            groups.append({"heading": text(first(g, *mk["group_h"])), "collections": cards})
        out.append({"heading": text(h, (mk["stamp"],)), "stamp": text(first(cat, None, mk["stamp"])), "groups": groups})
    return out


def read_page(html: str, side: str) -> dict:
    mk = MARKUP[side]
    root = tree(html)
    head = first(root, "header", "ggrr-hub__head" if side == "live" else "room__head")
    lede = ""
    for cls in mk["lede"]:
        lede = lede or text(first(head, "p", cls))
    notice = first(root, *mk["notice"])
    nb = []
    if notice is not None:
        ps = find(notice, "p")
        rep = first(notice, "p", mk["notice_report"])
        nb = [text(first(notice, "h2")), text(next((p for p in ps if p is not rep), None)), text(rep)]
    files = find(root, *mk["file"])
    badges = []
    for a in files:
        bs = []
        for cls in mk["badges"]:
            bs += [text(b) for b in find(a, "span", cls)]
        badges.append("|".join(bs))
    return {"title": text(first(root, *mk["title"])), "count": text(first(head, "p", mk["count"])),
            "stamp": text(first(head, "span", mk["stamp"])), "years": text(first(head, "span", mk["years"])),
            "lede": lede, "notice": nb,
            "documents": [last_segment(a.attrs.get("href", "")) for a in files],
            "nums": [text(first(a, "span", mk["num"])) for a in files],
            "sizes": [text(first(a, "span", mk["size"])) for a in files],
            "badges": badges, "jsonld": _jsonld(root)}


def read_grid(html: str, side: str) -> list[dict] | None:
    mk = MARKUP[side]
    table = first(tree(html), *mk["table"])
    if table is None:
        return None
    eras: list[dict] = []
    for tr in find(table, "tr"):
        c = tr.classes()
        if mk["era"] in c:
            eras.append({"heading": text(tr), "groups": []})
        elif mk["grp"] in c:
            if not eras:
                eras.append({"heading": "", "groups": []})
            eras[-1]["groups"].append({"heading": text(tr), "rows": []})
        elif (mk["row"] in c) if mk["row"] else ("data-room-collection" in tr.attrs):
            if not eras or not eras[-1]["groups"]:
                raise CollectionParityError([f"{side} grid: a row before any group heading"])
            name = first(tr, "td", mk["row_name"])
            a = first(name, "a")
            eras[-1]["groups"][-1]["rows"].append({
                "slug": last_segment(a.attrs.get("href", "")) if a else "", "title": text(a),
                "years": text(first(tr, "td", mk["row_years"])), "sources": text(first(tr, "td", mk["row_src"])),
                "blurb": text(first(tr, "td", mk["row_blurb"]))})
    return eras


# --- the live file -------------------------------------------------------------------

read_pages_tsv = EP.read_pages_tsv


def live_from_pages(site: str, head: dict, pages: dict[str, tuple[int, str]]) -> dict:
    """The live file from fetched pages: the index (for the table), the collections
    page and each collection page."""
    if site != "glassgovernment":
        raise CollectionParityError([f"no live collections markup known for site {site!r}"])
    out: dict = {"site": site, **head, "index": None, "pages": {}, "grid": None, "unfetched": {}}
    for path, (code, html) in sorted(pages.items()):
        if code != 200:
            out["unfetched"][path] = code
            continue
        parts = [p for p in path.strip("/").split("/") if p]
        if parts == ["library"]:
            out["grid"] = read_grid(html, "live")
        elif parts == ["library", "collections"]:
            out["index"] = read_index(html, "live")
        elif len(parts) == 3 and parts[:2] == ["library", "collection"]:
            out["pages"][parts[2]] = read_page(html, "live")
    return out


def load_live(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CollectionParityError([f"{path}: {exc}"]) from exc
    if not isinstance(data, dict) or not set(data) <= KEYS or not isinstance(data.get("pages"), dict):
        raise CollectionParityError([f"{path} is not a collections live file (collection_parity.py documents it)"])
    return data


# --- the room --------------------------------------------------------------------------

def room_collections(room: Path) -> dict:
    lock = json.loads((room / "room.lock.json").read_text(encoding="utf-8"))
    out: dict = {"index": None, "pages": {}, "grid": None, "mount": lock.get("mount")}
    ix = room / "collections" / "index.html"
    if ix.is_file():
        out["index"] = read_index(ix.read_text(encoding="utf-8"), "room")
    for p in sorted((room / "collection").glob("*/index.html")) if (room / "collection").is_dir() else []:
        out["pages"][p.parent.name] = read_page(p.read_text(encoding="utf-8"), "room")
    if (room / "index.html").is_file():
        out["grid"] = read_grid((room / "index.html").read_text(encoding="utf-8"), "room")
    return out


def _first_diff(live, room, where: str = "") -> str:
    """Where two values first differ, as a short path and both values."""
    if type(live) is not type(room):
        return f"{where}: live {live!r} | room {room!r}"
    if isinstance(live, dict):
        for k in sorted(set(live) | set(room)):
            if live.get(k) != room.get(k):
                return _first_diff(live.get(k), room.get(k), f"{where}.{k}")
    if isinstance(live, list):
        for i, (a, b) in enumerate(zip(live, room)):
            if a != b:
                return _first_diff(a, b, f"{where}[{i}]")
        if len(live) != len(room):
            return f"{where}: live has {len(live)}, room {len(room)}"
    return f"{where}: live {live!r} | room {room!r}"


def compare(live: dict, room: dict) -> dict:
    lp, rp = live["pages"], room["pages"]
    pages = {}
    for k in sorted(set(lp) | set(rp)):
        if k not in rp:
            pages[k] = "missing from the room"
        elif k not in lp:
            pages[k] = "unchecked (no live page)"
        elif lp[k] != rp[k]:
            pages[k] = "differs: " + _first_diff(lp[k], rp[k], k)
        else:
            pages[k] = "same"
    listed = [c["slug"] for cat in (live.get("index") or []) for g in cat["groups"] for c in g["collections"]]
    unpaged = [s for s in listed if s not in lp]
    parts = {}
    for part in ("index", "grid"):
        if live.get(part) is None:
            parts[part] = "not in the live file"
        elif room.get(part) is None:
            parts[part] = "missing from the room"
        else:
            parts[part] = "same" if live[part] == room[part] else "differs: " + _first_diff(live[part], room[part], part)
    ok = (all(v == "same" for v in pages.values()) and all(v == "same" for v in parts.values())
          and not live.get("unfetched") and not unpaged)
    return {"ok": ok, "fetched": live.get("fetched", ""), "parts": parts, "pages": pages,
            "same": sum(v == "same" for v in pages.values()), "total": len(pages),
            "unfetched": live.get("unfetched", {}), "unpaged": unpaged}


def run(live_path, room: Path) -> dict:
    if not (room / "room.lock.json").is_file():
        raise CollectionParityError([f"{room} is not a built room (no room.lock.json)"])
    return compare(load_live(live_path), room_collections(room))


def text_report(rep: dict) -> str:
    lines = [(f"{'PASSES' if rep['ok'] else 'FAILS'}: collection pages {rep['same']}/{rep['total']} same"
              f"{' (live fetched ' + rep['fetched'] + ')' if rep['fetched'] else ''}")]
    lines += [f"   {part}: {v}" for part, v in rep["parts"].items()]
    lines += [f"   collection/{k}/: {v}" for k, v in rep["pages"].items() if v != "same"]
    lines += [f"   unfetched: {p} ({c})" for p, c in rep["unfetched"].items()]
    lines += [f"   listed on the live collections page, no live page fetched: {s}" for s in rep["unpaged"]]
    return "\n".join(lines)
