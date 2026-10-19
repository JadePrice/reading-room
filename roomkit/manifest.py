"""The manifest a static reading room is built from, and the rows it refuses.

A manifest is what a site exports about its public documents (read-only
`wp eval-file`, or later Civica). roomkit trusts nothing in it it can check:
every refusal names the row and the reason, and any refusal fails the build.
A refused row is never dropped quietly; a reading room missing a record it
should hold is the failure this kit exists to prevent.

    {
      "site": {"name": "deflockdane.org", "title": "Reading Room",
               "base_url": "https://deflockdane.org", "room_path": "/reading-room/"},
      "documents": [{
        "slug": "...", "title": "...", "visibility": "public",
        "citation": "<the site's own citation text, verbatim>",
        "agency": "...", "date": "2025-01-31", "summary": "...",      (optional)
        "archive_url": "https://archive.org/details/...",            (optional)
        "file": {"url": "...", "download_url": "...", "sha256": "<64 hex>",
                 "bytes": 123, "ext": "pdf", "mime": "application/pdf",
                 "view_url": "...", "poster_url": "..."},                (both optional)
        "pages": [{"n": 1, "text": "...", "provenance": "ocr",
                   "cite": {...}}, ...]                               (optional; cite: passages.py)
        "document_id": 505,         (optional; the site's id, for passage citations)
        "search_text": "...",       (optional; only when there are no pages)
        "display": {                                                   (optional, all keys optional)
          "breadcrumbs": [{"label", "url"?}],      the last one is this page
          "eyebrow": {"label", "url"?}, "badge": "...", "badge_kind": "<slug>",
          "released": "...",
          "notice": {"heading", "body", "report"?},
          "details": [{"label", "value", "url"?, "code"?, "note"?}],
          "notes": "...",
          "groups": [{"heading", "blurb"?, "style": "chips"|"list",
                      "items": [{"label", "url"?, "kind"?, "quote"?, "meta"?}]}],
          "jsonld": {...}},
        "index": {"group": "...", "card_date": "...", "thumb_url": "...",
                  "meta": ["..."], "facets": {"<name>": "<value>"}}   (optional)
      }],
      "excluded": [{"slug": "...", "problem": "..."}],                 (optional)
      "entities": {"index": {...}, "pages": [...]}                     (optional; entities.py)
      "passages": {"api": "...", "citations": [...]}                   (optional; passages.py)
    }

`site.template` names the site's pack (roomkit/packs/<site>/): its
colors, fonts, labels and layout for the one shared page template
(roomkit/templates/room/).
`site.index` is the index copy: {eyebrow, title, lede, groups: [ordered group
names], group_label, links: [{label, url, text}], facets: [{name, label}],
empty_group_text}. `display` and `index` on a document are what the template
shows, already formatted by the site's own helpers: roomkit formats no dates
and composes no labels.

`search_text` is a record's text for corpus search alone, for a record the
site can search but cannot export page by page (no complete 1..N run of
pages). It is indexed (search.py) and never shown: no pages.json, no reader
search, no page anchors. A row with both `pages` and `search_text` is refused,
so a record's text has one source.

`entities` is the site's entity index and entity pages, every word and every
list already as the site writes it (the shape and its refusals: entities.py).
A problem in it is a refusal like a bad row's.

`passages`, `document_id` and a page's `cite` are GG's passage citations: the
passage route, the page-level citation text and the curated citations, all as
the site writes them (passages.py). Refused the same way.

`excluded` is the exporter saying out loud which public records it could not
export and why. roomkit names them on every build, check and status.

The citation comes from the site, never from here: roomkit does not compose
citations, so a static page and the WordPress page cannot disagree about one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import entities as E
from . import passages as PS

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

PDF = {"pdf"}
IMAGE = {"jpg", "jpeg", "png", "gif", "webp"}
TABLE = {"csv", "tsv"}
TEXT = {"txt", "md", "json", "xml", "html"}
READER = PDF | IMAGE | TABLE | TEXT
# No reader module: the page offers the download and the citation, nothing inline.
DOWNLOAD_ONLY = {"zip", "xlsx", "xls", "docx", "doc", "pptx", "tiff", "tif"}
EXTS = READER | DOWNLOAD_ONLY


class ManifestError(ValueError):
    """The manifest as a whole cannot be read (not a single bad row)."""


@dataclass(frozen=True)
class Page:
    n: int
    text: str
    provenance: str = ""
    cite: dict | None = field(default=None, compare=False)   # passages.py; the site's page citation
    image_url: str = ""
    boxes: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Document:
    slug: str
    title: str
    citation: str
    file_url: str
    download_url: str
    sha256: str
    ext: str
    mime: str
    bytes: int | None = None
    view_url: str = ""
    poster_url: str = ""
    agency: str = ""
    date: str = ""
    summary: str = ""
    archive_url: str = ""
    pages: tuple[Page, ...] = ()
    search_text: str = ""
    document_id: int | None = None
    display: dict = field(default_factory=dict, compare=False)
    index: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Site:
    name: str
    title: str
    base_url: str
    room_path: str
    template: str = ""
    index: dict = field(default_factory=dict, compare=False)


@dataclass
class Manifest:
    site: Site
    documents: list[Document]
    refusals: list[tuple[str, str]] = field(default_factory=list)  # (row id, reason)
    excluded: list[tuple[str, str]] = field(default_factory=list)  # (slug, problem), from the exporter
    entities: dict | None = field(default=None, compare=False)       # entities.parse's output, or None
    passages: dict | None = field(default=None, compare=False)       # passages.parse's output, or None


def _url_ok(u: str) -> bool:
    # https, or a path on the same host. Anything else (javascript:, data:,
    # plain http) would end up in an href on a public page.
    return u.startswith("https://") or (u.startswith("/") and not u.startswith("//"))


def _str(row: dict, key: str) -> str:
    v = row.get(key, "")
    return v.strip() if isinstance(v, str) else ""


def _is_int(v: object) -> bool:
    """Return True if v is an int and strictly not a boolean."""
    return isinstance(v, int) and not isinstance(v, bool)


def validate_room_path(path: str, field_name: str = "site.room_path") -> str:
    """Validate that a room path or mount is a safe absolute web path.

    Rejects protocol-relative URLs (//host/), backslashes, query strings,
    hash fragments, and relative dot segments.
    """
    if not (isinstance(path, str) and path.startswith("/") and path.endswith("/")):
        raise ManifestError(f"{field_name} must start and end with '/': {path!r}")
    if path.startswith("//"):
        raise ManifestError(f"{field_name} cannot start with '//' (protocol-relative URL): {path!r}")
    if "\\" in path:
        raise ManifestError(f"{field_name} cannot contain backslashes: {path!r}")
    if "?" in path or "#" in path:
        raise ManifestError(f"{field_name} cannot contain query parameters or fragments: {path!r}")
    parts = path.strip("/").split("/")
    if any(p in (".", "..") for p in parts):
        raise ManifestError(f"{field_name} cannot contain dot segments ('.' or '..'): {path!r}")
    return path


def _site(raw: object) -> Site:
    if not isinstance(raw, dict):
        raise ManifestError("manifest has no 'site' object")
    name, title, base, path = (_str(raw, k) for k in ("name", "title", "base_url", "room_path"))
    if not (name and title and base and path):
        raise ManifestError("site needs name, title, base_url and room_path")
    if not base.startswith("https://") or base.endswith("/"):
        raise ManifestError(f"site.base_url must be https:// with no trailing slash: {base!r}")
    path = validate_room_path(path, "site.room_path")
    template = _str(raw, "template")
    if template and not SLUG.match(template):
        raise ManifestError(f"site.template {template!r} is not a slug")
    index = raw.get("index") or {}
    if not isinstance(index, dict):
        raise ManifestError("site.index is not an object")
    groups = index.get("groups", [])
    if not (isinstance(groups, list) and all(isinstance(c, str) for c in groups)):
        raise ManifestError("site.index.groups is not a list of strings")
    for key in ("eyebrow", "title", "lede", "group_label", "empty_group_text"):
        if not isinstance(index.get(key, ""), str):
            raise ManifestError(f"site.index.{key} is not a string")
    for ln in index.get("links", []) if isinstance(index.get("links", []), list) else [None]:
        if not (isinstance(ln, dict) and isinstance(ln.get("label"), str) and isinstance(ln.get("url"), str)
                and _url_ok(ln["url"])):
            raise ManifestError("site.index.links entries need a label and an https:// or same-host url")
    facets = index.get("facets", [])
    if not (isinstance(facets, list) and all(isinstance(f, dict) and SLUG.match(str(f.get("name", "")))
                                             and isinstance(f.get("label"), str) for f in facets)):
        raise ManifestError("site.index.facets entries need a slug name and a label")
    return Site(name, title, base, path, template, index)


def _href(u: object, where: str) -> str:
    if not isinstance(u, str) or (u and not _url_ok(u)):
        return f"{where} URL {u!r} is not https:// or a same-host path"
    return ""


def _labelled(items: object, where: str, value: bool = False) -> str:
    if not isinstance(items, list):
        return f"{where} is not a list"
    for it in items:
        if not (isinstance(it, dict) and isinstance(it.get("label"), str)):
            return f"a {where} entry has no label"
        if value and not isinstance(it.get("value"), str):
            return f"a {where} entry has no string value"
        for k in ("kind", "quote", "meta", "note"):
            if not isinstance(it.get(k, ""), str):
                return f"{where}.{k} is not a string"
        why = _href(it.get("url", ""), where)
        if why:
            return why
    return ""


def _display(raw: object) -> tuple[dict, str]:
    """The template's display block, checked: strings where strings go, safe hrefs."""
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "display is not an object"
    for key in ("released", "notes", "badge", "badge_sr"):
        if not isinstance(raw.get(key, ""), str):
            return {}, f"display.{key} is not a string"
    if raw.get("badge_kind") and not (isinstance(raw["badge_kind"], str) and SLUG.match(raw["badge_kind"])):
        return {}, "display.badge_kind is not a slug"
    why = (_labelled(raw.get("breadcrumbs", []), "display.breadcrumbs")
           or _labelled(raw.get("details", []), "display.details", value=True))
    if why:
        return {}, why
    eb = raw.get("eyebrow")
    if eb is not None:
        why = _labelled([eb], "display.eyebrow")
        if why:
            return {}, why
    notice = raw.get("notice")
    if notice is not None and not (isinstance(notice, dict) and isinstance(notice.get("heading"), str)
                                   and isinstance(notice.get("body"), str)
                                   and isinstance(notice.get("report", ""), str)):
        return {}, "display.notice is not {heading, body, report?} strings"
    groups = raw.get("groups", [])
    if not isinstance(groups, list):
        return {}, "display.groups is not a list"
    for g in groups:
        if not (isinstance(g, dict) and isinstance(g.get("heading"), str) and isinstance(g.get("blurb", ""), str)
                and g.get("style", "list") in ("chips", "list")):
            return {}, "a display.groups entry is not {heading, blurb?, style: chips|list, items}"
        why = _labelled(g.get("items", []), "display.groups.items")
        if why:
            return {}, why
    if not isinstance(raw.get("jsonld", {}), dict):
        return {}, "display.jsonld is not an object"
    hdr = raw.get("header")
    if hdr is not None:
        if not isinstance(hdr, dict):
            return {}, "display.header is not an object"
        if "meta" in hdr and not (isinstance(hdr["meta"], list) and all(isinstance(x, str) for x in hdr["meta"])):
            return {}, "display.header.meta is not a list of strings"
        for k in ("original_url", "ia_url", "category"):
            if k in hdr and not isinstance(hdr[k], str):
                return {}, f"display.header.{k} is not a string"
        if "ia_pending" in hdr and not isinstance(hdr["ia_pending"], bool):
            return {}, "display.header.ia_pending is not a bool"
    return raw, ""


def _index(raw: object) -> tuple[dict, str]:
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k, ""), str) for k in ("group", "card_date", "thumb_url")):
        return {}, "index is not {group, card_date, thumb_url} strings"
    if not (isinstance(raw.get("meta", []), list) and all(isinstance(x, str) for x in raw.get("meta", []))):
        return {}, "index.meta is not a list of strings"
    facets = raw.get("facets", {})
    if not (isinstance(facets, dict) and all(SLUG.match(k) and isinstance(v, str) for k, v in facets.items())):
        return {}, "index.facets is not {slug: string}"
    if raw.get("thumb_url") and not _url_ok(raw["thumb_url"]):
        return {}, f"index.thumb_url {raw['thumb_url']!r} is not https:// or a same-host path"
    return raw, ""


def _document(row: dict) -> tuple[Document | None, str]:
    """A Document, or None and the reason it is refused."""
    if not isinstance(row, dict):
        return None, "not an object"
    if row.get("visibility") != "public":
        # Only public records may be exported at all. One that is not public
        # here means the exporter is wrong, so this is a refusal, not a skip.
        return None, f"visibility is {row.get('visibility')!r}, not 'public'"
    slug = _str(row, "slug")
    if not SLUG.match(slug):
        return None, f"slug {slug!r} is not lowercase letters, digits and single hyphens"
    title, citation = _str(row, "title"), _str(row, "citation")
    if not title:
        return None, "no title"
    if not citation:
        return None, "no citation (it must come from the site, verbatim)"
    f = row.get("file")
    if not isinstance(f, dict):
        return None, "no file"
    url, dl, sha = _str(f, "url"), _str(f, "download_url"), _str(f, "sha256").lower()
    ext, mime = _str(f, "ext").lower().lstrip("."), _str(f, "mime")
    if not (url and dl):
        return None, "file needs both url and download_url"
    view, poster = _str(f, "view_url"), _str(f, "poster_url")
    for u in (url, dl, view, poster):
        if u and not _url_ok(u):
            return None, f"file URL {u!r} is not https:// or a same-host path"
    if not SHA256.match(sha):
        return None, "file.sha256 is not 64 hex characters"
    if ext not in EXTS:
        return None, f"file.ext {ext!r} is neither a reader type nor a known download-only type"
    if not mime:
        return None, "file.mime is empty"
    size = f.get("bytes")
    if size is not None and (not _is_int(size) or size < 0):
        return None, "file.bytes is not a non-negative integer"
    date = _str(row, "date")
    if date and not DATE.match(date):
        return None, f"date {date!r} is not YYYY, YYYY-MM or YYYY-MM-DD"
    archive = _str(row, "archive_url")
    if archive and not archive.startswith("https://"):
        return None, f"archive_url {archive!r} is not https://"
    pages_raw = row.get("pages") or []
    if not isinstance(pages_raw, list):
        return None, "pages is not a list"
    pages = []
    for p in pages_raw:
        if not isinstance(p, dict) or not _is_int(p.get("n")) or not isinstance(p.get("text", ""), str):
            return None, "a page is not {n: int, text: str}"
        if "cite" in p and PS.cite_problem(p["cite"]):
            return None, f"page {p['n']}: {PS.cite_problem(p['cite'])}"
        img_url = _str(p, "image_url")
        if img_url and not _url_ok(img_url):
            return None, f"page {p['n']} image_url {img_url!r} is not https:// or a same-host path"
        boxes_raw = p.get("boxes")
        boxes: list[dict] = []
        if boxes_raw is not None:
            if not isinstance(boxes_raw, list):
                return None, f"page {p['n']} boxes is not a list"
            for b_idx, b in enumerate(boxes_raw):
                if not isinstance(b, dict):
                    return None, f"page {p['n']} box #{b_idx} is not an object"
                coord = b.get("box")
                if not (isinstance(coord, (list, tuple)) and len(coord) == 4
                        and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coord)):
                    return None, f"page {p['n']} box #{b_idx} coord must be 4 numbers [ymin, xmin, ymax, xmax]"
                ymin, xmin, ymax, xmax = [float(c) for c in coord]
                if not (0.0 <= ymin < ymax <= 1.0 and 0.0 <= xmin < xmax <= 1.0):
                    return None, f"page {p['n']} box #{b_idx} coord out of bounds or inverted: {coord}"
                b_text = b.get("text", "")
                if not isinstance(b_text, str):
                    return None, f"page {p['n']} box #{b_idx} text is not a string"
                b_conf = b.get("confidence")
                if b_conf is not None and not (isinstance(b_conf, (int, float)) and not isinstance(b_conf, bool) and 0.0 <= float(b_conf) <= 1.0):
                    return None, f"page {p['n']} box #{b_idx} confidence must be a number between 0 and 1 or null"
                boxes.append(b)
        pages.append(Page(p["n"], p.get("text", ""), _str(p, "provenance"), p.get("cite"), img_url, tuple(boxes)))
    if [p.n for p in pages] != list(range(1, len(pages) + 1)):
        return None, "page numbers are not 1..N in order"
    search_text = row.get("search_text", "")
    if not isinstance(search_text, str):
        return None, "search_text is not a string"
    if search_text and pages:
        return None, "search_text is only for a record with no pages"
    doc_id = row.get("document_id")
    if doc_id is not None and not (_is_int(doc_id) and doc_id >= 1):
        return None, "document_id is not a positive integer"
    if view and ext not in PDF:
        return None, "file.view_url is only for PDFs"
    display, why = _display(row.get("display"))
    if why:
        return None, why
    index, why = _index(row.get("index"))
    if why:
        return None, why
    return Document(slug, title, citation, url, dl, sha, ext, mime, size, view, poster,
                    _str(row, "agency"), date, _str(row, "summary"), archive, tuple(pages),
                    search_text.strip(), doc_id, display, index), ""


def parse(data: object) -> Manifest:
    if not isinstance(data, dict):
        raise ManifestError("manifest is not a JSON object")
    site = _site(data.get("site"))
    rows = data.get("documents")
    if not isinstance(rows, list):
        raise ManifestError("manifest has no 'documents' list")
    m = Manifest(site, [])
    seen: set[str] = set()
    for i, row in enumerate(rows):
        rid = row.get("slug") if isinstance(row, dict) and isinstance(row.get("slug"), str) else f"#{i}"
        doc, why = _document(row)
        if doc is None:
            m.refusals.append((rid, why))
        elif doc.slug in seen:
            m.refusals.append((rid, "duplicate slug"))
        else:
            seen.add(doc.slug)
            m.documents.append(doc)
    ex = data.get("excluded") or []
    if not isinstance(ex, list) or not all(isinstance(e, dict) and _str(e, "slug") and _str(e, "problem") for e in ex):
        raise ManifestError("'excluded' must be a list of {slug, problem}")
    m.excluded = [(_str(e, "slug"), _str(e, "problem")) for e in ex]
    m.entities, problems = E.parse(data.get("entities"), site.base_url, site.room_path, seen)
    m.refusals += [("entities", why) for why in problems]
    m.passages, problems = PS.parse(data.get("passages"), {d.slug: d for d in m.documents}, dict(m.excluded))
    m.refusals += [("passages", why) for why in problems]
    return m


def load(path: Path | str) -> Manifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    return parse(data)
