"""Passage citations (GG): the manifest's `passages` block, page-level citations, and
the curated citations a room can resolve without a server.

Turned on by a pack's `features.passage-cite` (off unless the pack says so; plan
2026-10-13-unified-reading-room-frontend, Task 12; matrix row passage-citations,
disposition dynamic-api). The hybrid the user approved (2026-10-15):

- "Cite page" is static. Each page in the export carries `cite`, the site's own
  page-scoped citation (GGRR_Citations::format_reference with the page's
  permalink `#page-N`, exactly what `ggrr/v1/passage?slug=&page=` answers), and
  the reader shows it from `pages.json` without a request.
- "Cite" on an in-document search hit calls the live passage route (`api`) with
  the hit's offsets, as the WordPress reader does. When that call cannot be made
  or fails, the reader shows the page's citation instead, never a broken panel.
- Curated citations (rows of wp_ggrr_citations) ship as `citations.json`, keyed by
  stable_key and shaped like the `ggrr/v1/citation?key=` response, so a key an
  entity or power map names resolves with no server. No page lists them; live
  shows none either.

roomkit composes no citation: every reference string comes from the export.

    "passages": {
      "api": "https://<host>/wp-json/ggrr/v1/passage",   (rest_url on the site)
      "source": {"<plugin file>": "<sha256>"},            (optional; not rendered)
      "citations": [{"slug", "stable_key", "document_id", "page_id", "page_number",
                     "offset_start", "offset_end", "provenance_level",
                     "ocr_confidence", "citation_type", "bounding_box", "text"}],
      "excluded": [{"stable_key", "problem"}]             (optional; rows the exporter
                                                           could not ship, said out loud)
    }
    document: "document_id": <int>        (the site's id; stable keys hash it)
    page:     "cite": {"reference": "...", "provenance_level": "...",
                       "ocr_confidence": <number> | null}

A curated citation of a record the exporter excluded (the manifest's `excluded`)
is excluded with it and named on every build, like the record.

Refused (as manifest refusals, so the build stops): a malformed block; an `api`
that is not https; a citation naming a record the room does not hold, or one
whose document_id is not that record's; a stable_key that is not
sha256("{document_id}|{page_number}|{start}|{end}") (an empty page number for a
document-scope page, as GGRR_Citations::stable_key); a quoted text that is not
the page text between those offsets (counted in code points, as PHP's mb_*
functions count); two rows with one key; a page `cite` that is not the shape
above.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

FEATURE = "passage-cite"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHAPE = ("stable_key", "document_id", "page_id", "page_number", "offset_start", "offset_end",
         "provenance_level", "ocr_confidence", "citation_type", "bounding_box", "text")


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def gate(m, pack: dict):
    """The manifest as the pack lets the room see it: without passages when the pack
    does not turn them on (no passage route, no page citations, no citations.json)."""
    if getattr(m, "passages", None) and not enabled(pack):
        return replace(m, passages=None)
    return m


def stable_key(document_id: int, page_number: int | None, start: int, end: int) -> str:
    """GGRR_Citations::stable_key."""
    pn = "" if page_number is None else str(page_number)
    return hashlib.sha256(f"{document_id}|{pn}|{start}|{end}".encode()).hexdigest()


def slice_text(text: str, start: int, end: int) -> str:
    """mb_substr(text, start, end - start): Python strings count code points, as mb_* does."""
    return text[start:end]


def _int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _number_or_null(v: object) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))


def cite_problem(cite: object) -> str:
    """Why a page's `cite` is not {reference, provenance_level, ocr_confidence}, or ''."""
    if not isinstance(cite, dict) or set(cite) != {"reference", "provenance_level", "ocr_confidence"}:
        return "page cite is not {reference, provenance_level, ocr_confidence}"
    if not (isinstance(cite["reference"], str) and cite["reference"].strip()):
        return "page cite.reference is empty"
    if not isinstance(cite["provenance_level"], str):
        return "page cite.provenance_level is not a string"
    if not _number_or_null(cite["ocr_confidence"]):
        return "page cite.ocr_confidence is not a number or null"
    return ""


def parse(raw: object, docs: dict, excluded: dict | None = None) -> tuple[dict | None, list[str]]:
    """The block as the room uses it ({api, citations: {key: shape}, excluded}), or
    None; and every problem. `docs` maps each room record's slug to its Document;
    `excluded` the manifest's excluded records (slug -> problem): a curated
    citation of one of those is excluded with it, named, not refused."""
    excluded = excluded or {}
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["passages is not an object"]
    problems: list[str] = []
    api = raw.get("api")
    if not (isinstance(api, str) and api.startswith("https://") and "?" not in api and "#" not in api):
        problems.append(f"passages.api {api!r} is not an https:// URL without a query")
    src = raw.get("source", {})
    # "" where the exporter could not read the file, as entities.source.
    if not (isinstance(src, dict) and all(isinstance(k, str) and isinstance(v, str) and (v == "" or HEX64.match(v))
                                          for k, v in src.items())):
        problems.append("passages.source is not {file: sha256}")
    ex = raw.get("excluded", [])
    if not (isinstance(ex, list) and all(isinstance(e, dict) and isinstance(e.get("stable_key"), str)
                                         and isinstance(e.get("problem"), str) and e["problem"].strip()
                                         for e in ex)):
        problems.append("passages.excluded is not a list of {stable_key, problem}")
        ex = []
    rows = raw.get("citations", [])
    if not isinstance(rows, list):
        return None, problems + ["passages.citations is not a list"]
    out: dict[str, dict] = {}
    later: list[tuple[str, str]] = []
    for i, row in enumerate(rows):
        where = f"passages.citations[{i}]"
        if not isinstance(row, dict) or set(row) != {"slug", *SHAPE}:
            problems.append(f"{where} is not {{slug, {', '.join(SHAPE)}}}")
            continue
        key, slug = row["stable_key"], row["slug"]
        where = f"citation {key}" if isinstance(key, str) else where
        doc = docs.get(slug) if isinstance(slug, str) else None
        if doc is None and slug in excluded and isinstance(key, str):
            later.append((key, f"its record ({slug}) is excluded: {excluded[slug]}"))
            continue
        if doc is None:
            problems.append(f"{where}: names {slug!r}, which is not a record in this room")
            continue
        pn, s, e = row["page_number"], row["offset_start"], row["offset_end"]
        if not (_int(row["document_id"]) and _int(row["page_id"]) and (pn is None or _int(pn))
                and _int(s) and _int(e) and 0 <= s < e):
            problems.append(f"{where}: ids and offsets must be integers with 0 <= start < end")
            continue
        if doc.document_id != row["document_id"]:
            problems.append(f"{where}: document_id {row['document_id']} is not {slug}'s ({doc.document_id})")
            continue
        if not (isinstance(key, str) and key == stable_key(row["document_id"], pn, s, e)):
            problems.append(f"{where}: stable_key is not sha256(document_id|page|start|end)")
            continue
        if key in out:
            problems.append(f"{where}: two rows with one key")
            continue
        bb = row.get("bounding_box")
        bb_ok = (bb is None) or (
            isinstance(bb, (list, tuple))
            and len(bb) == 4
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) and 0.0 <= float(c) <= 1.0 for c in bb)
            and float(bb[0]) < float(bb[2])
            and float(bb[1]) < float(bb[3])
        )
        if not (isinstance(row["text"], str) and isinstance(row["provenance_level"], str)
                and _number_or_null(row["ocr_confidence"]) and bb_ok
                and (row["citation_type"] is None or isinstance(row["citation_type"], str))):
            problems.append(f"{where}: text, provenance_level, ocr_confidence, citation_type or bounding_box has the wrong type")
            continue
        if pn is not None:
            page = next((p for p in doc.pages if p.n == pn), None)
            if page is None:
                problems.append(f"{where}: {slug} has no page {pn}")
                continue
            if slice_text(page.text, s, e) != row["text"]:
                problems.append(f"{where}: text is not page {pn}'s text from {s} to {e}")
                continue
        out[key] = {k: row[k] for k in SHAPE}
    if problems:
        return None, problems
    return {"api": api, "citations": dict(sorted(out.items())),
            "excluded": [(e["stable_key"], e["problem"].strip()) for e in ex] + later}, []


def citations_json(block: dict) -> dict:
    """citations.json: each curated key as `ggrr/v1/citation?key=` answers it."""
    return {"citations": {k: {"found": True, "citation": c} for k, c in block["citations"].items()}}
