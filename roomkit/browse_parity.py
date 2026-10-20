"""parity.facet_pages and parity.sitemaps: the room's no-JS ways in against live.

As for parity.entities, the live side is an input file, never fetched here, so
dd (behind Cloudflare's 429s) can be read through the origin.

**parity.facet_pages** (matrix row index-facet-pages). Live file:

    {
      "site": "deflockdane", "fetched": "<ISO time>", "source": "...",
      "facets": {"agency": {"Green Bay Police Department": ["<slug>", ...]}, ...}
    }

what filtering the live index by each value holds. `roomkit parity --facets-from
INDEX.html --site deflockdane` writes it from the live index page: dd's finder
narrows by the `archiveSearch` docs embedded in `deflockReadingRoomConfig`
(agency, docType, vendors, year). The room side is the built room: each facet
page's `data-room-facet-page` key and the records its cards link to, and the
index's browse block (`data-room-browse`), which must link every facet page.

`ok` only when every live facet is built, with the same values, every value's
page holds the same records, and the index links every page. A room facet live
does not have is `extra`, which is not ok.

**parity.sitemaps** (matrix row sitemaps). Live input: the site's sitemap
provider files as fetched (dd: Yoast's `deflock_rr_document-sitemap.xml` and
`deflock_rr_entity-sitemap.xml`), any number. Only their URLs under the room's
live path count; a URL elsewhere on the site is not the room's. The room side is
the built room's `sitemap.xml`. `ok` when the sets are equal, apart from the
room's own pages no live provider lists: the room's index and its facet pages
(`room_only`, reported, not a difference).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from .view import slugify

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# dd's finder payload (deflock-reading-room, class-deflock-reading-room-shortcode.php
# build_archive_search_payload, read 2026-10-19): its doc keys -> the room's facet names.
DD_KEYS = {"agency": "agency", "docType": "type", "vendors": "vendor", "year": "year"}
DD_CONFIG = re.compile(r"var deflockReadingRoomConfig = (\{.*?\});\s*\n", re.DOTALL)


class BrowseParityError(ValueError):
    """The live file or the room cannot be read as this check needs."""


# --- facet pages -------------------------------------------------------------

def live_from_index(site: str, html: str, fetched: str = "", source: str = "") -> dict:
    """The live file for --facet-pages, from the live index page's markup."""
    if site != "deflockdane":
        raise BrowseParityError(f"no reader for {site!r}'s live index facets (dd only so far)")
    m = DD_CONFIG.search(html)
    if not m:
        raise BrowseParityError("no deflockReadingRoomConfig on the page")
    docs = json.loads(m.group(1)).get("archiveSearch", {}).get("docs")
    if not isinstance(docs, list) or not docs:
        raise BrowseParityError("deflockReadingRoomConfig has no archiveSearch docs")
    facets: dict[str, dict[str, list[str]]] = {name: {} for name in DD_KEYS.values()}
    for d in docs:
        for key, name in DD_KEYS.items():
            vals = d.get(key) if isinstance(d.get(key), list) else [d.get(key)]
            for v in dict.fromkeys(str(x) for x in vals if x not in (None, "")):
                facets[name].setdefault(v, []).append(str(d["slug"]))
    return {"site": site, "fetched": fetched, "source": source,
            "facets": {n: {v: sorted(s) for v, s in sorted(vs.items())} for n, vs in facets.items()}}


class _Room(HTMLParser):
    """A facet page's key and card links, or the index's browse links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.key = ""
        self.cards: list[str] = []
        self.browse: list[str] = []
        self._title = self._browse = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-room-facet-page" in a:
            self.key = a["data-room-facet-page"] or ""
        if "data-room-browse" in a:
            self._browse = True
        cls = (a.get("class") or "").split()
        if tag == "h3" and "room__card-title" in cls:
            self._title = True
        elif tag == "a" and self._title:
            self.cards.append(a.get("href") or "")
        elif tag == "a" and self._browse:
            self.browse.append(a.get("href") or "")

    def handle_endtag(self, tag):
        if tag == "h3":
            self._title = False
        elif tag == "nav":
            self._browse = False


def _parse(path: Path) -> _Room:
    p = _Room()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def _mount(room: Path) -> str:
    lock = room / "room.lock.json"
    if not lock.is_file():
        raise BrowseParityError(f"{room}: no room.lock.json (not a built room)")
    return json.loads(lock.read_text())["mount"]


def room_facets(room: Path) -> dict:
    """The built room's facet pages: {name: {value-slug: [record slugs]}} and the
    index's browse links (room-relative paths)."""
    at = _mount(room)
    facets: dict[str, dict[str, list[str]]] = {}
    for page in sorted(room.glob("*/*/index.html")):
        p = _parse(page)
        if not p.key:
            continue
        name, slug = p.key.split("/", 1)
        facets.setdefault(name, {})[slug] = sorted(h[len(at):].strip("/") for h in p.cards if h.startswith(at))
    index = _parse(room / "index.html")
    return {"facets": facets, "linked": sorted(h[len(at):] for h in index.browse if h.startswith(at))}


def compare_facets(live: dict, room: dict) -> dict:
    rf, diffs = room["facets"], []
    linked = set(room["linked"])
    for name, values in sorted(live["facets"].items()):
        built = rf.get(name)
        if built is None:
            diffs.append({"kind": "missing-facet", "facet": name})
            continue
        want = {slugify(v): (v, sorted(s)) for v, s in values.items()}
        for s in sorted(set(want) - set(built)):
            diffs.append({"kind": "missing-value", "facet": name, "value": want[s][0]})
        for s in sorted(set(built) - set(want)):
            diffs.append({"kind": "extra-value", "facet": name, "value": s})
        for s in sorted(set(want) & set(built)):
            v, members = want[s]
            if built[s] != members:
                diffs.append({"kind": "members", "facet": name, "value": v,
                              "missing": sorted(set(members) - set(built[s])),
                              "extra": sorted(set(built[s]) - set(members))})
    for name in sorted(set(rf) - set(live["facets"])):
        diffs.append({"kind": "extra-facet", "facet": name})
    for name, built in sorted(rf.items()):
        for s in sorted(built):
            if f"{name}/{s}/" not in linked:
                diffs.append({"kind": "unlinked", "facet": name, "value": s})
    pages = sum(len(v) for v in rf.values())
    return {"check": "facet_pages", "site": live.get("site", ""), "fetched": live.get("fetched", ""),
            "facets": {n: len(v) for n, v in sorted(rf.items())}, "pages": pages,
            "differences": diffs, "ok": not diffs}


def load_live_facets(path: Path) -> dict:
    live = json.loads(path.read_text())
    f = live.get("facets") if isinstance(live, dict) else None
    if not (isinstance(f, dict) and all(isinstance(vs, dict) and all(isinstance(s, list) for s in vs.values())
                                        for vs in f.values())):
        raise BrowseParityError(f"{path}: not a facet-pages live file (browse_parity.py documents it)")
    return live


def run_facets(live_path: Path, room: Path) -> dict:
    return compare_facets(load_live_facets(live_path), room_facets(room))


# --- sitemaps ----------------------------------------------------------------

def locs(xml: bytes | str, where: str = "") -> list[str]:
    # A sitemap never has a DOCTYPE; refusing one shuts out entity expansion
    # (stdlib expat, no defusedxml in the gate's environment).
    if b"<!DOCTYPE" in (xml.encode() if isinstance(xml, str) else xml).upper():
        raise BrowseParityError(f"{where}: has a DOCTYPE; a sitemap does not")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise BrowseParityError(f"{where}: not XML ({exc})") from exc
    if root.tag != NS + "urlset":
        raise BrowseParityError(f"{where}: not a urlset (a sitemap index? pass its provider files)")
    return [(u.findtext(NS + "loc") or "").strip() for u in root.findall(NS + "url")]


def _canonical(html: str) -> str:
    m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    if not m:
        raise BrowseParityError("the room's index.html has no canonical link")
    return m.group(1)


def run_sitemaps(live_files: list[Path], room: Path) -> dict:
    sm = room / "sitemap.xml"
    if not sm.is_file():
        raise BrowseParityError(f"{room}: no sitemap.xml (pack features.sitemaps off?)")
    room_urls = locs(sm.read_bytes(), str(sm))
    root = _canonical((room / "index.html").read_text(encoding="utf-8"))
    facet_urls = {root + n + "/" + s + "/" for n, vs in room_facets(room)["facets"].items() for s in vs}
    live_all = [u for f in live_files for u in locs(f.read_bytes(), str(f))]
    live = {u for u in live_all if u.startswith(root)}
    own = {root} | facet_urls
    rs = set(room_urls)
    missing = sorted(live - rs)
    extra = sorted(rs - live - own)
    dupes = sorted({u for u in room_urls if room_urls.count(u) > 1})
    return {"check": "sitemaps", "room": root, "live_files": [str(f) for f in live_files],
            "live": len(live), "outside_room": len(set(live_all) - live), "room_urls": len(rs),
            "room_only": len(own & rs), "missing": missing, "extra": extra, "duplicates": dupes,
            "ok": not (missing or extra or dupes)}


# --- text --------------------------------------------------------------------

def text(rep: dict) -> str:
    if rep["check"] == "sitemaps":
        head = (f"parity.sitemaps {'OK' if rep['ok'] else 'DIFFERENT'}: live {rep['live']} under {rep['room']} "
                f"({rep['outside_room']} elsewhere, ignored), room {rep['room_urls']} "
                f"({rep['room_only']} the room's own: index and facet pages)")
        body = [f"   missing {u}" for u in rep["missing"]] + [f"   extra {u}" for u in rep["extra"]] \
            + [f"   duplicate {u}" for u in rep["duplicates"]]
        return "\n".join([head, *body])
    head = (f"parity.facet_pages {'OK' if rep['ok'] else 'DIFFERENT'}: {rep['pages']} pages, "
            + ", ".join(f"{n} {c}" for n, c in rep["facets"].items()))
    body = []
    for d in rep["differences"]:
        line = f"   {d['kind']} {d['facet']}" + (f" {d['value']!r}" if "value" in d else "")
        if d["kind"] == "members":
            line += f": missing {d['missing']} extra {d['extra']}"
        body.append(line)
    return "\n".join([head, *body])
