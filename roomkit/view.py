"""The view model: the plain dicts the room's templates render.

Everything the templates (`templates/room/`) show comes from here, as plain
dicts, lists and strings, so a template never reaches into roomkit's
`Manifest`/`Document`. The host application will build the same dicts from its own
`document` and `document_page` rows and render the same templates.

What is decided here, not in a template: which links point into the room (and
so follow a staging mount), which are external, the groups and their order,
counts and the year span. Nothing here formats a date or composes a label: those
arrive formatted from the site's own helpers (the manifest's `display`/`index`).
Every key a template reads is always present (the environment is
StrictUndefined), empty when there is nothing to show.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from . import entities as E
from . import page_text as PT
from . import search as S
from . import site_collections as CO
from . import topics as TP
from .manifest import PDF, READER, THUMB_TYPES, Document, Manifest


def slugify(s: str) -> str:
    """An anchor id from a label (ASCII; matches WordPress sanitize_title for plain labels)."""
    s = re.sub(r"&[a-z]+;|&#\d+;", "", s.lower())
    s = re.sub(r"[^a-z0-9 _-]", "", s.replace("'", ""))
    return re.sub(r"-+", "-", re.sub(r"\s+", "-", s.strip())).strip("-") or "group"


def _external(url: str, m: Manifest) -> bool:
    return url.startswith("https://") and not url.startswith(m.site.base_url + "/")


# Links into the room (another record, the index) follow the mount, so a staging
# tree links to itself; everything else on the site keeps its live URL.

def _rebase_url(url: str, m: Manifest, at: str) -> str:
    room = m.site.base_url + m.site.room_path
    if not url.startswith(room):
        return url
    rest = url[len(room):]
    # Only the room itself, record pages and (with the pack's switches on) entity
    # collection and topic pages are in the static tree; other site pages under the
    # same path stay on the site.
    if (rest == "" or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/", rest) and rest[:-1] in _slugs(m)
            or rest in _entity_paths(m)):
        return at + rest
    return url


def _entity_paths(m: Manifest) -> set[str]:
    # m.entities, m.collections and m.topics are None unless the pack turned the
    # feature on (entities.gate, site_collections.gate, topics.gate).
    cache = getattr(m, "_room_entity_paths", None)
    if cache is None:
        cache = (E.served(m.entities) | CO.served(getattr(m, "collections", None))
                 | TP.served(getattr(m, "topics", None)))
        m._room_entity_paths = cache
    return cache


def _slugs(m: Manifest) -> set[str]:
    cache = getattr(m, "_room_slugs", None)
    if cache is None:
        cache = {d.slug for d in m.documents}
        m._room_slugs = cache
    return cache


def _crumbs(items: list[dict]) -> list[dict]:
    return [{"label": c["label"], "url": c.get("url", "")} for c in items]


def _chrome(pack: dict, at: str) -> dict:
    toggle = pack["layout"]["toggle"]
    return {"at": at, "theme_key": toggle, "toggle_on": bool(toggle)}


# --- document page --------------------------------------------------------------

def read_aloud_on(doc: Document, pack: dict) -> bool:
    """Whether this record's reader mount carries the read-aloud panel: the pack's
    read-aloud switch, a mount the engine fills, page texts to read (the mount's
    data-pages-url), and no gate (the player wires mounts at load, and a gated
    mount only gets its data-file-url on "Show document")."""
    return bool(pack.get("features", {}).get("read-aloud") and doc.pages and doc.ext in READER
                and not doc.is_snapshot and not doc.display.get("gate") and doc.has_file)


def reader_view(doc: Document, at: str, read_aloud: bool = False) -> dict:
    """The reader mount (or the download block for files the engine cannot show)."""
    snap = doc.snapshot
    is_wacz = snap.get("kind") == "wacz"
    return {"has_file": doc.has_file, "no_file": doc.display.get("no_file", ""),
            "mount": doc.is_snapshot or doc.ext in READER, "pdf": doc.ext in PDF,
            "kind": "HTML mirror" if snap.get("kind") == "html" else ("WACZ archive" if is_wacz else ("PDF" if doc.ext in PDF else "file")),
            "file_url": snap.get("url", doc.file_url), "download_url": snap.get("url", doc.download_url),
            # display.gate: the reader waits for "Show document" (room.js), loading nothing before.
            "gate": bool(doc.display.get("gate")),
            # The reader may load a verified viewing copy; every link stays the original.
            "reader_url": snap.get("url", doc.view_url or doc.file_url), "view_note": bool(doc.view_url),
            "snapshot_kind": snap.get("kind", ""), "snapshot_page": snap.get("page", ""), "snapshot_ts": snap.get("ts", ""),
            "ext": doc.ext, "mime": doc.mime, "slug": doc.slug, "title": doc.title, "poster_url": doc.poster_url,
            # With page texts, the engine (0.6.0+) searches them in the browser.
            "pages_url": f"{at}{doc.slug}/pages.json" if doc.pages else "",
            "read_aloud": read_aloud,
            "features": "spread,search,lightbox,fullscreen" if doc.pages else "spread,lightbox,fullscreen"}


def _details(doc: Document, m: Manifest, at: str) -> list[dict]:
    rows = doc.display.get("details", [])
    if not rows:
        rows = ([{"label": "Agency", "value": doc.agency}] if doc.agency else []) \
            + ([{"label": "Date", "value": doc.date}] if doc.date else []) \
            + ([{"label": "SHA-256", "value": doc.sha256, "code": True}] if doc.has_file and doc.sha256 else [])
    return [{"label": r["label"], "value": r["value"], "code": bool(r.get("code")),
             "url": _rebase_url(r["url"], m, at) if r.get("url") else "",
             # Judged on the URL as the site wrote it, before any rebase.
             "external": _external(r.get("url", ""), m), "note": r.get("note", "")} for r in rows]


def _snapshot_provenance(doc: Document, m: Manifest) -> list[dict]:
    """Expose capture facts supplied by the exporter, without composing them."""
    snap = doc.snapshot
    if not snap:
        return []
    rows = [{"label": "Captured", "value": snap["captured"], "code": False, "url": "",
             "external": False, "note": ""},
            {"label": "Capture source", "value": snap["source"], "code": False, "url": "",
             "external": False, "note": ""}]
    for record in snap.get("of_record", []):
        url = record["url"]
        rows.append({"label": "Archive of record", "value": record["label"], "code": False,
                     "url": url, "external": _external(url, m), "note": ""})
    return rows


def _groups(doc: Document, m: Manifest, at: str) -> list[dict]:
    out = []
    for g in doc.display.get("groups", []):
        items = []
        for it in g.get("items", []):
            url = _rebase_url(it.get("url", ""), m, at)
            items.append({"label": it["label"], "url": url, "external": bool(url) and _external(url, m),
                          "kind": it.get("kind", ""), "quote": it.get("quote", ""), "meta": it.get("meta", "")})
        out.append({"heading": g["heading"], "blurb": g.get("blurb", ""),
                    "list": "chips" if g.get("style", "list") == "chips" else "links", "items": items})
    return out


def doc_view(doc: Document, m: Manifest, at: str, pack: dict) -> dict:
    d, labels = doc.display, pack.get("labels", {})
    crumbs = d.get("breadcrumbs") or [{"label": labels.get("room", "Reading Room"), "url": at}, {"label": doc.title}]
    eb = d.get("eyebrow")
    notice = d.get("notice")
    hdr = d.get("header")
    header_view = None
    if hdr:
        header_view = {
            "meta": [str(x) for x in hdr.get("meta", [])],
            "original_url": _rebase_url(hdr["original_url"], m, at) if hdr.get("original_url") else "",
            "ia_url": hdr.get("ia_url", ""),
            "ia_pending": bool(hdr.get("ia_pending")),
            "category": hdr.get("category", ""),
        }
    return {**_chrome(pack, at), "doc": {
        "crumbs": _crumbs([{**c, "url": _rebase_url(c.get("url", ""), m, at)} for c in crumbs]),
        "eyebrow": {"label": eb["label"], "url": _rebase_url(eb.get("url", ""), m, at)} if eb else None,
        "header": header_view,
        "title": doc.title, "badge": d.get("badge", ""), "badge_kind": d.get("badge_kind", ""),
        "badge_sr": d.get("badge_sr", ""),
        "released": d.get("released", ""), "released_label": labels.get("released", "Released"),
        "summary": doc.summary,
        "notice": {"heading": notice["heading"], "body": notice["body"], "report": notice.get("report", "")}
                  if notice else None,
        "reader_label": "Document" if doc.ext in READER else "File",
        "reader": reader_view(doc, at, read_aloud_on(doc, pack)),
        # The text view's links (pack features.page-text), or None.
        "text": {"url": f"{at}{PT.text_path(doc)}", "download_url": f"{at}{PT.txt_path(doc)}"}
                if PT.on(doc, pack) else None,
        "details": _details(doc, m, at),
        "provenance": _snapshot_provenance(doc, m),
        "file_kind": "PDF" if doc.ext in PDF else "file",
        "has_file": doc.has_file,
        "file_url": doc.file_url, "download_url": doc.download_url, "archive_url": doc.archive_url,
        "citation": doc.citation,
        "groups": _groups(doc, m, at),
        "notes_lines": d["notes"].split("\n") if d.get("notes") else [],
    }}


def text_view(doc: Document, m: Manifest, at: str, pack: dict) -> dict:
    """The record's text page (page_text.py): the title, the machine-read label, the links back
    to the record and the file, and each page's paragraphs."""
    d, labels = doc.display, pack.get("labels", {})
    record = f"{at}{doc.slug}/"
    crumbs = [{**c, "url": _rebase_url(c.get("url", ""), m, at)}
              for c in (d.get("breadcrumbs") or [{"label": labels.get("room", "Reading Room"), "url": at},
                                                 {"label": doc.title}])]
    if crumbs and not crumbs[-1]["url"]:
        crumbs[-1] = {**crumbs[-1], "url": record}
    pages = PT.sections(doc)
    return {**_chrome(pack, at), "t": {
        "crumbs": _crumbs([*crumbs, {"label": "Text"}]),
        "title": doc.title, "label": PT.LABEL, "lang": doc.lang or "en",
        "record_url": record, "file_url": doc.file_url if doc.has_file else "",
        "download_url": f"{at}{PT.txt_path(doc)}",
        "sha256": doc.sha256 if doc.has_file else "", "pages": pages,
        "page_links": pages if len(pages) > 1 else [],
    }}


# --- index ------------------------------------------------------------------------

def _facet_values(m: Manifest, name: str) -> list[str]:
    vals = {d.index.get("facets", {}).get(name, "") for d in m.documents}
    vals.discard("")
    return sorted(vals, reverse=name == "year")


def _group_sets(sets: list[dict], shown: list[str]) -> list[dict]:
    """The group select's optgroups: each set's groups that the room shows, in the set's
    order, then any shown group in no set (left as a plain option)."""
    out, used = [], set()
    for g in sets:
        vals = [x for x in g["groups"] if x in shown and x not in used]
        used.update(vals)
        if vals:
            out.append({"label": g["label"], "values": vals})
    rest = [x for x in shown if x not in used]
    return out + ([{"label": "", "values": rest}] if out and rest else [])


def _year(doc: Document) -> str:
    return doc.date[:4] if doc.date else ""


def gallery_on(pack: dict) -> bool:
    """layout.gallery: the index's List / Gallery switch, over a rows layout only."""
    lay = pack.get("layout", {})
    return bool(lay.get("gallery")) and lay.get("style") == "rows"


def page_size(pack: dict) -> int:
    """layout.page_size: records per page on the index and facet pages; 0 is one page."""
    n = pack.get("layout", {}).get("page_size")
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0


def thumb_path(doc: Document) -> str:
    """The room's copy of the card thumbnail (manifest index.thumb), before its
    content hash is added; empty when the manifest carries none."""
    t = doc.index.get("thumb")
    return f"assets/thumbs/{doc.slug}.{THUMB_TYPES[t['mime']][0]}" if t else ""


def _end_year(years: str) -> str:
    """A collection's period ("1968–1971") as its last year, or ""."""
    ys = re.findall(r"\d{4}", years or "")
    return ys[-1] if ys else ""


def _grid_rows(m: Manifest) -> list[dict]:
    gr = (getattr(m, "collections", None) or {}).get("grid") or {}
    return [r for e in gr.get("eras", []) for g in e["groups"] for r in g["rows"]]


def _recency(m: Manifest) -> dict[str, str]:
    """Each group's newest record date (YYYY-MM-DD, YYYY-MM or YYYY), or, with no dated
    record, its collection's last year from the collections table; "" when neither.
    Strings compare in date order: "1971" < "1971-05" < "2026-08-12"."""
    out: dict[str, str] = {r["title"]: _end_year(r.get("years", "")) for r in _grid_rows(m)}
    newest: dict[str, str] = {}
    for d in m.documents:
        g = d.index.get("group", "")
        if d.date and d.date > newest.get(g, ""):
            newest[g] = d.date
    return {**out, **newest}


def _newest_first(items: list, key) -> list:
    # Stable: equal keys keep the export's order; "" (nothing dated) sorts last.
    return sorted(items, key=key, reverse=True)


def _lead_grid(gr: dict, rec: dict[str, str]) -> dict:
    """The collections table with eras, groups and rows ordered newest first (layout.lead recent)."""
    def rk(r: dict) -> str:
        return rec.get(r["title"], "")
    def groups(e: dict) -> list:
        return [dict(g, rows=_newest_first(g["rows"], rk)) for g in e["groups"]]
    eras = [dict(e, groups=_newest_first(groups(e), lambda g: max([rk(r) for r in g["rows"]] or [""])))
            for e in gr["eras"]]
    return dict(gr, eras=_newest_first(eras, lambda e: max([rk(r) for g in e["groups"] for r in g["rows"]] or [""])))


def _cover_text(s: str) -> bool:
    """A summary that is a scan's cover-sheet text: 40 or more letters, at least 60% capitals."""
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 40 and sum(c.isupper() for c in letters) >= 0.6 * len(letters)


def _blurbs(m: Manifest, pack: dict) -> dict[str, str]:
    """Collection title -> its description, when the pack shows those over cover-sheet summaries."""
    if pack.get("layout", {}).get("cover_summaries") != "collection-blurb":
        return {}
    return {r["title"]: r["blurb"] for r in _grid_rows(m) if r.get("blurb")}


def _card(doc: Document, at: str, multi: tuple[str, ...] = (), sortable: bool = False, n: int = 0,
          blurbs: dict[str, str] | None = None) -> dict:
    ix = doc.index
    summary = doc.summary
    if blurbs and _cover_text(summary) and blurbs.get(ix.get("group", "")):
        summary = blurbs[ix["group"]]
    blob = " ".join([doc.title, doc.summary, doc.agency, ix.get("group", ""), ix.get("card_date", ""),
                     *ix.get("meta", []), *ix.get("facets", {}).values(),
                     *([ix["badge"]] if ix.get("badge") else [])]).lower()
    return {"text": re.sub(r"\s+", " ", blob).strip(), "group": ix.get("group", ""),
            "facets": [{"name": k, "value": v} for k, v in sorted(ix.get("facets", {}).items())],
            # A multi-valued facet (vendor): the values as JSON, matched whole by room.js.
            "multi": [{"name": n, "json": json.dumps(ix.get("browse", {}).get(n, []), ensure_ascii=False)} for n in multi],
            # The site's own sort text (index.sort_title), cased as rendered: room.js trims and
            # lowercases it in the browser, as the site's list does. n: the manifest position,
            # the order a flat sort starts from (the site's own list order).
            "sort_title": ix.get("sort_title") or doc.title, "sortable": sortable, "n": n,
            "url": f"{at}{doc.slug}/", "thumb_url": at + thumb_path(doc) if ix.get("thumb") else ix.get("thumb_url", ""),
            "date": doc.date, "card_date": ix.get("card_date", ""),
            "title": doc.title, "meta": list(ix.get("meta", [])), "summary": summary,
            "badge": ix.get("badge", ""), "badge_kind": ix.get("badge_kind", ""), "badge_sr": ix.get("badge_sr", "")}


def _number(v: object) -> int | None:
    """An exported count ("11", "1,234", "70 files") as a number, or None."""
    m = re.match(r"\s*([0-9][0-9,]*)", str(v or ""))
    return int(m.group(1).replace(",", "")) if m else None


def _suggest_list(m: Manifest, at: str, sg: dict) -> dict:
    """A flat suggestion list (site A): the site's limits and words, plus what its ranking reads,
    from the room's own pages: entities and collections as room URLs, and every document's
    title with its collection, in the site's list order."""
    entities = [{"type": e["type"], "label": e["label"], "url": _rebase_url(e["url"], m, at), "count": _number(e.get("count"))}
                for g in (m.entities or {}).get("index", {}).get("groups", []) for e in g["entities"]]
    collections = [{"label": c["title"], "url": _rebase_url(c["url"], m, at), "count": _number(c.get("count"))}
                   for cat in ((getattr(m, "collections", None) or {}).get("index") or {}).get("categories", [])
                   for g in cat.get("groups", []) for c in g.get("collections", [])]
    groups: list[dict] = []
    at_group: dict[str, int] = {}
    docs = []
    for d in m.documents:
        eb = d.display.get("eyebrow") or {}
        label = eb.get("label", "")
        if label and label not in at_group:
            at_group[label] = len(groups)
            groups.append({"label": label, "url": _rebase_url(eb["url"], m, at) if eb.get("url") else ""})
        docs.append([d.title, at_group.get(label, -1)])
    return dict(sg, entities=entities, collections=collections, groups=groups, docs=docs)


def _suggest(m: Manifest, at: str) -> str:
    """site.index.suggest as room-search.js reads it: recent documents as titles and room URLs."""
    sg = m.site.index.get("suggest")
    if not sg:
        return ""
    if sg.get("style") == "list":
        return script_json(_suggest_list(m, at, sg))
    titles = {d.slug: d.title for d in m.documents}
    out = dict(sg, recent_docs=[{"label": titles[s], "url": f"{at}{s}/"} for s in sg["recent_docs"]])
    if "rank" in sg:
        out["rank"] = [dict(r, label=titles[r["slug"]], url=f"{at}{r['slug']}/") for r in sg["rank"]]
    return script_json(out)


def _noun(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def _browse(facet_pages: list[dict], heading: str, at: str) -> dict | None:
    """The index's links to every facet page (browse.py), one folded list per facet."""
    if not facet_pages:
        return None
    facets: dict[str, dict] = {}
    for p in facet_pages:
        f = facets.setdefault(p["name"], {"name": p["name"], "label": p["label"], "values": []})
        f["values"].append({"label": p["value"], "url": at + p["path"], "count": len(p["docs"])})
    return {"heading": heading, "facets": list(facets.values())}


def index_view(m: Manifest, at: str, pack: dict, facet_pages: list[dict] | None = None,
               browse_heading: str = "") -> dict:
    """The index. Every noun comes from the pack, and the jump nav is named by its
    visible label. `facet_pages` (browse.pages, when the pack builds them) adds the
    browse block."""
    ix, labels = m.site.index, pack.get("labels", {})
    order = list(ix.get("groups", []))
    grouped: dict[str, list[Document]] = {g: [] for g in order}
    other = labels.get("other_group", "Other records")
    for d in m.documents:
        grouped.setdefault(d.index.get("group") or other, []).append(d)
    shown = [g for g in grouped if grouped[g] or (g in order and pack["layout"]["show_empty_groups"])]
    lay = pack["layout"]
    lead = lay.get("lead", "site")
    rec = _recency(m) if lead == "recent" else {}
    sets = list(ix.get("group_sets", []))
    if lead == "recent":
        shown = _newest_first(shown, lambda g: rec.get(g, ""))
        rank = {g: i for i, g in enumerate(shown)}
        sets = sorted(({**s, "groups": sorted(s["groups"], key=lambda g: rank.get(g, len(rank)))} for s in sets),
                      key=lambda s: min([rank.get(g, len(rank)) for g in s["groups"]] or [len(rank)]))
    blurbs = _blurbs(m, pack)
    pos = {d.slug: i for i, d in enumerate(m.documents)}
    # One source for the group noun: the pack. The manifest's group_label is not shown.
    group_label = labels["group"]
    # The nav is named by its visible label, minus trailing punctuation (WCAG 2.5.3). The same
    # short form goes before a folded list's count: "Jump to jurisdiction (17)", not ": (17)".
    jump_label = labels["jump"]
    jump_name = jump_label.rstrip(" :;,.!?\u2026\u2013\u2014")
    years = sorted({_year(d) for d in m.documents if _year(d)})
    selects = [{"kind": "group", "name": "group", "label": group_label, "values": [g for g in shown if grouped[g]],
                "sets": _group_sets(sets, [g for g in shown if grouped[g]])}]
    multi = tuple(f["name"] for f in ix.get("facets", []) if f.get("multi"))
    for f in ix.get("facets", []):
        if f.get("multi"):
            vals = sorted({v for d in m.documents for v in d.index.get("browse", {}).get(f["name"], [])})
            selects.append({"kind": "multi", "name": f["name"], "label": f["label"], "values": vals})
        elif f.get("range"):
            vals = _facet_values(m, f["name"])
            selects.append({"kind": "range", "name": f["name"], "label": f["label"], "values": vals,
                            "from_label": f["from_label"], "to_label": f["to_label"]})
        else:
            selects.append({"kind": "", "name": f["name"], "label": f["label"], "values": _facet_values(m, f["name"])})
    jump = [g for g in shown if grouped[g]]
    group_count = len([g for g in grouped if grouped[g]])
    return {**_chrome(pack, at), "layout": pack["layout"]["style"], "index": {
        "crumbs": [{"label": "Home", "url": m.site.base_url + "/"}, {"label": labels.get("room", "Reading Room"), "url": ""}],
        "back": _back(ix, m, at),
        "eyebrow": ix.get("eyebrow", ""), "title": ix.get("title") or m.site.title, "lede": ix.get("lede", ""),
        "count": len(m.documents),
        "group_count": group_count,
        # Count nouns come from the pack, singular or plural by the count; never "+s".
        "records_noun": _noun(len(m.documents), labels["record_singular"], labels["record_plural"]),
        # The header's count may name records differently from the finder's count (site A).
        "stats_noun": _noun(len(m.documents), labels.get("stats_singular", labels["record_singular"]),
                            labels.get("stats_plural", labels["record_plural"])),
        # The finder's live count (room.js) picks between these.
        "count_nouns": {"one": labels["record_singular"], "other": labels["record_plural"]},
        "groups_noun": _noun(group_count, labels["group_singular"], labels["groups_plural"]),
        "years": list(ix["years"]) if ix.get("years") else ([years[0], years[-1]] if years else []),
        "links": [{"label": ln["label"], "url": ln["url"], "text": ln.get("text", "")} for ln in ix.get("links", [])],
        "search_placeholder": labels.get("search_placeholder", "Title, agency, summary..."),
        # Corpus search (pack features.corpus-search): room-search.js owns the finder and
        # loads the Pagefind index from here. None: room.js filters the cards as before.
        "search": {"pagefind_url": f"{at}{S.OUT}/",
                   "placeholder": labels.get("fulltext_placeholder", "Words in the records, titles, agencies..."),
                   "recent_key": f"room-recent-searches:{at}",
                   # The site's suggestion panel (manifest site.index.suggest), for room-search.js.
                   "suggest": _suggest(m, at),
                   # How the site's search reads a query (site.index.search_terms), or None.
                   "terms": ix.get("search_terms"),
                   # Pagefind's ranking weights (pack search_ranking), or None for its defaults.
                   "ranking": (json.dumps(pack["search_ranking"], sort_keys=True, separators=(",", ":"))
                               if pack.get("search_ranking") else None)} if S.enabled(pack) else None,
        # The site's own search for readers without JavaScript (pack features.server-search):
        # the form its server answers, rendered in a <noscript>; the room answers nothing.
        "server_search": ix.get("server_search") if pack.get("features", {}).get("server-search") else None,
        # A select with fewer than two values could not narrow anything.
        "selects": [x for x in selects if len(x["values"]) >= 2],
        "sort": ix.get("sort"),
        "jump": {"label": jump_label, "name": jump_name,
                 # Bare slugs, as the WordPress index used, so old #anchors still land.
                 "groups": [{"id": slugify(g), "label": g} for g in jump], "folded": len(jump) > 12}
                if len(jump) > 1 else None,
        "sections": [{"id": slugify(g), "label": g, "cards": [_card(d, at, multi, bool(ix.get('sort')), pos[d.slug], blurbs)
                                                               for d in grouped[g]]} for g in shown],
        "empty_group_text": ix.get("empty_group_text") or "No records yet.",
        "browse": _browse(facet_pages or [], browse_heading, at),
        "collections_grid": _grid(m, at, rec if lead == "recent" else None),
        "lead": lead,
        # The folded collections table's summary (lead recent): "All 41 collections".
        "grid_fold": f"All {len(_grid_rows(m))} {_noun(len(_grid_rows(m)), labels['group_singular'], labels['groups_plural'])}",
        "newest": (newest := _newest(m, at, lay.get("newest", 0), labels)),
        "added": _added(m, at, lay.get("added", 0), labels, {it["url"] for it in (newest or {}).get("items", [])}),
        "finder": _finder(lay, labels),
        # layout.gallery: the List / Gallery switch (rows layout only).
        "gallery": gallery_on(pack),
    }}


def _newest(m: Manifest, at: str, n: int, labels: dict) -> dict | None:
    """The index's newest dated records (layout.newest), newest first; ties in the export's order."""
    dated = _newest_first([d for d in m.documents if d.date], lambda d: d.date)[:n]
    if not dated:
        return None
    return {"heading": labels.get("newest", "Newest records"), "id": "room-newest",
            "items": [_lead_item(d, at, d.date, d.index.get("card_date", "") or d.date) for d in dated]}


def _added(m: Manifest, at: str, n: int, labels: dict, skip: set[str]) -> dict | None:
    """The records most recently added to the catalog (index.added, layout.added), latest
    first, leaving out those the newest list already shows (`skip`, their urls). Records
    added the same day go newest document date first, then in the export's order."""
    if n <= 0:
        return None
    pool = [d for d in m.documents if d.index.get("added") and f"{at}{d.slug}/" not in skip]
    pool = _newest_first(_newest_first(pool, lambda d: d.date or ""), lambda d: d.index["added"])[:n]
    if not pool:
        return None
    return {"heading": labels.get("added", "Recently added"), "id": "room-added",
            "items": [_lead_item(d, at, d.index["added"], d.index.get("added_display", "") or d.index["added"],
                                 verb="Added ") for d in pool]}


def _lead_item(d: Document, at: str, date: str, shown: str, verb: str = "") -> dict:
    return {"title": d.title, "url": f"{at}{d.slug}/", "date": date, "card_date": shown, "verb": verb,
            "group": d.index.get("group", ""),
            # The record's first page (index.thumb, when an exporter step adds one).
            "thumb_url": at + thumb_path(d) if d.index.get("thumb") else ""}


# The selects a compact finder keeps in view; the rest go under the More filters fold.
FINDER_IN_VIEW = ("group", "year")


def _finder(lay: dict, labels: dict) -> dict | None:
    """layout.finder compact: the fold's label, which selects stay in view, and the undated line's words."""
    if lay.get("finder") != "compact":
        return None
    adj = labels.get("undated", "undated")
    return {"more": labels.get("more_filters", "More filters"), "in_view": list(FINDER_IN_VIEW),
            # {n} is the count; the noun is the pack's, singular or plural by the count.
            "undated_one": f"{{n}} {adj} {labels['record_singular']} is not shown while a year is set.",
            "undated_other": f"{{n}} {adj} {labels['record_plural']} are not shown while a year is set."}


def facet_view(p: dict, m: Manifest, at: str, pack: dict) -> dict:
    """One facet page (browse.py): the records listed under one value, as index cards."""
    labels = pack.get("labels", {})
    n = len(p["docs"])
    return {**_chrome(pack, at), "layout": pack["layout"]["style"], "facet": {
        "key": f"{p['name']}/{p['slug']}", "room_only": p["room_only"],
        "crumbs": [{"label": labels.get("room", "Reading Room"), "url": at}, {"label": p["title"], "url": ""}],
        "eyebrow": p["label"], "title": p["title"], "count": n,
        "records_noun": _noun(n, labels["record_singular"], labels["record_plural"]),
        "cards": [_card(d, at, blurbs=_blurbs(m, pack)) for d in p["docs"]]}}


def facet_root_view(f: dict, m: Manifest, at: str, pack: dict) -> dict:
    """A facet's own path (browse.py roots): its values as links, so a trimmed URL lands somewhere."""
    labels = pack.get("labels", {})
    return {**_chrome(pack, at), "froot": {
        "key": f["name"],
        "crumbs": [{"label": labels.get("room", "Reading Room"), "url": at}, {"label": f["label"], "url": ""}],
        "title": f["label"], "values": f["values"]}}


# --- entities (pack features.entities; entities.py) ----------------------------------
# Every string and list below is the export's, in the export's order. The view
# decides only which links follow the mount and which heading levels the lists sit
# under, so the outline has no gap: with a documents heading, the groups are h3.

def _back(p: dict, m: Manifest, at: str) -> dict | None:
    b = p.get("back")
    return {"label": b["label"], "url": _rebase_url(b["url"], m, at)} if b else None


def _head_block(p: dict, m: Manifest, at: str) -> dict:
    return {"crumbs": _crumbs([{**c, "url": _rebase_url(c.get("url", ""), m, at)} for c in p.get("crumbs", [])]),
            "back": _back(p, m, at), "eyebrow": p.get("eyebrow", ""), "title": p["title"],
            "lede": p.get("lede", ""), "note": p.get("note", ""), "empty_text": p["empty_text"],
            "stats": [{"figure": s["figure"], "label": s["label"]} for s in p.get("stats", [])]}


def _entity_link(e: dict, m: Manifest, at: str) -> dict:
    return {"key": E.key(e["type"], e["slug"]), "label": e["label"], "kind": e.get("kind", ""),
            "count": e.get("count", ""), "url": _rebase_url(e["url"], m, at)}


def entity_index_view(m: Manifest, at: str, pack: dict) -> dict:
    """The site's entity index: its groups and entities as exported."""
    ix = m.entities["index"]
    return {**_chrome(pack, at), "entities": {
        **_head_block(ix, m, at),
        "groups": [{"id": f"room-etype-{g['type']}", "type": g["type"], "heading": g["heading"],
                    "count": g.get("count", ""), "entities": [_entity_link(e, m, at) for e in g["entities"]]}
                   for g in ix["groups"]]}}


def entity_view(p: dict, m: Manifest, at: str, pack: dict) -> dict:
    """One entity page: its documents in the site's groups, and who appears alongside."""
    al = p.get("alongside")
    heading = p.get("documents_heading", "")
    return {**_chrome(pack, at), "entity": {
        **_head_block(p, m, at),
        "key": E.key(p["type"], p["slug"]),
        "alongside": {"heading": al["heading"], "note": al.get("note", ""), "count_sr": al.get("count_sr", ""),
                      "items": [_entity_link(e, m, at) for e in al["items"]]} if al and al["items"] else None,
        "documents_heading": heading, "documents_heading_hidden": bool(p.get("documents_heading_hidden")),
        "group_level": 3 if heading else 2,
        "groups": [{"id": f"room-egroup-{i}", "heading": g["heading"],
                    "documents": [{"slug": d["slug"], "title": d["title"], "url": _rebase_url(d["url"], m, at),
                                   "badge": d.get("badge", ""), "badge_kind": d.get("badge_kind", ""),
                                   "badge_sr": d.get("badge_sr", ""), "meta": d.get("meta", "")}
                                  for d in g["documents"]]}
                   for i, g in enumerate(p["groups"], 1)]}}


# --- collections (pack features.collections; site_collections.py) -----------------------

def _sort_view(s: dict | None) -> dict | None:
    return {"label": s["label"], "options": [{"value": o["value"], "label": o["label"]} for o in s["options"]]} if s else None


def _grid(m: Manifest, at: str, rec: dict[str, str] | None = None) -> dict | None:
    """The collections table on the index, or None (no block, or the switch off). With
    `rec` (layout.lead recent), newest first."""
    gr = (getattr(m, "collections", None) or {}).get("grid")
    if not gr:
        return None
    if rec is not None:
        gr = _lead_grid(gr, rec)
    return {"heading": gr["heading"], "columns": list(gr["columns"]), "sort": _sort_view(gr.get("sort")),
            "eras": [{"heading": e["heading"], "groups": [
                {"heading": g["heading"], "rows": [
                    {"slug": r["slug"], "title": r["title"], "url": _rebase_url(r["url"], m, at),
                     "years": r.get("years", ""), "year": r.get("year", ""), "sources": r.get("sources", ""),
                     "sources_line": r.get("sources_line", ""), "sources_empty": r.get("sources_empty", ""),
                     "blurb": r.get("blurb", ""), "blurb_empty": r.get("blurb_empty", "")} for r in g["rows"]]}
                for g in e["groups"]]} for e in gr["eras"]]}


def collections_index_view(m: Manifest, at: str, pack: dict) -> dict:
    """The site's collections page: its categories, groups and collections, in its order."""
    ix = m.collections["index"]
    f = ix.get("filters")
    img = ix.get("image")
    return {**_chrome(pack, at), "collections": {
        "back": _back(ix, m, at), "eyebrow": ix.get("eyebrow", ""), "title": ix["title"], "lede": ix.get("lede", ""),
        "image": {"url": img["url"], "alt": img["alt"]} if img else None,
        "empty_text": ix["empty_text"],
        "search": {"label": ix["search"]["label"], "placeholder": ix["search"]["placeholder"]} if ix.get("search") else None,
        "filters": {"label": f["label"], "group_label": f["group_label"],
                    "options": [{"value": o["value"], "label": o["label"]} for o in f["options"]]} if f else None,
        "sort": _sort_view(ix.get("sort")),
        "categories": [{"key": c["key"], "heading": c["heading"], "stamp": c.get("stamp", ""), "groups": [
            {"id": g["id"], "heading": g["heading"], "collections": [
                {"slug": c2["slug"], "title": c2["title"], "url": _rebase_url(c2["url"], m, at),
                 "count": c2["count"], "code": c2.get("code", ""), "blurb": c2.get("blurb", ""),
                 "years": c2.get("years", ""), "year": c2.get("year", ""), "tags": " ".join(c2.get("tags", [])),
                 "match": c2.get("match", "")} for c2 in g["collections"]]}
            for g in c["groups"]]} for c in ix["categories"]]}}


def collection_view(p: dict, m: Manifest, at: str, pack: dict) -> dict:
    """One collection page: its heading block, any notice, and its records in order."""
    n, s = p.get("notice"), p.get("search")
    return {**_chrome(pack, at), "collection": {
        "slug": p["slug"], "back": _back(p, m, at), "eyebrow": p.get("eyebrow", ""), "title": p["title"],
        "count": p["count"], "stamp": p.get("stamp", ""), "stamp_kind": p.get("stamp_kind", ""),
        "years": p.get("years", ""), "blurb": p.get("blurb", ""), "description": p.get("description", ""),
        "notice": {"heading": n["heading"], "body": n["body"], "report": n.get("report", "")} if n else None,
        "search": {"label": s["label"], "placeholder": s["placeholder"], "status": s["status"]} if s else None,
        "list_label": p["list_label"], "empty_text": p["empty_text"],
        "documents": [{"slug": d["slug"], "title": d["title"], "url": _rebase_url(d["url"], m, at), "num": d["num"],
                       "final": d.get("final", ""), "badge": d.get("badge", ""), "badge_kind": d.get("badge_kind", ""),
                       "badge_sr": d.get("badge_sr", ""), "size": d.get("size", ""), "match": d["title"].lower()}
                      for d in p["documents"]]}}


def topics_index_view(m: Manifest, at: str, pack: dict) -> dict:
    """The site's topics page: every topic with its count, in the site's order."""
    ix = m.topics["index"]
    return {**_chrome(pack, at), "topics": {
        "back": _back(ix, m, at), "title": ix["title"], "subtitle": ix["subtitle"], "empty_text": ix["empty_text"],
        "topics": [{"slug": t["slug"], "label": t["label"], "count": t["count"], "url": _rebase_url(t["url"], m, at)}
                   for t in ix["topics"]]}}


def topic_view(p: dict, m: Manifest, at: str, pack: dict) -> dict:
    """One page of one topic: its heading block, its records, its paging."""
    pg = p.get("pagination")
    return {**_chrome(pack, at), "topic": {
        "slug": p["slug"], "page": p["page"],
        "crumbs": _crumbs([{**c, "url": _rebase_url(c.get("url", ""), m, at)} for c in p.get("crumbs", [])]),
        "back": _back(p, m, at), "eyebrow": p.get("eyebrow", ""), "title": p["title"], "subtitle": p["subtitle"],
        "empty_text": p["empty_text"],
        # The site's in-topic filter, answered by its server at the topic's live URL
        # (pack features.server-search): live sends it to page 1 from every page.
        "search": {**p["search"], "action": m.site.base_url + m.site.room_path + TP.page_path(p["slug"], 1)}
        if p.get("search", {}).get("param") and pack.get("features", {}).get("server-search") else None,
        "documents": [{"slug": d["slug"], "title": d["title"], "url": _rebase_url(d["url"], m, at),
                       "badge": d.get("badge", ""), "badge_kind": d.get("badge_kind", ""), "badge_sr": d.get("badge_sr", ""),
                       "date": d.get("date", ""), "reading_time": d.get("reading_time", ""), "agency": d.get("agency", ""),
                       "summary": d.get("summary", ""),
                       "collection": {"label": d["collection"]["label"], "url": _rebase_url(d["collection"]["url"], m, at)}
                       if d.get("collection") else None}
                      for d in p["documents"]],
        "pagination": {"label": pg["label"], "links": [
            {"kind": it["kind"], "label": it["label"], "url": _rebase_url(it.get("url", ""), m, at) if it.get("url") else ""}
            for it in pg["items"]]} if pg else None}}


def not_found_view(m: Manifest, at: str, pack: dict) -> dict:
    room = pack.get("labels", {}).get("room", "Reading Room")
    return {**_chrome(pack, at), "not_found": {"crumbs": [{"label": room, "url": at}, {"label": "Not found", "url": ""}],
                                                "room_label": room}}


# --- the page around it -------------------------------------------------------------

def script_json(obj: dict) -> str:
    """JSON for a <script type="application/json"> block: every "<" escaped, so no
    "</script" or "<!--" in the data can end or change the block."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")


def jsonld(obj: dict) -> str:
    # "</" inside a script block would end it; JSON allows the escaped slash.
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def head(title: str, robots: bool, canonical: str = "", social: dict | None = None, ld: str = "") -> dict:
    # "wp": the site's own <title> and meta tags, set by head_meta.head when the manifest has them.
    # "noindex_only": the lighter `noindex` a page that may be crawled but not indexed sends (text pages, D1).
    return {"title": title, "robots": robots, "canonical": canonical, "social": social, "jsonld": ld, "wp": None,
            "noindex_only": False}


def social(title: str, desc: str, url: str, image: str, site_title: str) -> dict:
    return {"title": title, "description": desc, "url": url, "image": image, "site_title": site_title}


# Without a pack chrome the page still has its skip link; nothing else is drawn.
SKIP_TEXT = "Skip to the content"
# build.render() puts the published URL of each theme file the pack names here
# ({pack file: URL}); a pack without theme files has no such key.
THEME_URLS = "_theme_urls"


def chrome_view(pack: dict, at: str = "") -> dict:
    """The room's own header, navigation and footer. A nav link to the room's own
    root (`at`, its path) is the current item, as WordPress's menu marks it, and a
    group holding it is current too (WordPress's current-menu-ancestor).

    Everything comes from the pack's `chrome`, as written: no label is composed
    and the site's name is never looked up from `identity`, so two sites with the
    same chrome draw the same bytes (tests/roomkit/test_generic.py).
    """
    c = pack.get("chrome")
    ident, urls = pack.get("identity", {}), pack.get(THEME_URLS, {})
    site = {"lang": ident.get("lang", "en"), "theme_color": ident.get("theme_color", ""),
            "icon": urls.get(ident.get("favicon") or "", "")}
    a11y = a11y_view(pack)
    if not c:
        return {"skip_text": SKIP_TEXT, "header": None, "footer": None, "site": site, "a11y": a11y}
    lg = ident.get("logo")
    logo = ({"src": urls[lg["src"]], "alt": lg["alt"], "width": lg.get("width"), "height": lg.get("height")}
            if lg and lg["src"] in urls else None)
    here = lambda url: bool(at) and bool(url) and urlsplit(url).path == at
    nav = [{"label": it["label"], "url": it.get("url", ""), "group": "links" in it,
            "current": here(it.get("url")) or any(here(ln["url"]) for ln in it.get("links", [])),
            "links": [{"label": ln["label"], "url": ln["url"], "current": here(ln["url"])} for ln in it.get("links", [])]}
           for it in c.get("nav", [])]
    notice = c.get("notice")
    footer = {"columns": [{"heading": col.get("heading", ""),
                           "links": [{"label": ln["label"], "url": ln["url"]} for ln in col["links"]]}
                          for col in c.get("footer", [])],
              "text": list(c.get("footer_text", []))}
    return {"skip_text": c["skip_text"], "site": site, "a11y": a11y,
            "header": {"home": {"label": c["home"]["label"], "url": c["home"]["url"]}, "logo": logo,
                       "tagline": c.get("tagline", ""), "nav_label": c["nav_label"],
                       "menu_label": c["menu_label"], "nav": nav,
                       "notice": {"text": notice["text"], "url": notice.get("url", "")} if notice else None},
            "footer": footer if footer["columns"] or footer["text"] else None}


# The plugin's buttons, in its order: (switch, kind, data-id, icon). Grayscale is not
# ported (the schema refuses it on).
A11Y_BUTTONS = (("enable_contrast", "contrast", "is_normal_contrast", "adjust"),
                ("enable_fontsize", "fontsize", "is_normal_fontsize", "font"))


def a11y_view(pack: dict) -> dict | None:
    """The site's accessibility toolbar (pack `a11y_toolbar`, the wp-accessibility
    plugin's own settings, `wpatb`), or None. The wrapper's classes are the plugin's,
    in its order, so its stylesheet and the room's theme rules both apply."""
    t = pack.get("a11y_toolbar")
    if not t:
        return None
    w = t["wpatb"]
    return {"classes": " ".join([w["responsive"], "a11y-toolbar", w["is_rtl"], w["is_right"],
                                 w["custom_location"], "room-a11y"]),
            "contrast_css": pack.get(THEME_URLS, {}).get(t["contrast_css"], ""),
            "factor": w["factor"],
            "buttons": [{"kind": kind, "data_id": data_id, "icon": icon, "label": w[kind]}
                        for on, kind, data_id, icon in A11Y_BUTTONS if w[on] == "true"]}


def page_view(main: str, content: dict, at: str, page_head: dict, scripts: list[str],
              chrome: dict | None = None) -> dict:
    """One whole page: `main` is the content template, `content` its view, and
    `chrome` (chrome_view) what the room draws around it. Without it, the bare
    skip link."""
    return {**content, "main": main, "at": at, "head": page_head, "scripts": scripts,
            "chrome": chrome if chrome is not None else chrome_view({})}
