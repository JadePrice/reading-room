"""Facet pages and the sitemap: the room's ways in that need no JavaScript.

Two pack switches, each off by default so a pack that does not ask changes no byte:

`features.facet-pages` (matrix row index-facet-pages): one page per value of
each facet the manifest's `site.index.browse` names, at
`<room>/<facet>/<value-slug>/`, listing every record whose `index.browse` holds
that value, in manifest order, as the index's cards. The index links them all
in a "browse" block (folded per facet), so a reader without JavaScript can
narrow the list. The heading is the site's (`title`, `{value}` filled in);
roomkit composes no label.

`features.sitemaps` (matrix row sitemaps): `sitemap.xml` at the room's root,
every page the room serves, by its live canonical URL (the room, each record,
the entity index and pages when the entities switch is on, each facet page).
No lastmod: the build is deterministic and the manifest has no modified time
to give.

Refusals (raised by `render`, so nothing is written): a facet named like a
record slug or a path the room already serves, a value with no ASCII slug, two
values of one facet that slug the same, a record listed under a facet the site
does not browse.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from . import entities as E
from . import topics as TP
from .view import slugify

FACETS = "facet-pages"
SITEMAPS = "sitemaps"
SITEMAP = "sitemap.xml"
RESERVED = E.RESERVED | {SITEMAP, "entity", "entities", "citations.json"}


def facet_pages_on(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FACETS))


def sitemap_on(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(SITEMAPS))


def _declared(m) -> list[dict]:
    return (m.site.index.get("browse") or {}).get("facets", [])


def problems(m) -> list[str]:
    """Why the manifest's browse block cannot be built, if it cannot."""
    out = []
    declared = _declared(m)
    names = {f["name"] for f in declared}
    taken = RESERVED | {d.slug for d in m.documents} | {p.split("/", 1)[0] for p in E.served(m.entities)}
    out += [f"browse facet {n!r} is already a path in the room" for n in sorted(names & taken)]
    for d in m.documents:
        extra = set(d.index.get("browse", {})) - names
        out += [f"{d.slug}: index.browse names {n!r}, which site.index.browse does not" for n in sorted(extra)]
    for f in declared:
        seen: dict[str, str] = {}
        for d in m.documents:
            for v in d.index.get("browse", {}).get(f["name"], []):
                if not re.search(r"[a-z0-9]", v.lower()):
                    out.append(f"{d.slug}: browse {f['name']} value {v!r} has no slug")
                    continue
                s = slugify(v)
                if seen.setdefault(s, v) != v:
                    out.append(f"browse {f['name']}: {seen[s]!r} and {v!r} are both {s!r}")
    return sorted(set(out))


def pages(m) -> list[dict]:
    """Every facet page, facets in the site's order, values sorted (years newest first)."""
    out = []
    for f in _declared(m):
        members: dict[str, list] = {}
        for d in m.documents:
            for v in dict.fromkeys(d.index.get("browse", {}).get(f["name"], [])):
                if v.strip():
                    members.setdefault(v, []).append(d)
        order = sorted(members, reverse=True) if f["name"] == "year" else sorted(members, key=lambda v: (v.casefold(), v))
        for v in order:
            s = slugify(v)
            out.append({"name": f["name"], "label": f["label"], "value": v, "slug": s,
                        "path": f"{f['name']}/{s}/", "title": f["title"].replace("{value}", v),
                        "room_only": bool(f.get("room_only")),
                        "docs": members[v]})
    return out


def roots(facet_pages: list[dict]) -> list[dict]:
    """One page per facet at `<room>/<facet>/`, listing its values (never in the sitemap)."""
    out: dict[str, dict] = {}
    for p in facet_pages:
        f = out.setdefault(p["name"], {"name": p["name"], "label": p["label"], "path": p["name"] + "/", "values": []})
        f["values"].append({"label": p["value"], "slug": p["slug"], "count": len(p["docs"])})
    return list(out.values())


def heading(m) -> str:
    return (m.site.index.get("browse") or {}).get("heading", "")


def urls(m, facet_pages: list[dict]) -> list[str]:
    """Every served page by its live URL: the room, records, entities, collections, topics
    (first pages: the site's provider lists no /page/N/), facet pages."""
    room = m.site.base_url + m.site.room_path
    out = [room] + [f"{room}{d.slug}/" for d in m.documents]
    if m.entities:
        if m.entities.get("index"):
            out.append(m.entities["index"]["url"])
        out += [p["url"] for p in m.entities["pages"]]
    if getattr(m, "collections", None):
        if m.collections.get("index"):
            out.append(m.collections["index"]["url"])
        out += [p["url"] for p in m.collections["pages"]]
    if getattr(m, "topics", None):
        if m.topics.get("index"):
            out.append(m.topics["index"]["url"])
        out += TP.sitemap_urls(m.topics)
    out += [room + p["path"] for p in facet_pages]
    return out


def sitemap_xml(locs: list[str]) -> str:
    rows = "".join(f"<url><loc>{escape(u)}</loc></url>\n" for u in locs)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "</urlset>\n")
