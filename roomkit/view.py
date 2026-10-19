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
from .manifest import PDF, READER, Document, Manifest


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
    # Only the room itself, record pages and (with the pack's entities on) entity
    # pages are in the static tree; other site pages under the same path
    # (collection, topic pages) stay on the site.
    if (rest == "" or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/", rest) and rest[:-1] in _slugs(m)
            or rest in _entity_paths(m)):
        return at + rest
    return url


def _entity_paths(m: Manifest) -> set[str]:
    # m.entities is None unless the pack turned the feature on (entities.gate).
    cache = getattr(m, "_room_entity_paths", None)
    if cache is None:
        cache = E.served(m.entities)
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
    return {"mount": doc.ext in READER, "pdf": doc.ext in PDF, "kind": "PDF" if doc.ext in PDF else "file",
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
            + [{"label": "SHA-256", "value": doc.sha256, "code": True}]
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


def _year(doc: Document) -> str:
    return doc.date[:4] if doc.date else ""


def _card(doc: Document, at: str) -> dict:
    ix = doc.index
    blob = " ".join([doc.title, doc.summary, doc.agency, ix.get("group", ""), ix.get("card_date", ""),
                     *ix.get("meta", []), *ix.get("facets", {}).values()]).lower()
    return {"text": re.sub(r"\s+", " ", blob).strip(), "group": ix.get("group", ""),
            "facets": [{"name": k, "value": v} for k, v in sorted(ix.get("facets", {}).items())],
            "url": f"{at}{doc.slug}/", "thumb_url": ix.get("thumb_url", ""),
            "date": doc.date, "card_date": ix.get("card_date", ""),
            "title": doc.title, "meta": list(ix.get("meta", [])), "summary": doc.summary}


def _noun(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def index_view(m: Manifest, at: str, pack: dict) -> dict:
    """The index. Every noun comes from the pack, and the jump nav is named by its
    visible label."""
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
    selects = [("group", group_label, [g for g in shown if grouped[g]])]
    selects += [(f["name"], f["label"], _facet_values(m, f["name"])) for f in ix.get("facets", [])]
    jump = [g for g in shown if grouped[g]]
    group_count = len([g for g in grouped if grouped[g]])
    return {**_chrome(pack, at), "layout": pack["layout"]["style"], "index": {
        "crumbs": [{"label": "Home", "url": m.site.base_url + "/"}, {"label": labels.get("room", "Reading Room"), "url": ""}],
        "eyebrow": ix.get("eyebrow", ""), "title": ix.get("title") or m.site.title, "lede": ix.get("lede", ""),
        "count": len(m.documents),
        "group_count": group_count,
        # Count nouns come from the pack, singular or plural by the count; never "+s".
        "records_noun": _noun(len(m.documents), labels["record_singular"], labels["record_plural"]),
        # The finder's live count (room.js) picks between these.
        "count_nouns": {"one": labels["record_singular"], "other": labels["record_plural"]},
        "groups_noun": _noun(group_count, labels["group_singular"], labels["groups_plural"]),
        "years": [years[0], years[-1]] if years else [],
        "links": [{"label": ln["label"], "url": ln["url"], "text": ln.get("text", "")} for ln in ix.get("links", [])],
        "search_placeholder": labels.get("search_placeholder", "Title, agency, summary..."),
        # Corpus search (pack features.corpus-search): room-search.js owns the finder and
        # loads the Pagefind index from here. None: room.js filters the cards as before.
        "search": {"pagefind_url": f"{at}{S.OUT}/",
                   "placeholder": labels.get("fulltext_placeholder", "Words in the records, titles, agencies..."),
                   "recent_key": f"room-recent-searches:{at}"} if S.enabled(pack) else None,
        # A select with fewer than two values could not narrow anything.
        "selects": [{"name": n, "label": lab, "values": vals} for n, lab, vals in selects if len(vals) >= 2],
        "jump": {"label": jump_label, "name": jump_name,
                 # Bare slugs, as the WordPress index used, so old #anchors still land.
                 "groups": [{"id": slugify(g), "label": g} for g in jump], "folded": len(jump) > 12}
                if len(jump) > 1 else None,
        "sections": [{"id": slugify(g), "label": g, "cards": [_card(d, at) for d in grouped[g]]} for g in shown],
        "empty_group_text": ix.get("empty_group_text") or "No records yet.",
    }}


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


def not_found_view(m: Manifest, at: str, pack: dict) -> dict:
    room = pack.get("labels", {}).get("room", "Reading Room")
    return {**_chrome(pack, at), "not_found": {"crumbs": [{"label": room, "url": at}, {"label": "Not found", "url": ""}],
                                                "room_label": room}}


# --- the page around it -------------------------------------------------------------

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
