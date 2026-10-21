"""Entities: the manifest's `entities` block, its refusals, and the paths it serves.

Turned on by a pack's `features.entities` (off unless the pack says so; plan
2026-10-13-unified-reading-room-frontend, Task 7; matrix rows entities-index,
entity-page). The pages are built only when the pack turns the feature on and
the manifest carries the block: `gate()` is the one place that decides, and a
build with the switch off never sees the block, so nothing it renders changes.

Every word on an entity page comes from the export, already written by the
site's own helpers and templates (the exporters repeat each formula and name
it): headings, counts, the eyebrow, the "appears alongside" note, the JSON-LD.
roomkit composes no heading, label or relationship, and does not re-order or
re-group anything. The lists arrive in the site's order:

    "entities": {
      "index": {                                 (optional: the site's entity index)
        "url": "<base_url><room_path>entities/",
        "head_title": "...", "title": "...",
        "back": {"label", "url"}, "crumbs": [{"label", "url"?}],     (optional)
        "eyebrow": "...", "lede": "...", "note": "...",              (optional)
        "description": "...", "stats": [{"figure", "label"}],        (optional)
        "empty_text": "...",
        "groups": [{"type": "<slug>", "heading": "...", "count": "...",
                    "entities": [{"type", "slug", "label", "count"?, "url"}]}]
      },
      "pages": [{
        "type": "<slug>", "slug": "<slug>",
        "url": "<base_url><room_path>.../<type>/<slug>/",
        "head_title": "...", "title": "...", "empty_text": "...",
        "description", "eyebrow", "lede", "note", "back", "crumbs", "stats"  (optional, as above)
        "alongside": {"heading", "note"?, "count_sr"?,               (optional)
                      "items": [{"type", "slug", "label", "kind"?, "count"?, "url"}]},
        "documents_heading": "...", "documents_heading_hidden": bool,  (optional)
        "groups": [{"heading": "...",
                    "documents": [{"slug", "title", "url",
                                   "badge"?, "badge_kind"?, "badge_sr"?, "meta"?}]}],
        "jsonld": {...}                                              (optional)
      }],
      "source": {"<plugin file>": "<sha256>"}       (optional; the files the exporter's
                                                     formulas repeat, as read on the host;
                                                     not rendered)
    }

Paths are the live ones: a page's URL must sit under the site's room path,
every segment a slug, and end in `<type>/<slug>/` (dd
`/reading-room/entity/<type>/<slug>/`, GG `/library/entity/<type>/<slug>/` and
`/library/entities/`). The static tree serves each at the same path under the
mount.

Refused (as manifest refusals, so the whole build stops): a malformed block, a
URL outside the room path or not made of slugs, a page URL that does not end
in its own `<type>/<slug>/`, a path whose first segment is a record's slug or
the room's own (`assets`, `pagefind`), two pages at one URL, a counted string
that is not text, an index or "alongside" entry naming an entity with no page.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import replace
from urllib.parse import unquote, urlsplit

FEATURE = "entities"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED = {"assets", "pagefind", "404.html", "index.html", "room.lock.json"}


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def gate(m, pack: dict):
    """The manifest as the pack lets the room see it: without its entities when the
    pack does not turn them on. Pages, links and the stylesheet all follow this."""
    if getattr(m, "entities", None) and not enabled(pack):
        return replace(m, entities=None)
    return m


def key(type_: str, slug: str) -> str:
    return f"{type_}/{slug}"


def _url_ok(u: object) -> bool:
    # https, or a path on the same host. A backslash or a control character is
    # refused too: browsers strip tabs and newlines and read "/\\host" as "//host",
    # so "/\\evil.example" would leave the site from a same-host-looking href.
    return (isinstance(u, str) and not any(c == "\\" or c <= " " or c == "\x7f" for c in u)
            and (u.startswith("https://") or (u.startswith("/") and not u.startswith("//"))))


def _text(v: object, optional: bool = False) -> bool:
    return isinstance(v, str) and (optional or v.strip() != "")


def rel_path(url: str, room: str) -> str:
    """`entity/vendor/axon/` from the page's live URL, or '' if it is not under `room`
    as slug segments."""
    if not url.startswith(room):
        return ""
    rest = url[len(room):]
    segs = rest.split("/")
    if not rest.endswith("/") or len(segs) < 2 or not all(SLUG.match(s) for s in segs[:-1]):
        return ""
    return rest


def _links(items: object, where: str, problems: list[str], need_url: bool = False) -> None:
    if not isinstance(items, list):
        problems.append(f"{where} is not a list")
        return
    for it in items:
        if not (isinstance(it, dict) and _text(it.get("label"))):
            problems.append(f"a {where} entry has no label")
        elif ("url" in it or need_url) and not _url_ok(it.get("url")):
            problems.append(f"{where} URL {it.get('url')!r} is not https:// or a same-host path")


def _strings(obj: dict, keys: tuple[str, ...], where: str, problems: list[str], optional: bool) -> None:
    for k in keys:
        if (k in obj or not optional) and not _text(obj.get(k), optional):
            problems.append(f"{where}.{k} is {'not text' if optional else 'missing or empty'}")


def _common(p: dict, where: str, problems: list[str]) -> None:
    _strings(p, ("head_title", "title", "empty_text"), where, problems, optional=False)
    _strings(p, ("description", "eyebrow", "lede", "note"), where, problems, optional=True)
    if "back" in p:
        _links([p["back"]], f"{where}.back", problems, need_url=True)
    if "crumbs" in p:
        _links(p["crumbs"], f"{where}.crumbs", problems)
    if "stats" in p and not (isinstance(p["stats"], list) and all(
            isinstance(s, dict) and _text(s.get("figure")) and _text(s.get("label")) for s in p["stats"])):
        problems.append(f"{where}.stats is not a list of {{figure, label}} text")


def _entity_ref(e: object, where: str, problems: list[str]) -> str:
    if not (isinstance(e, dict) and SLUG.match(str(e.get("type", ""))) and SLUG.match(str(e.get("slug", "")))
            and _text(e.get("label")) and _url_ok(e.get("url"))):
        problems.append(f"a {where} entry is not {{type, slug, label, url}} with slug type and slug")
        return ""
    for k in ("count", "kind"):
        if k in e and not _text(e[k], optional=True):
            problems.append(f"{where} {e['type']}/{e['slug']}: {k} is not text")
    return key(e["type"], e["slug"])


def _room_slug(url: str, room: str) -> str | None:
    """The record slug a link into `room` names ('' for the room itself), or None
    for a link to another site. Host case, percent-escapes and dot segments are
    normalized first, so a non-canonical spelling of an internal URL is internal."""
    u, r = urlsplit(url), urlsplit(room)
    if u.netloc and u.netloc.lower().removesuffix(":443") != r.netloc.lower().removesuffix(":443"):
        return None
    path = posixpath.normpath("/" + unquote(u.path).lstrip("/"))
    root = r.path.rstrip("/")
    if path != root and not path.startswith(root + "/"):
        return None
    return path[len(root):].strip("/").split("/", 1)[0]


def _page(p: dict, where: str, problems: list[str], room: str = "", doc_slugs: set[str] | None = None) -> None:
    _common(p, where, problems)
    if "documents_heading" in p and not _text(p["documents_heading"]):
        problems.append(f"{where}.documents_heading is not text")
    if not isinstance(p.get("documents_heading_hidden", False), bool):
        problems.append(f"{where}.documents_heading_hidden is not true/false")
    if "jsonld" in p and not isinstance(p["jsonld"], dict):
        problems.append(f"{where}.jsonld is not an object")
    groups = p.get("groups")
    if not isinstance(groups, list):
        problems.append(f"{where}.groups is not a list")
        groups = []
    for g in groups:
        if not (isinstance(g, dict) and _text(g.get("heading")) and isinstance(g.get("documents"), list)
                and g["documents"]):
            problems.append(f"a {where}.groups entry is not {{heading, documents: [...]}} (non-empty)")
            continue
        for d in g["documents"]:
            if not (isinstance(d, dict) and SLUG.match(str(d.get("slug", ""))) and _text(d.get("title"))
                    and _url_ok(d.get("url"))):
                problems.append(f"a {where} document is not {{slug, title, url}}")
                continue
            # A link into this room must name one of its public records; a link to
            # another site is that site's business.
            named = _room_slug(d["url"], room)
            if doc_slugs is not None and named is not None and (named not in doc_slugs or named != d["slug"]):
                problems.append(f"{where} document {d['slug']!r} is not a public record in this room")
                continue
            _strings(d, ("badge", "badge_sr", "meta"), f"{where} document {d['slug']}", problems, optional=True)
            if d.get("badge_kind") and not SLUG.match(str(d["badge_kind"])):
                problems.append(f"{where} document {d['slug']}: badge_kind is not a slug")
    al = p.get("alongside")
    if al is not None:
        if not (isinstance(al, dict) and _text(al.get("heading")) and isinstance(al.get("items"), list)):
            problems.append(f"{where}.alongside is not {{heading, items}}")
        else:
            _strings(al, ("note", "count_sr"), f"{where}.alongside", problems, optional=True)


def parse(raw: object, base_url: str, room_path: str, doc_slugs: set[str]) -> tuple[dict | None, list[str]]:
    """The checked block (plain dicts, as exported, plus each page's `path`), and
    every problem. A block with problems is not returned."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict) or not set(raw) <= {"index", "pages", "source"}:
        return None, ["entities is not {index?, pages, source?}"]
    src = raw.get("source", {})
    if not (isinstance(src, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in src.items())):
        return None, ["entities.source is not {file: sha256}"]
    room = base_url + room_path
    problems: list[str] = []
    pages = raw.get("pages")
    if not isinstance(pages, list):
        return None, ["entities.pages is not a list"]
    paths: dict[str, str] = {}
    keys: set[str] = set()
    out_pages = []

    def claim(url: object, where: str, tail: str = "") -> str:
        rest = rel_path(url, room) if isinstance(url, str) else ""
        if not rest:
            problems.append(f"{where}: URL {url!r} is not under {room} as slug segments")
            return ""
        if tail and not rest.endswith("/" + tail) and rest != tail:
            problems.append(f"{where}: URL {url!r} does not end in {tail}")
        first = rest.split("/", 1)[0]
        if first in doc_slugs or first in RESERVED:
            problems.append(f"{where}: path {rest} starts with {first!r}, a record's or the room's own path")
        if rest in paths:
            problems.append(f"{where}: {rest} is also {paths[rest]}")
        paths[rest] = where
        return rest

    for p in pages:
        if not (isinstance(p, dict) and SLUG.match(str(p.get("type", ""))) and SLUG.match(str(p.get("slug", "")))):
            problems.append("an entities.pages entry has no slug type and slug")
            continue
        k = key(p["type"], p["slug"])
        where = f"entity {k}"
        if k in keys:
            problems.append(f"{where}: listed twice")
        keys.add(k)
        rest = claim(p.get("url"), where, k + "/")
        _page(p, where, problems, room, doc_slugs)
        out_pages.append({**p, "path": rest})

    index = raw.get("index")
    out_index = None
    if index is not None:
        if not isinstance(index, dict):
            problems.append("entities.index is not an object")
        else:
            rest = claim(index.get("url"), "entities index")
            _common(index, "entities index", problems)
            groups = index.get("groups")
            if not isinstance(groups, list):
                problems.append("entities index.groups is not a list")
                groups = []
            for g in groups:
                if not (isinstance(g, dict) and SLUG.match(str(g.get("type", ""))) and _text(g.get("heading"))
                        and _text(g.get("count", ""), optional=True) and isinstance(g.get("entities"), list)):
                    problems.append("an entities index group is not {type, heading, count?, entities}")
                    continue
                for e in g["entities"]:
                    k = _entity_ref(e, "entities index", problems)
                    if k and k not in keys:
                        problems.append(f"entities index lists {k}, which has no page")
            out_index = {**index, "path": rest}
    for p in out_pages:
        al = p.get("alongside")
        if isinstance(al, dict) and isinstance(al.get("items"), list):
            for e in al["items"]:
                k = _entity_ref(e, f"entity {key(p['type'], p['slug'])} alongside", problems)
                if k and k not in keys:
                    problems.append(f"entity {key(p['type'], p['slug'])} alongside lists {k}, which has no page")
    if problems:
        return None, problems
    return {"index": out_index, "pages": out_pages}, []


def served(block: dict | None) -> set[str]:
    """The room-relative paths the block's pages are served at."""
    if not block:
        return set()
    out = {p["path"] for p in block["pages"]}
    if block.get("index"):
        out.add(block["index"]["path"])
    return out
