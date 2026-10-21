"""The view model: the plain dicts the room's templates render.

Everything the templates (`templates/room/`) show comes from here, as plain
dicts, lists and strings, so a template never reaches into roomkit's
`Manifest`/`Document`. Civica will build the same dicts from its own
`document` and `document_page` rows and render the same templates (plan
2026-10-13-unified-reading-room-frontend, Task 3a and Milestone 6).

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

from . import entities as E
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

def reader_view(doc: Document, at: str) -> dict:
    """The reader mount (or the download block for files the engine cannot show)."""
    return {"has_file": doc.has_file, "no_file": doc.display.get("no_file", ""), "mount": doc.ext in READER, "pdf": doc.ext in PDF, "kind": "PDF" if doc.ext in PDF else "file",
            "file_url": doc.file_url, "download_url": doc.download_url,
            # The reader may load a verified viewing copy; every link stays the original.
            "reader_url": doc.view_url or doc.file_url, "view_note": bool(doc.view_url),
            "ext": doc.ext, "mime": doc.mime, "slug": doc.slug, "title": doc.title, "poster_url": doc.poster_url,
            # With page texts, the engine (0.6.0+) searches them in the browser.
            "pages_url": f"{at}{doc.slug}/pages.json" if doc.pages else "",
            "features": "spread,search,lightbox,fullscreen" if doc.pages else "spread,lightbox,fullscreen"}


def _details(doc: Document, m: Manifest, at: str) -> list[dict]:
    rows = doc.display.get("details", [])
    if not rows:
        rows = ([{"label": "Agency", "value": doc.agency}] if doc.agency else []) \
            + ([{"label": "Date", "value": doc.date}] if doc.date else []) \
            + ([{"label": "SHA-256", "value": doc.sha256, "code": True}] if doc.has_file else [])
    return [{"label": r["label"], "value": r["value"], "code": bool(r.get("code")),
             "url": _rebase_url(r["url"], m, at) if r.get("url") else "",
             # Judged on the URL as the site wrote it, before any rebase.
             "external": _external(r.get("url", ""), m), "note": r.get("note", "")} for r in rows]


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
        "reader": reader_view(doc, at),
        "details": _details(doc, m, at),
        "file_kind": "PDF" if doc.ext in PDF else "file",
        "has_file": doc.has_file,
        "file_url": doc.file_url, "download_url": doc.download_url, "archive_url": doc.archive_url,
        "citation": doc.citation,
        "groups": _groups(doc, m, at),
        "notes_lines": d["notes"].split("\n") if d.get("notes") else [],
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


def thumb_path(doc: Document) -> str:
    """The room's copy of the card thumbnail (manifest index.thumb), before its
    content hash is added; empty when the manifest carries none."""
    t = doc.index.get("thumb")
    return f"assets/thumbs/{doc.slug}.{THUMB_TYPES[t['mime']][0]}" if t else ""


def _card(doc: Document, at: str, multi: tuple[str, ...] = (), sortable: bool = False) -> dict:
    ix = doc.index
    blob = " ".join([doc.title, doc.summary, doc.agency, ix.get("group", ""), ix.get("card_date", ""),
                     *ix.get("meta", []), *ix.get("facets", {}).values(),
                     *([ix["badge"]] if ix.get("badge") else [])]).lower()
    return {"text": re.sub(r"\s+", " ", blob).strip(), "group": ix.get("group", ""),
            "facets": [{"name": k, "value": v} for k, v in sorted(ix.get("facets", {}).items())],
            # A multi-valued facet (vendor): the values as JSON, matched whole by room.js.
            "multi": [{"name": n, "json": json.dumps(ix.get("browse", {}).get(n, []), ensure_ascii=False)} for n in multi],
            "sort_title": doc.title.lower(), "sortable": sortable,
            "url": f"{at}{doc.slug}/", "thumb_url": at + thumb_path(doc) if ix.get("thumb") else ix.get("thumb_url", ""),
            "date": doc.date, "card_date": ix.get("card_date", ""),
            "title": doc.title, "meta": list(ix.get("meta", [])), "summary": doc.summary,
            "badge": ix.get("badge", ""), "badge_kind": ix.get("badge_kind", ""), "badge_sr": ix.get("badge_sr", "")}


def _suggest(m: Manifest, at: str) -> str:
    """site.index.suggest as room-search.js reads it: recent documents as titles and room URLs."""
    sg = m.site.index.get("suggest")
    if not sg:
        return ""
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
    # One source for the group noun: the pack. The manifest's group_label is not shown.
    group_label = labels["group"]
    # The nav is named by its visible label, minus trailing punctuation (WCAG 2.5.3). The same
    # short form goes before a folded list's count: "Jump to jurisdiction (17)", not ": (17)".
    jump_label = labels["jump"]
    jump_name = jump_label.rstrip(" :;,.!?\u2026\u2013\u2014")
    years = sorted({_year(d) for d in m.documents if _year(d)})
    selects = [{"kind": "group", "name": "group", "label": group_label, "values": [g for g in shown if grouped[g]],
                "sets": _group_sets(ix.get("group_sets", []), [g for g in shown if grouped[g]])}]
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
        "eyebrow": ix.get("eyebrow", ""), "title": ix.get("title") or m.site.title, "lede": ix.get("lede", ""),
        "count": len(m.documents),
        "group_count": group_count,
        # Count nouns come from the pack, singular or plural by the count; never "+s".
        "records_noun": _noun(len(m.documents), labels["record_singular"], labels["record_plural"]),
        # The header's count may name records differently from the finder's count (GG).
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
                   "suggest": _suggest(m, at)} if S.enabled(pack) else None,
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
        "sections": [{"id": slugify(g), "label": g, "cards": [_card(d, at, multi, bool(ix.get('sort'))) for d in grouped[g]]} for g in shown],
        "empty_group_text": ix.get("empty_group_text") or "No records yet.",
        "browse": _browse(facet_pages or [], browse_heading, at),
        "collections_grid": _grid(m, at),
    }}


def facet_view(p: dict, m: Manifest, at: str, pack: dict) -> dict:
    """One facet page (browse.py): the records listed under one value, as index cards."""
    labels = pack.get("labels", {})
    n = len(p["docs"])
    return {**_chrome(pack, at), "layout": pack["layout"]["style"], "facet": {
        "key": f"{p['name']}/{p['slug']}", "room_only": p["room_only"],
        "crumbs": [{"label": labels.get("room", "Reading Room"), "url": at}, {"label": p["title"], "url": ""}],
        "eyebrow": p["label"], "title": p["title"], "count": n,
        "records_noun": _noun(n, labels["record_singular"], labels["record_plural"]),
        "cards": [_card(d, at) for d in p["docs"]]}}


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


def _grid(m: Manifest, at: str) -> dict | None:
    """The collections table on the index, or None (no block, or the switch off)."""
    gr = (getattr(m, "collections", None) or {}).get("grid")
    if not gr:
        return None
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
    return {"title": title, "robots": robots, "canonical": canonical, "social": social, "jsonld": ld}


def social(title: str, desc: str, url: str, image: str, site_title: str) -> dict:
    return {"title": title, "description": desc, "url": url, "image": image, "site_title": site_title}


# Without a pack chrome the page still has its skip link; nothing else is drawn.
SKIP_TEXT = "Skip to the content"


def chrome_view(pack: dict) -> dict:
    """The room's own header, navigation and footer.

    Everything comes from the pack's `chrome`, as written: no label is composed
    and the site's name is never looked up from `identity`, so two sites with the
    same chrome draw the same bytes (tests/roomkit/test_generic.py).
    """
    c = pack.get("chrome")
    if not c:
        return {"skip_text": SKIP_TEXT, "header": None, "footer": None}
    nav = [{"label": it["label"], "url": it.get("url", ""), "group": "links" in it,
            "links": [{"label": ln["label"], "url": ln["url"]} for ln in it.get("links", [])]}
           for it in c.get("nav", [])]
    notice = c.get("notice")
    footer = {"columns": [{"heading": col.get("heading", ""),
                           "links": [{"label": ln["label"], "url": ln["url"]} for ln in col["links"]]}
                          for col in c.get("footer", [])],
              "text": list(c.get("footer_text", []))}
    return {"skip_text": c["skip_text"],
            "header": {"home": {"label": c["home"]["label"], "url": c["home"]["url"]},
                       "tagline": c.get("tagline", ""), "nav_label": c["nav_label"],
                       "menu_label": c["menu_label"], "nav": nav,
                       "notice": {"text": notice["text"], "url": notice.get("url", "")} if notice else None},
            "footer": footer if footer["columns"] or footer["text"] else None}


def page_view(main: str, content: dict, at: str, page_head: dict, scripts: list[str],
              chrome: dict | None = None) -> dict:
    """One whole page: `main` is the content template, `content` its view, and
    `chrome` (chrome_view) what the room draws around it. Without it, the bare
    skip link."""
    return {**content, "main": main, "at": at, "head": page_head, "scripts": scripts,
            "chrome": chrome if chrome is not None else chrome_view({})}
