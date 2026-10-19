"""parity.entities: does the room hold the site's entities, as the site lists them?

Matrix rows `entities-index` (GG) and `entity-page` (dd and GG): the same entity
set, the same grouping on the index, and per entity the same documents in the
same order, plus GG's "appears alongside" list in its order. Every entity is
compared, not a sample.

The live side is an input file, never fetched here, so dd (behind Cloudflare's
429s) can be read through the origin and GG politely from anywhere. Two steps:

1. `exporters/fetch-entity-pages.sh` GETs the live pages (read-only, paced) and
   prints `# fetched <ISO time> <how>` and one `<path>\t<code>\t<base64 html>`
   line per page.
2. `roomkit parity --entities-from PAGES.tsv --site S` turns those pages into the
   live file (`live_from_pages`), the format below. It reads WordPress's markup,
   so it knows each site's classes; nothing here is used to build the room.

    {
      "site": "glassgovernment",                       (one of parity.SITES)
      "fetched": "2026-10-15T09:00:00Z", "source": "...", "notes": "..."?,
      "entities": ["vendor/axon", ...],                the live set: GG's index, dd's
                                                       entity sitemap (Yoast)
      "index": [{"type": "vendor", "heading": "Vendors",
                 "entities": ["vendor/flock-safety", ...]}],   (GG only)
      "pages": {"vendor/axon": {"documents": ["<slug>", ...],     in page order
                                "alongside": ["program/draft-one", ...]}},  (GG only)
      "unfetched": {"<path>": <http code>}             (optional: pages that did not answer 200)
    }

The room side is the built room on disk: the entity pages' `data-room-entity-page`,
`data-room-doc` and `data-room-entity` attributes, and the index's
`data-room-entity-group` sections (templates/room/entity.html, entities.html).

`ok` only when the sets are equal, the index agrees (types, headings, entities
and their order), every live page was fetched and is built, and every page's
documents and alongside list are equal in order. A room page with no live page
to compare is `unchecked`, which is not ok: every row, not a sample.
"""

from __future__ import annotations

import base64
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

KEYS = {"site", "fetched", "source", "notes", "entities", "index", "pages", "unfetched"}
ENTITY_PATH = re.compile(r"/entity/([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")

# Each WordPress room's markup (read 2026-10-15 from the live GG pages and from
# deflock-reading-room 3ab6ca4's templates/entity-reading-room.php).
LIVE_MARKUP = {
    "glassgovernment": {"doc": ("a", "ggrr-rr-row__link"), "alongside": ("ul", "ggrr-entity__also-list"),
                        "group_heading": ("h2", "ggrr-entities-group__title"),
                        "group_count": "ggrr-entities-group__n", "card": ("a", "ggrr-topic-card")},
    "deflockdane": {"doc": ("li", "deflock-reading-room__entity-row"), "alongside": None,
                    "group_heading": None, "group_count": None, "card": None},
}


class EntityParityError(ValueError):
    """The live file cannot be used as written. Every problem is listed."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def key_of(url: str) -> str:
    """`vendor/axon` from an entity page URL, or ''."""
    m = ENTITY_PATH.search(urlsplit(url).path)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def slug_of(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    return parts[-1] if parts else ""


# --- reading HTML ---------------------------------------------------------------------

class _Collector(HTMLParser):
    """Walks a page once and records, in document order, what `markup` names: the
    hrefs of links that match (an <a> with the class, or a link inside an element
    with it), heading text (minus a count span), and the room's own data-room-*
    attributes."""

    VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "base", "col", "embed", "track"}

    def __init__(self, markup: dict):
        super().__init__(convert_charrefs=True)
        self.mk = markup
        self.stack: list[tuple[str, set[str]]] = []
        self.events: list[tuple[str, str]] = []   # (kind, value), in document order
        self._heading: list[str] | None = None
        self._hdepth = 0
        self._skipdepth = 0

    def _inside(self, tag: str, cls: str) -> bool:
        return any(t == tag and cls in c for t, c in self.stack)

    def _heading_starts(self, tag: str, cls: set[str]) -> bool:
        gh = self.mk.get("group_heading")
        if gh:
            return tag == gh[0] and gh[1] in cls
        # The room's index: the h2 of each data-room-entity-group section.
        return tag == "h2" and self._inside("section", "room__egroup")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        if tag not in self.VOID:
            self.stack.append((tag, cls))
        if self._heading is None and self._heading_starts(tag, cls):
            self._heading, self._hdepth = [], len(self.stack)
        elif self._heading is not None and not self._skipdepth and self.mk.get("group_count") in cls:
            self._skipdepth = len(self.stack)
        if tag == "a" and a.get("href"):
            for kind in ("doc", "alongside", "card"):
                sel = self.mk.get(kind)
                if sel and ((sel[0] == "a" and sel[1] in cls) or (sel[0] != "a" and self._inside(*sel))):
                    self.events.append((kind, a["href"]))
        for k in ("data-room-entity-group", "data-room-entity-page", "data-room-doc", "data-room-entity"):
            if a.get(k):
                self.events.append((k, a[k]))
        if tag == "section" and "room__alongside" in cls:
            self.events.append(("room-alongside", ""))
        if tag == "div" and "room__edocs" in cls:
            self.events.append(("room-edocs", ""))

    def handle_endtag(self, tag):
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            t, _ = self.stack.pop()
            if self._skipdepth and len(self.stack) < self._skipdepth:
                self._skipdepth = 0
            if self._heading is not None and len(self.stack) < self._hdepth:
                self.events.append(("heading", " ".join("".join(self._heading).split())))
                self._heading = None
            if t == tag:
                break

    def handle_data(self, data):
        if self._heading is not None and not self._skipdepth:
            self._heading.append(data)


class _RoomCollector(_Collector):
    def __init__(self):
        super().__init__({"group_count": "room__section-n"})


def _events(html: str, markup: dict) -> list[tuple[str, str]]:
    c = _Collector(markup)
    c.feed(html)
    c.close()
    return c.events


# --- the live side --------------------------------------------------------------------

def read_pages_tsv(path) -> tuple[dict, dict[str, tuple[int, str]]]:
    """The fetch script's output: its header ({fetched, source}) and {path: (code, html)}."""
    head: dict = {}
    pages: dict[str, tuple[int, str]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# fetched "):
            _, _, rest = line.partition("# fetched ")
            when, _, how = rest.partition(" ")
            head = {"fetched": when, "source": how}
        elif line.strip() and not line.startswith("#"):
            p, code, b64 = (line.split("\t") + ["", ""])[:3]
            pages[p] = (int(code or 0), base64.b64decode(b64).decode("utf-8", "replace"))
    if not head:
        raise EntityParityError([f"{path} has no '# fetched <time> <how>' line (exporters/fetch-entity-pages.sh writes one)"])
    return head, pages


def live_from_pages(site: str, head: dict, pages: dict[str, tuple[int, str]]) -> dict:
    """The live file from fetched pages: sitemap XML, the GG index, entity pages."""
    if site not in LIVE_MARKUP:
        raise EntityParityError([f"no live markup known for site {site!r}"])
    mk = LIVE_MARKUP[site]
    out: dict = {"site": site, **head, "entities": [], "pages": {}}
    sitemap: list[str] = []
    index: list[dict] | None = None
    unfetched = {}
    for path, (code, html) in sorted(pages.items()):
        if code != 200:
            unfetched[path] = code
            continue
        if path.endswith(".xml"):
            sitemap += [k for k in (key_of(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", html)) if k]
        elif path.rstrip("/").endswith("entities"):
            index = []
            for kind, val in _events(html, mk):
                if kind == "heading":
                    index.append({"type": "", "heading": val, "entities": []})
                elif kind == "card" and index:
                    k = key_of(val)
                    index[-1]["entities"].append(k)
                    index[-1]["type"] = index[-1]["type"] or k.split("/")[0]
        elif key_of(path):
            ev = _events(html, mk)
            page = {"documents": [slug_of(v) for kind, v in ev if kind == "doc"]}
            if mk["alongside"]:
                page["alongside"] = [key_of(v) for kind, v in ev if kind == "alongside"]
            out["pages"][key_of(path)] = page
    if index is not None:
        out["index"] = index
        out["entities"] = list(dict.fromkeys(k for g in index for k in g["entities"]))
    elif sitemap:
        out["entities"] = list(dict.fromkeys(sitemap))
    else:
        out["entities"] = list(out["pages"])
    if unfetched:
        out["unfetched"] = unfetched
    return out


def parse_live(data: object, sites: tuple[str, ...]) -> dict:
    if not isinstance(data, dict):
        raise EntityParityError(["the live file is not a mapping"])
    problems = [f"unknown key {k!r}" for k in sorted(set(data) - KEYS, key=str)]
    problems += [f"missing {k!r}" for k in ("site", "fetched", "source", "entities", "pages") if k not in data]
    if "site" in data and data["site"] not in sites:
        problems.append(f"unknown site {data['site']!r}")
    for k in ("fetched", "source"):
        if k in data and not (isinstance(data[k], str) and data[k].strip()):
            problems.append(f"{k} is not text")
    ents = data.get("entities", [])
    if not (isinstance(ents, list) and all(isinstance(k, str) and KEY.match(k) for k in ents)):
        problems.append("entities is not a list of '<type>/<slug>'")
    idx = data.get("index")
    if idx is not None and not (isinstance(idx, list) and all(
            isinstance(g, dict) and isinstance(g.get("type"), str) and isinstance(g.get("heading"), str)
            and isinstance(g.get("entities"), list) and all(isinstance(k, str) and KEY.match(k) for k in g["entities"])
            for g in idx)):
        problems.append("index is not a list of {type, heading, entities: ['<type>/<slug>']}")
    pages = data.get("pages", {})
    if not isinstance(pages, dict):
        problems.append("pages is not a mapping of '<type>/<slug>' -> {documents, alongside?}")
    else:
        for k, p in pages.items():
            if not (KEY.match(k) and isinstance(p, dict) and set(p) <= {"documents", "alongside"}
                    and isinstance(p.get("documents"), list) and all(isinstance(s, str) for s in p["documents"])
                    and all(isinstance(s, str) and KEY.match(s) for s in p.get("alongside", []))):
                problems.append(f"pages[{k!r}] is not {{documents: [slug], alongside?: ['<type>/<slug>']}}")
    uf = data.get("unfetched", {})
    if not (isinstance(uf, dict) and all(isinstance(c, int) for c in uf.values())):
        problems.append("unfetched is not {path: http code}")
    if problems:
        raise EntityParityError(problems)
    return data


def load_live(path, sites: tuple[str, ...]) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EntityParityError([f"cannot read {path}: {exc}"]) from exc
    return parse_live(data, sites)


# --- the room side --------------------------------------------------------------------

def room_entities(room: Path) -> dict:
    """What the built room holds: {entities, index?, pages}, read from its HTML."""
    lock = json.loads((room / "room.lock.json").read_text(encoding="utf-8"))
    out: dict = {"entities": [], "pages": {}}
    for rel in sorted(lock["files"]):
        if not rel.endswith("/index.html"):
            continue
        html = (room / rel).read_text(encoding="utf-8")
        if 'class="room room--entity"' in html:
            ev = _events(html, {})
            page_key = next(v for kind, v in ev if kind == "data-room-entity-page")
            alongside, docs, where = [], [], ""
            for kind, v in ev:
                if kind == "room-alongside":
                    where = "alongside"
                elif kind == "room-edocs":
                    where = "docs"
                elif kind == "data-room-entity" and where == "alongside":
                    alongside.append(v)
                elif kind == "data-room-doc":
                    docs.append(v)
            out["pages"][page_key] = {"documents": docs, "alongside": alongside}
        elif 'class="room room--entities"' in html:
            c = _RoomCollector()
            c.feed(html)
            index: list[dict] = []
            for kind, v in c.events:
                if kind == "data-room-entity-group":
                    index.append({"type": v, "heading": "", "entities": []})
                elif kind == "heading" and index and not index[-1]["heading"]:
                    index[-1]["heading"] = v
                elif kind == "data-room-entity" and index:
                    index[-1]["entities"].append(v)
            out["index"] = index
    out["entities"] = sorted(out["pages"])
    return out


# --- comparing ------------------------------------------------------------------------

def _list_diff(live: list[str], room: list[str]) -> dict:
    return {"equal": live == room,
            "missing": [x for x in live if x not in room], "extra": [x for x in room if x not in live],
            "order_only": live != room and sorted(live) == sorted(room)}


def compare(live: dict, room: dict) -> dict:
    """Pure: the live file against the room's own entities."""
    lset, rset = set(live["entities"]), set(room["entities"])
    rep: dict = {"set": {"live": len(lset), "room": len(rset), "missing": sorted(lset - rset),
                         "extra": sorted(rset - lset)}}
    ok = lset == rset
    if live.get("index") is not None:
        ri = room.get("index")
        if ri is None:
            rep["index"] = {"ok": False, "problems": ["the room has no entity index"]}
        else:
            probs = []
            lt, rt = [g["type"] for g in live["index"]], [g["type"] for g in ri]
            if lt != rt:
                probs.append(f"groups {lt} live, {rt} in the room")
            for lg, rg in zip(live["index"], ri):
                if lg["heading"] != rg["heading"]:
                    probs.append(f"{lg['type']}: heading {lg['heading']!r} live, {rg['heading']!r} in the room")
                d = _list_diff(lg["entities"], rg["entities"])
                if not d["equal"]:
                    probs.append(f"{lg['type']}: entities differ (missing {d['missing']}, extra {d['extra']}"
                                 f"{', order only' if d['order_only'] else ''})")
            rep["index"] = {"ok": not probs, "problems": probs}
        ok = ok and rep["index"]["ok"]
    rows = []
    for k in sorted(set(live["pages"]) | set(room["pages"])):
        lp, rp = live["pages"].get(k), room["pages"].get(k)
        if lp is None:
            rows.append({"key": k, "ok": False, "problem": "unchecked: no live page to compare"})
            continue
        if rp is None:
            rows.append({"key": k, "ok": False, "problem": "not built in the room"})
            continue
        row = {"key": k, "documents": _list_diff(lp["documents"], rp["documents"])}
        if "alongside" in lp:
            row["alongside"] = _list_diff(lp["alongside"], rp["alongside"])
        row["ok"] = row["documents"]["equal"] and row.get("alongside", {"equal": True})["equal"]
        rows.append(row)
    rep["pages"] = rows
    rep["unfetched"] = live.get("unfetched", {})
    rep["ok"] = ok and all(r["ok"] for r in rows) and not rep["unfetched"]
    return rep


def run(live_path, room: Path, sites: tuple[str, ...]) -> dict:
    live = load_live(live_path, sites)
    if not (room / "room.lock.json").is_file():
        raise EntityParityError([f"{room} is not a built room (no room.lock.json)"])
    got = room_entities(room)
    if not got["pages"]:
        raise EntityParityError([f"{room} has no entity pages (built without the pack's features.entities?)"])
    return {"site": live["site"], "fetched": live["fetched"], "source": live["source"], **compare(live, got)}


def text(rep: dict) -> str:
    s = rep["set"]
    good = sum(1 for r in rep["pages"] if r["ok"])
    lines = [f"{'AGREES' if rep['ok'] else 'DIFFERS'}: {good}/{len(rep['pages'])} entity pages agree; "
             f"{s['live']} entities live, {s['room']} in the room ({rep['site']}, live read {rep['fetched']})"]
    lines += [f"   missing from the room: {k}" for k in s["missing"]]
    lines += [f"   in the room, not live: {k}" for k in s["extra"]]
    if "index" in rep:
        lines += [f"   index: {p}" for p in rep["index"]["problems"]]
    for r in rep["pages"]:
        if r["ok"]:
            continue
        if "problem" in r:
            lines.append(f"   {r['key']}: {r['problem']}")
            continue
        for part in ("documents", "alongside"):
            d = r.get(part)
            if d and not d["equal"]:
                lines.append(f"   {r['key']} {part}: " + ("same set, different order" if d["order_only"]
                                                         else f"missing {d['missing']}, extra {d['extra']}"))
    lines += [f"   live page did not answer 200: {p} ({c})" for p, c in sorted(rep["unfetched"].items())]
    return "\n".join(lines)
