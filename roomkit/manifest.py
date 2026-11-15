"""The manifest a static reading room is built from, and the rows it refuses.

A manifest is what a site exports about its public documents (read-only
`wp eval-file`, or later the host application). roomkit trusts nothing in it it can check:
every refusal names the row and the reason, and any refusal fails the build.
A refused row is never dropped quietly; a reading room missing a record it
should hold is the failure this kit exists to prevent.

    {
      "site": {"name": "example.org", "title": "Reading Room",
               "base_url": "https://example.org", "room_path": "/reading-room/"},
      "documents": [{
        "slug": "...", "title": "...", "visibility": "public",
        "citation": "<the site's own citation text, verbatim>",
        "agency": "...", "date": "2025-01-31", "summary": "...",      (optional)
        "archive_url": "https://archive.org/details/...",            (optional)
        "file": {"url": "...", "download_url": "...", "sha256": "<64 hex>",
                 "bytes": 123, "ext": "pdf", "mime": "application/pdf",
                 "view_url": "...", "poster_url": "..."},                (both optional)
                 ("view_sha256": "<64 hex>", optional, only with view_url: the
                  viewing copy's own hash; the lock records it beside the original's)
        "pages": [{"n": 1, "text": "...", "provenance": "ocr",
                   "cite": {...}}, ...]                               (optional; cite: passages.py)
        "document_id": 505,         (optional; the site's id, for passage citations)
        "search_text": "...",       (optional; only when there are no pages)
        "file": null,               (a text-only record: needs search_text or pages; the page
                                     has no reader, buttons or hash row, and shows
                                     display.no_file where the reader would be)
        "display": {                                                   (optional, all keys optional)
          "breadcrumbs": [{"label", "url"?}],      the last one is this page
          "eyebrow": {"label", "url"?}, "badge": "...", "badge_kind": "<slug>",
          "released": "...",
          "notice": {"heading", "body", "report"?},
          "gate": true,                            the reader waits behind the notice for a
                                                   click ("Show document"); needs a notice
          "details": [{"label", "value", "url"?, "code"?, "note"?}],
          "notes": "...", "no_file": "...",
          "groups": [{"heading", "blurb"?, "style": "chips"|"list",
                      "items": [{"label", "url"?, "kind"?, "quote"?, "meta"?}]}],
          "jsonld": {...}},
        "index": {"group": "...", "card_date": "...", "thumb_url": "...",
                  "thumb": {"mime": "image/jpeg", "sha256": "...", "data": "<base64>"},
                  "meta": ["..."], "facets": {"<name>": "<value>"},
                  "browse": {"<name>": ["<value>", ...]},
                  "badge": "...", "badge_kind": "<slug>", "badge_sr": "...",
                  "sort_title": "...",
                  "added": "YYYY-MM-DD", "added_display": "..."}  (optional; sort_title: the text the site sorts
                                         "title" on, as the site renders it; default the title;
                                         added: the day the record went into the catalog, for
                                         the recently added list, pack layout.added)
      }],
      "excluded": [{"slug": "...", "problem": "..."}],                 (optional)
      "entities": {"index": {...}, "pages": [...]}                     (optional; entities.py)
      "collections": {"index": {...}, "pages": [...], "grid": {...}}   (optional; site_collections.py)
      "passages": {"api": "...", "citations": [...]}                   (optional; passages.py)
      "machine_text": {"files": [{"url": "...", "text": "..."}]}        (optional; machine_text.py)
      "topics": {"index": {...}, "pages": [...]}                       (optional; topics.py)
      "head_meta": {"pages": {"<path>": {"title": "...", "meta": [...]}}} (optional; head_meta.py)
      "redirects": [{"from": "agency/fbi/", "to": "agency/federal-bureau-of-investigation/"}]
                                                                       (optional; redirects.py)
    }

`site.template` names the site's pack (roomkit/packs/<site>/): its
colors, fonts, labels and layout for the one shared page template
(roomkit/templates/room/).
`site.index` is the index copy: {eyebrow, title, lede, groups: [ordered group
names], group_label, links: [{label, url, text}], facets: [{name, label}],
empty_group_text, browse, sort: {label, options: [{value, label}]} (value one of default,
date-desc, date-asc, title; a sort other than default lists every card as one flat list, in
document order and then sorted, as site A's live list does), group_sets: [{label,
groups: [names]}] (the group select's optgroups), facets may add multi (the card's values
are its index.browse list) or range (from_label, to_label: two selects, From and To), years: [first, last] (the site's own span, four-digit years;
without it the room shows the span of its dated records)}. `display` and `index` on a document are what the template
shows, already formatted by the site's own helpers: roomkit formats no dates
and composes no labels.

`site.index.browse` is {heading, facets: [{name, label, title}]}: the facets
that get a page per value (pack features.facet-pages; browse.py), each
document's `index.browse` the values it is listed under (a list: a record can
name two vendors). `title` is the page's heading with `{value}` where the value
goes, as the site words it. Separate from `facets`, the finder's selects.
A facet with `"room_only": true` is one the site's own index does not narrow
by, so parity.facet_pages reports its pages instead of comparing them.

`index.badge` is the card's badge as the site words it (`badge_kind` a slug for
its modifier class, `badge_sr` the screen-reader prefix), drawn as the record
page's `display.badge` is.

`index.thumb` is the card's thumbnail itself, so the room serves its own copy
(`assets/thumbs/<slug>.<hash>.<ext>`) instead of pointing at a route only the
site's server answers. Refused unless the bytes decode, hash to `sha256`, are
the image `mime` says (JPEG, PNG or WebP, by their first bytes) and are at most
THUMB_MAX bytes. A row has `thumb` or `thumb_url`, not both.

`site.index.suggest` is the finder's suggestion panel as the site words it
(pack features.corpus-search; room-search.js):

    {"labels": {"top": "Top matches", "recent_docs": "...", "recent_searches": "..."},
     "top": 6,                                      how many top matches to show
     "recent_docs": ["<slug>", ...],                the site's recent documents, its order
     "groups": [{"label": "Try searching", "items": [{"label", "query", "count"?}
                                                    or {"label", "facet", "value", "count"?}],
                 "empty": 6, "typing": 0}],         how many with no text / matching the text
     "rank": [{"slug", "title", "agency", "summary", "date", "year", "doc_type",
               "aliases": [...], "vendors": [...]}]}   optional: what the site's own
                                                    top-match scorer reads, per record

With no text: recent documents, recent searches, then each group with `empty`
items; while typing: top matches, then each group's items whose label or query
holds the text. Choosing an item searches its `query`, or sets the finder's
`facet` select (a name in site.index.facets) to `value`. Without the block the
panel draws its groups from the finder's selects. roomkit composes none of it.
With `rank`, top matches are the site's own field scorer over those rows
(room-search.js `rankDocs`, ported from site B's reading-room plugin's scoreDoc)
instead of Pagefind's relevance; a rank row naming no document is refused.

Or the site's box is one flat list (site A: its plugin's suggest combobox over
its server-side suggest builder), `{"style": "list", ...}`:

    {"style": "list",
     "local": 8,                        titles and collections from the cards, "contains", list order
     "min": 2,                          characters before the ranked half runs (the site's server call)
     "caps": {"entity": 4, "collection": 3, "document": 5, "total": 8},
     "prefix": {"vendor": "Vendor: ", ...},   the label before an entity or collection
     "count": " ({n} documents)",       after a label with a count
     "no_results": {"lead": "Explore popular topics like", "or": "or",
                    "words": ["cointelpro", ...]}}   searches the empty state offers

The ranked half reads the room's own entity index (m.entities), collections
index (m.collections) and document titles: exact, then prefix, then contains;
each kind capped; entity before collection before document at equal rank; more
documents first; then the label, case folded. The list is the cards' items then
the ranked ones, the same type and label once, cut at `total`. A document puts
its title in the box; an entity or collection opens its room page.

`site.index.search_terms` is how the site's own text search reads a query
(site A: its plugin's search terms and sanitize_boolean_query), `{"min": 3, "max": 8}`:
the query lowercased and split on anything but a-z and 0-9, words shorter than
`min` dropped, the first `max` kept, each required. room-search.js gives
Pagefind those words, and lists first the cards whose text holds the whole
query as typed (the site's page shows those rows too); with no word left it
matches the cards' text only, as the site's page does. Without it, Pagefind gets the query as typed (site B keeps that,
the user's call of 2026-10-20).

`site.index.server_search` is the site's own search that works without
JavaScript (pack features.server-search): {action, param, label, placeholder,
button}, the form the site's server answers today (site A `/library/?q=`, site B
`/reading-room/?rr_search=`, both WordPress). The room renders it in a
<noscript> on the index; the answer comes from that URL, not from the room, so
after cutover the host keeps sending those queries to the site's server.
Refused: an action off `base_url`, with a query or fragment, or a param that is
not a plain lowercase name.

`search_text` is a record's text for corpus search alone, for a record the
site can search but cannot export page by page (no complete 1..N run of
pages). It is indexed (search.py) and never shown: no pages.json, no reader
search, no page anchors. A row with both `pages` and `search_text` is refused,
so a record's text has one source.

`entities` is the site's entity index and entity pages, every word and every
list already as the site writes it (the shape and its refusals: entities.py).
A problem in it is a refusal like a bad row's.

`collections` is the site's collections page, one page per collection and the
collections table on the room's index, the same way (site_collections.py). A path
both blocks claim is refused.

`machine_text` is the site's plain-text record index (site A /library/documents.txt),
written by the exporter and served as it is; each link in it must name a record
the room holds (machine_text.py).

`topics` is the site's topics page and every page of every topic, paged as the
site pages them, each record one the room holds (topics.py). A path it shares
with an entity or collection page is refused.

`head_meta` is each page's <title> and meta tags as the site prints them, by the
page's path under the room (head_meta.py). A path the room does not serve is refused.

`passages`, `document_id` and a page's `cite` are site A's passage citations: the
passage route, the page-level citation text and the curated citations, all as
the site writes them (passages.py). Refused the same way.

`excluded` is the exporter saying out loud which public records it could not
export and why. roomkit names them on every build, check and status.

The citation comes from the site, never from here: roomkit does not compose
citations, so a static page and the WordPress page cannot disagree about one.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import entities as E
from . import head_meta as HM
from . import machine_text as MT
from . import passages as PS
from . import redirects as RD
from . import site_collections as CO
from . import topics as TP

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SORTS = ("default", "date-desc", "date-asc", "title")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
SCHEMA_VERSION = "1.0"
SCHEMA_VERSION_RE = re.compile(r"^(?P<major>[1-9]\d*)\.(?P<minor>\d+)$")
LANG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
PROVENANCE_KEYS = {
    "source_url", "issuing_org", "document_date", "acquisition_method",
    "acquired", "source_checked", "source_state", "completeness",
}
ACQUISITION_METHODS = {"records-request", "official-publication", "web-capture", "other"}
SOURCE_STATES = {"live", "changed", "removed", "unknown"}
RELATION_BASES = {"curated", "shared-entity", "shared-collection"}

PDF = {"pdf"}
IMAGE = {"jpg", "jpeg", "png", "gif", "webp"}
TABLE = {"csv", "tsv"}
TEXT = {"txt", "md", "json", "xml", "html"}
READER = PDF | IMAGE | TABLE | TEXT
SNAPSHOT_KINDS = {"html", "wacz"}
# No reader module: the page offers the download and the citation, nothing inline.
DOWNLOAD_ONLY = {"zip", "xlsx", "xls", "docx", "doc", "pptx", "tiff", "tif"}
EXTS = READER | DOWNLOAD_ONLY
# What `file.mime` may say for an extension. A row whose mime disagrees with its
# extension is refused: the reader module is chosen by extension, the browser's
# handling by mime, and a mismatch (a .png served as text/html) is a mislabeled file.
# Extensions not listed here are not checked.
MIMES = {
    "pdf": {"application/pdf"},
    "jpg": {"image/jpeg"}, "jpeg": {"image/jpeg"}, "png": {"image/png"}, "gif": {"image/gif"},
    "webp": {"image/webp"}, "tiff": {"image/tiff"}, "tif": {"image/tiff"},
    "csv": {"text/csv", "application/csv", "text/plain"},
    "tsv": {"text/tab-separated-values", "text/tsv", "text/plain"},
    "txt": {"text/plain"}, "md": {"text/markdown", "text/plain"},
    "json": {"application/json", "text/json", "text/plain"},
    "xml": {"application/xml", "text/xml"}, "html": {"text/html"},
    "zip": {"application/zip", "application/x-zip-compressed"},
}
# Per document: well above the largest live record (site A, 1,530 pages), low enough
# that a hostile or broken export cannot make the build or the reader unbounded.
MAX_PAGES = 5000
MAX_BOXES_PER_PAGE = 5000
BOX_KEYS = {"box", "text", "confidence"}
# index.thumb: mime -> (extension, the file's first bytes).
THUMB_TYPES = {"image/jpeg": ("jpg", b"\xff\xd8\xff"), "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
               "image/webp": ("webp", b"RIFF")}
THUMB_MAX = 256 * 1024


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
    view_sha256: str = ""
    snapshot: dict = field(default_factory=dict, compare=False)
    provenance: dict = field(default_factory=dict, compare=False)
    lang: str = ""
    relations: tuple[dict, ...] = ()

    @property
    def has_file(self) -> bool:
        """Whether the record has a file or a web snapshot to show."""
        return bool(self.file_url or self.snapshot)

    @property
    def is_snapshot(self) -> bool:
        return bool(self.snapshot)


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
    collections: dict | None = field(default=None, compare=False)    # site_collections.parse's output, or None
    passages: dict | None = field(default=None, compare=False)       # passages.parse's output, or None
    machine_text: dict | None = field(default=None, compare=False)   # machine_text.parse's output, or None
    topics: dict | None = field(default=None, compare=False)         # topics.parse's output, or None
    head_meta: dict | None = field(default=None, compare=False)      # head_meta.parse's output, or None
    redirects: tuple = field(default=(), compare=False)             # redirects.parse's (from, to) pairs
    redirect_notes: list = field(default_factory=list, compare=False)  # entries left out, never refusals
    schema_version: str = SCHEMA_VERSION


_url_ok = E._url_ok  # one rule for every href the room renders (entities.py)


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


def _schema_version(raw: object) -> str:
    """Return a supported manifest schema version, defaulting legacy manifests."""
    if raw is None:
        return SCHEMA_VERSION
    if not isinstance(raw, str):
        raise ManifestError("schema_version is not a string")
    match = SCHEMA_VERSION_RE.fullmatch(raw)
    if not match:
        raise ManifestError("schema_version must be major.minor")
    if int(match["major"]) != 1:
        raise ManifestError(f"unsupported schema_version major {match['major']}")
    return raw


def _provenance_problem(raw: object) -> tuple[dict, str]:
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "provenance is not an object"
    extra = sorted(set(raw) - PROVENANCE_KEYS)
    if extra:
        return {}, f"provenance has unsupported keys {extra}"
    out: dict[str, str] = {}
    for key in ("issuing_org", "completeness"):
        if key in raw:
            if not isinstance(raw[key], str) or not raw[key].strip():
                return {}, f"provenance.{key} is not a non-empty string"
            out[key] = raw[key].strip()
    if "source_url" in raw:
        if not isinstance(raw["source_url"], str) or not _url_ok(raw["source_url"]):
            return {}, "provenance.source_url is not an https:// or same-host URL"
        out["source_url"] = raw["source_url"]
    for key in ("document_date", "acquired", "source_checked"):
        if key in raw:
            if not isinstance(raw[key], str) or not DATE.fullmatch(raw[key]):
                return {}, f"provenance.{key} is not YYYY, YYYY-MM or YYYY-MM-DD"
            out[key] = raw[key]
    if "acquisition_method" in raw:
        if raw["acquisition_method"] not in ACQUISITION_METHODS:
            return {}, f"provenance.acquisition_method is not one of {sorted(ACQUISITION_METHODS)}"
        out["acquisition_method"] = raw["acquisition_method"]
    if "source_state" in raw:
        if raw["source_state"] not in SOURCE_STATES:
            return {}, f"provenance.source_state is not one of {sorted(SOURCE_STATES)}"
        out["source_state"] = raw["source_state"]
    return out, ""


def _relations_problem(raw: object) -> tuple[tuple[dict, ...], str]:
    if raw is None:
        return (), ""
    if not isinstance(raw, list):
        return (), "relations is not a list"
    relations: list[dict] = []
    seen: set[str] = set()
    for relation in raw:
        if not isinstance(relation, dict) or not {"slug", "basis"} <= set(relation) or set(relation) - {"slug", "basis", "note"}:
            return (), "relations entries are not {slug, basis, note?}"
        slug, basis = relation["slug"], relation["basis"]
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            return (), "relations.slug is not a slug"
        if slug in seen:
            return (), f"relations names {slug!r} more than once"
        if basis not in RELATION_BASES:
            return (), f"relations.basis is not one of {sorted(RELATION_BASES)}"
        if "note" in relation and (not isinstance(relation["note"], str) or not relation["note"].strip()):
            return (), "relations.note is not a non-empty string"
        seen.add(slug)
        relations.append({k: relation[k].strip() if isinstance(relation[k], str) else relation[k]
                          for k in ("slug", "basis", "note") if k in relation})
    return tuple(relations), ""


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
    back = index.get("back")
    if back is not None and not (isinstance(back, dict) and set(back) == {"label", "url"}
                                 and all(isinstance(v, str) and v for v in back.values())):
        raise ManifestError("site.index.back is not {label, url}")
    yrs = index.get("years")
    if yrs is not None and not (isinstance(yrs, list) and len(yrs) == 2
                                and all(isinstance(y, str) and re.fullmatch(r"\d{4}", y) for y in yrs)
                                and yrs[0] <= yrs[1]):
        raise ManifestError("site.index.years is not [first, last] four-digit years in order")
    for ln in index.get("links", []) if isinstance(index.get("links", []), list) else [None]:
        if not (isinstance(ln, dict) and isinstance(ln.get("label"), str) and isinstance(ln.get("url"), str)
                and _url_ok(ln["url"])):
            raise ManifestError("site.index.links entries need a label and an https:// or same-host url")
    facets = index.get("facets", [])
    if not (isinstance(facets, list) and all(isinstance(f, dict) and SLUG.match(str(f.get("name", "")))
                                             and isinstance(f.get("label"), str) for f in facets)):
        raise ManifestError("site.index.facets entries need a slug name and a label")
    for f in facets:
        if not (isinstance(f.get("multi", False), bool) and isinstance(f.get("range", False), bool)
                and not (f.get("multi") and f.get("range"))):
            raise ManifestError("site.index.facets: multi and range are booleans, and not both")
        if f.get("range") and not (isinstance(f.get("from_label"), str) and isinstance(f.get("to_label"), str)
                                   and f["from_label"] and f["to_label"]):
            raise ManifestError("site.index.facets: a range facet needs from_label and to_label")
    srt = index.get("sort")
    if srt is not None and not (isinstance(srt, dict) and isinstance(srt.get("label"), str) and srt["label"]
                                and isinstance(srt.get("options"), list) and srt["options"]
                                and all(isinstance(o, dict) and o.get("value") in SORTS and isinstance(o.get("label"), str)
                                        and o["label"] for o in srt["options"])
                                and len({o["value"] for o in srt["options"]}) == len(srt["options"])):
        raise ManifestError(f"site.index.sort needs a label and options of {{value in {sorted(SORTS)}, label}}")
    gsets = index.get("group_sets")
    if gsets is not None and not (isinstance(gsets, list)
                                  and all(isinstance(g, dict) and isinstance(g.get("label"), str) and g["label"]
                                          and isinstance(g.get("groups"), list)
                                          and all(isinstance(x, str) for x in g["groups"]) for g in gsets)):
        raise ManifestError("site.index.group_sets is not a list of {label, groups: [string]}")
    browse = index.get("browse")
    if browse is not None:
        bf = browse.get("facets") if isinstance(browse, dict) else None
        if not (isinstance(browse.get("heading") if isinstance(browse, dict) else None, str) and isinstance(bf, list) and bf
                and all(isinstance(f, dict) and SLUG.match(str(f.get("name", ""))) and isinstance(f.get("label"), str)
                        and isinstance(f.get("title"), str) and "{value}" in f["title"]
                        and isinstance(f.get("room_only", False), bool) for f in bf)):
            raise ManifestError("site.index.browse needs a heading and facets of "
                                "{slug name, label, title with {value}, room_only?: bool}")
        if len({f["name"] for f in bf}) != len(bf):
            raise ManifestError("site.index.browse names a facet twice")
    if "suggest" in index:
        why = _suggest_problem(index["suggest"])
        if why:
            raise ManifestError(f"site.index.suggest: {why}")
        names = {f["name"] for f in facets}
        for g in index["suggest"].get("groups", []):
            for it in g["items"]:
                if "facet" in it and it["facet"] not in names:
                    raise ManifestError(f"site.index.suggest: group {g['label']!r} sets the filter {it['facet']!r}, "
                                        "which site.index.facets does not have")
    if "search_terms" in index:
        st = index["search_terms"]
        if not (isinstance(st, dict) and set(st) == {"min", "max"} and _count(st["min"], 1) and _count(st["max"], 1)):
            raise ManifestError("site.index.search_terms is not {min, max}, each 1 to 50")
    if "server_search" in index:
        why = _server_search_problem(index["server_search"], base)
        if why:
            raise ManifestError(f"site.index.server_search: {why}")
    return Site(name, title, base, path, template, index)


PARAM = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _server_search_problem(ss: object, base: str) -> str:
    """Why the no-JS search form cannot be rendered as written, or ""."""
    keys = {"action", "param", "label", "placeholder", "button"}
    if not (isinstance(ss, dict) and set(ss) == keys and all(isinstance(ss[k], str) and ss[k] for k in keys)):
        return f"is not {{{', '.join(sorted(keys))}}}, every one a non-empty string"
    if not (ss["action"].startswith(base + "/") and _url_ok(ss["action"]) and "?" not in ss["action"] and "#" not in ss["action"]):
        return f"action {ss['action']!r} is not a URL on {base} without a query or fragment"
    if not PARAM.match(ss["param"]):
        return f"param {ss['param']!r} is not a lowercase query name"
    return ""


def _count(v: object, lo: int = 0) -> bool:
    return _is_int(v) and lo <= v <= 50


LIST_KEYS = {"style", "local", "min", "caps", "prefix", "count", "no_results"}
CAPS = ("entity", "collection", "document", "total")


def _suggest_list_problem(sg: dict) -> str:
    if set(sg) != LIST_KEYS:
        return f"a list is not {{{', '.join(sorted(LIST_KEYS))}}}"
    if not (_count(sg["local"], 1) and _count(sg["min"], 1)):
        return "local and min are not 1 to 50"
    caps = sg["caps"]
    if not (isinstance(caps, dict) and set(caps) == set(CAPS) and all(_count(caps[k], 1) for k in CAPS)):
        return "caps is not {entity, collection, document, total}, each 1 to 50"
    if not (isinstance(sg["prefix"], dict) and all(SLUG.match(str(k)) and isinstance(v, str) for k, v in sg["prefix"].items())):
        return "prefix is not {type: text}"
    if not (isinstance(sg["count"], str) and "{n}" in sg["count"]):
        return "count is not text with {n}"
    nr = sg["no_results"]
    if not (isinstance(nr, dict) and set(nr) == {"lead", "or", "words"}
            and all(isinstance(nr[k], str) and nr[k].strip() for k in ("lead", "or"))
            and isinstance(nr["words"], list) and nr["words"]
            and all(isinstance(w, str) and w.strip() for w in nr["words"])):
        return "no_results is not {lead, or, words: [text, ...]}"
    return ""


def _suggest_problem(sg: object) -> str:
    if isinstance(sg, dict) and sg.get("style") == "list":
        return _suggest_list_problem(sg)
    if not isinstance(sg, dict) or set(sg) - {"rank"} != {"labels", "top", "recent_docs", "groups"}:
        return "is not {labels, top, recent_docs, groups, rank?}"
    labels = sg["labels"]
    if not (isinstance(labels, dict) and set(labels) == {"top", "recent_docs", "recent_searches"}
            and all(isinstance(v, str) and v.strip() for v in labels.values())):
        return "labels is not {top, recent_docs, recent_searches} text"
    if not _count(sg["top"], 1):
        return "top is not 1 to 50"
    if not (isinstance(sg["recent_docs"], list) and all(isinstance(x, str) and SLUG.match(x) for x in sg["recent_docs"])):
        return "recent_docs is not a list of slugs"
    if not isinstance(sg["groups"], list):
        return "groups is not a list"
    for g in sg["groups"]:
        if not (isinstance(g, dict) and set(g) == {"label", "items", "empty", "typing"}
                and isinstance(g["label"], str) and g["label"].strip() and _count(g["empty"]) and _count(g["typing"])
                and isinstance(g["items"], list)):
            return "a group is not {label, items, empty: 0-50, typing: 0-50}"
        for it in g["items"]:
            # An item runs a query, or sets one of the finder's filters to a value.
            need = ("label", "facet", "value") if isinstance(it, dict) and "facet" in it else ("label", "query")
            if not (isinstance(it, dict) and set(it) <= {*need, "count"}
                    and all(isinstance(it.get(k), str) and it[k].strip() for k in need)
                    and ("count" not in it or (_is_int(it["count"]) and it["count"] > 0))):
                return f"group {g['label']!r}: an item is not {{label, query, count?}} or {{label, facet, value, count?}}"
    if "rank" in sg:
        rows = sg["rank"]
        if not isinstance(rows, list):
            return "rank is not a list"
        for r in rows:
            if not (isinstance(r, dict) and set(r) == set(RANK_TEXT) | set(RANK_LISTS)
                    and all(isinstance(r[k], str) for k in RANK_TEXT) and SLUG.match(r["slug"])
                    and all(isinstance(r[k], list) and all(isinstance(x, str) for x in r[k]) for k in RANK_LISTS)):
                return "a rank row is not {slug, title, agency, summary, date, year, doc_type} text and {aliases, vendors} lists"
        if len({r["slug"] for r in rows}) != len(rows):
            return "rank names a record twice"
    return ""


RANK_TEXT = ("slug", "title", "agency", "summary", "date", "year", "doc_type")
RANK_LISTS = ("aliases", "vendors")


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
    for key in ("released", "notes", "badge", "badge_sr", "no_file"):
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
    if not isinstance(raw.get("gate", False), bool):
        return {}, "display.gate is not a boolean"
    if raw.get("gate") and notice is None:
        return {}, "display.gate needs a display.notice to stand behind"
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
        for k in ("original_url", "ia_url"):
            if k in hdr:
                if not isinstance(hdr[k], str):
                    return {}, f"display.header.{k} is not a string"
                if hdr[k] and not _url_ok(hdr[k]):
                    return {}, f"display.header.{k} is not a safe URL: {hdr[k]!r}"
        if "category" in hdr and not isinstance(hdr["category"], str):
            return {}, "display.header.category is not a string"
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
    browse = raw.get("browse", {})
    if not (isinstance(browse, dict) and all(SLUG.match(k) and isinstance(v, list) and all(isinstance(x, str) for x in v)
                                             for k, v in browse.items())):
        return {}, "index.browse is not {slug: [string]}"
    if not all(isinstance(raw.get(k, ""), str) for k in ("badge", "badge_sr")):
        return {}, "index.badge and index.badge_sr are not strings"
    if not isinstance(raw.get("sort_title", ""), str):
        return {}, "index.sort_title is not a string"
    if raw.get("badge_kind") and not (isinstance(raw["badge_kind"], str) and SLUG.match(raw["badge_kind"])):
        return {}, "index.badge_kind is not a slug"
    if not all(isinstance(raw.get(k, ""), str) for k in ("added", "added_display")):
        return {}, "index.added and index.added_display are not strings"
    if raw.get("added") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw["added"]):
        return {}, f"index.added {raw['added']!r} is not YYYY-MM-DD"
    if raw.get("thumb_url") and not _url_ok(raw["thumb_url"]):
        return {}, f"index.thumb_url {raw['thumb_url']!r} is not https:// or a same-host path"
    if "thumb" in raw:
        why = _thumb_problem(raw["thumb"])
        if why:
            return {}, why
        if raw.get("thumb_url"):
            return {}, "index has both thumb and thumb_url"
    return raw, ""


def thumb_bytes(thumb: dict) -> bytes:
    """index.thumb's image (checked by _thumb_problem when the row was parsed)."""
    return base64.b64decode(thumb["data"], validate=True)


def _thumb_problem(t: object) -> str:
    if not (isinstance(t, dict) and set(t) == {"mime", "sha256", "data"} and all(isinstance(v, str) for v in t.values())):
        return "index.thumb is not {mime, sha256, data} strings"
    if t["mime"] not in THUMB_TYPES:
        return f"index.thumb.mime {t['mime']!r} is not one of {', '.join(sorted(THUMB_TYPES))}"
    try:
        b = thumb_bytes(t)
    except (binascii.Error, ValueError):
        return "index.thumb.data is not base64"
    if not b or len(b) > THUMB_MAX:
        return f"index.thumb is {len(b)} bytes (1 to {THUMB_MAX})"
    if hashlib.sha256(b).hexdigest() != t["sha256"].lower():
        return "index.thumb.data does not hash to index.thumb.sha256"
    magic = THUMB_TYPES[t["mime"]][1]
    if not b.startswith(magic) or (t["mime"] == "image/webp" and b[8:12] != b"WEBP"):
        return f"index.thumb.data is not {t['mime']}"
    return ""


def _snapshot_problem(raw: object, base_url: str) -> tuple[dict, str]:
    if not isinstance(raw, dict):
        return {}, "snapshot is not an object"
    required = {"kind", "url", "captured", "source"}
    if not required <= set(raw):
        return {}, "snapshot needs kind, url, captured and source"
    if set(raw) - required - {"page", "ts", "of_record"}:
        return {}, "snapshot has unknown keys"
    kind, url, captured, source = raw.get("kind"), _str(raw, "url"), _str(raw, "captured"), _str(raw, "source")
    if kind not in SNAPSHOT_KINDS:
        return {}, "snapshot.kind is not html or wacz"
    if not url or not _url_ok(url) or (url.startswith("https://") and not url.startswith(base_url + "/")):
        return {}, "snapshot.url is not a same-origin or https:// URL"
    if not DATE.match(captured):
        return {}, "snapshot.captured is not YYYY, YYYY-MM or YYYY-MM-DD"
    if not source:
        return {}, "snapshot.source is empty"
    if kind == "wacz" and not url.lower().split("?", 1)[0].endswith(".wacz"):
        return {}, "snapshot.url for a wacz record must end in .wacz"
    if kind == "html" and any(k in raw for k in ("page", "ts")):
        return {}, "html snapshots cannot have WACZ page or timestamp fields"
    if "page" in raw and not isinstance(raw["page"], str):
        return {}, "snapshot.page is not a string"
    if "ts" in raw and not (isinstance(raw["ts"], str) and raw["ts"].strip()):
        return {}, "snapshot.ts is not a non-empty string"
    records = raw.get("of_record", [])
    if not (isinstance(records, list) and all(isinstance(x, dict) and set(x) == {"label", "url"}
                                              and isinstance(x["label"], str) and x["label"].strip()
                                              and isinstance(x["url"], str) and x["url"].startswith("https://")
                                              for x in records)):
        return {}, "snapshot.of_record is not a list of {label, url} https:// links"
    return dict(raw), ""


def _document(row: dict, base_url: str = "") -> tuple[Document | None, str]:
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
    snapshot, why = _snapshot_problem(row["snapshot"], base_url) if "snapshot" in row else ({}, "")
    if why:
        return None, why
    f = row.get("file")
    if snapshot and f is not None:
        return None, "snapshot records need file: null"
    if "file" not in row:
        return None, "no file"
    if f is None:
        # A record the site holds as text only (no file attached). It still gets a
        # page and a search entry, so it must have text to show for itself.
        if not snapshot and not (row.get("search_text") or row.get("pages")):
            return None, "file is null and there is no search_text or pages: nothing to publish"
        url = dl = sha = ext = mime = view = poster = view_sha = ""
        size = None
    else:
        if not isinstance(f, dict):
            return None, "no file"
        url, dl, sha = _str(f, "url"), _str(f, "download_url"), _str(f, "sha256").lower()
        ext, mime = _str(f, "ext").lower().lstrip("."), _str(f, "mime")
        if not (url and dl):
            return None, "file needs both url and download_url"
        view, poster = _str(f, "view_url"), _str(f, "poster_url")
        view_sha = _str(f, "view_sha256").lower()
        if view_sha and not (view and SHA256.match(view_sha)):
            return None, "file.view_sha256 is not 64 hex characters beside a view_url"
        for u in (url, dl, view, poster):
            if u and not _url_ok(u):
                return None, f"file URL {u!r} is not https:// or a same-host path"
        if not SHA256.match(sha):
            return None, "file.sha256 is not 64 hex characters"
        if ext not in EXTS:
            return None, f"file.ext {ext!r} is neither a reader type nor a known download-only type"
        if not mime:
            return None, "file.mime is empty"
        if ext in MIMES and mime.split(";")[0].strip().lower() not in MIMES[ext]:
            return None, f"file.mime {mime!r} does not fit file.ext {ext!r}"
        size = f.get("bytes")
        if size is not None and (not _is_int(size) or size < 0):
            return None, "file.bytes is not a non-negative integer"
    date = _str(row, "date")
    if date and not DATE.match(date):
        return None, f"date {date!r} is not YYYY, YYYY-MM or YYYY-MM-DD"
    archive = _str(row, "archive_url")
    if archive and not archive.startswith("https://"):
        return None, f"archive_url {archive!r} is not https://"
    provenance, why = _provenance_problem(row.get("provenance"))
    if why:
        return None, why
    lang = _str(row, "lang")
    if lang and not LANG.fullmatch(lang):
        return None, f"lang {lang!r} is not a BCP 47 language tag"
    relations, why = _relations_problem(row.get("relations"))
    if why:
        return None, why
    pages_raw = row.get("pages") or []
    if not isinstance(pages_raw, list):
        return None, "pages is not a list"
    if len(pages_raw) > MAX_PAGES:
        return None, f"{len(pages_raw)} pages is over the {MAX_PAGES} limit"
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
            if len(boxes_raw) > MAX_BOXES_PER_PAGE:
                return None, f"page {p['n']} has {len(boxes_raw)} boxes, over the {MAX_BOXES_PER_PAGE} limit"
            for b_idx, b in enumerate(boxes_raw):
                if not isinstance(b, dict):
                    return None, f"page {p['n']} box #{b_idx} is not an object"
                extra = sorted(set(b) - BOX_KEYS)
                if extra:
                    return None, f"page {p['n']} box #{b_idx} has keys {extra}; only {sorted(BOX_KEYS)} are allowed"
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
                    search_text.strip(), doc_id, display, index, view_sha, snapshot, provenance,
                    lang, relations), ""


def parse(data: object) -> Manifest:
    if not isinstance(data, dict):
        raise ManifestError("manifest is not a JSON object")
    schema_version = _schema_version(data.get("schema_version"))
    site = _site(data.get("site"))
    rows = data.get("documents")
    if not isinstance(rows, list):
        raise ManifestError("manifest has no 'documents' list")
    m = Manifest(site, [])
    seen: set[str] = set()
    for i, row in enumerate(rows):
        rid = row.get("slug") if isinstance(row, dict) and isinstance(row.get("slug"), str) else f"#{i}"
        doc, why = _document(row, site.base_url)
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
    m.collections, problems = CO.parse(data.get("collections"), site.base_url, site.room_path, seen)
    m.refusals += [("collections", why) for why in problems]
    m.refusals += [("collections", f"{p} is also an entity page") for p in sorted(CO.served(m.collections) & E.served(m.entities))]
    m.machine_text, problems = MT.parse(data.get("machine_text"), site.base_url, site.room_path, seen)
    m.refusals += [("machine_text", why) for why in problems]
    m.topics, problems = TP.parse(data.get("topics"), site.base_url, site.room_path, seen)
    m.refusals += [("topics", why) for why in problems]
    m.refusals += [("topics", f"{p} is also an entity or collection page")
                   for p in sorted(TP.served(m.topics) & (E.served(m.entities) | CO.served(m.collections)))]
    served = {"", *(f"{s}/" for s in seen)} | E.served(m.entities) | CO.served(m.collections) | TP.served(m.topics)
    m.head_meta, problems = HM.parse(data.get("head_meta"), site.base_url, site.room_path, served)
    m.refusals += [("head_meta", why) for why in problems]
    m.passages, problems = PS.parse(data.get("passages"), {d.slug: d for d in m.documents}, dict(m.excluded))
    m.refusals += [("passages", why) for why in problems]
    for document in m.documents:
        for relation in document.relations:
            if relation["slug"] not in seen:
                m.refusals.append((document.slug, f"relation names {relation['slug']!r}, which is not a document"))
            elif relation["slug"] == document.slug:
                m.refusals.append((document.slug, "relation cannot name the document itself"))
    sg = site.index.get("suggest") or {}
    m.refusals += [("site.index.suggest", f"recent_docs names {s!r}, which is not a document")
                   for s in sg.get("recent_docs", []) if s not in seen]
    m.refusals += [("site.index.suggest", f"rank names {r['slug']!r}, which is not a document")
                   for r in sg.get("rank", []) if r["slug"] not in seen]
    # Moved pages (redirects.py). A bad entry is left out and noted, never refused:
    # a retraction publish must not wait on a redirect.
    m.redirects, m.redirect_notes = RD.parse(data.get("redirects"))
    m.schema_version = schema_version
    return m


def load(path: Path | str) -> Manifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    return parse(data)
