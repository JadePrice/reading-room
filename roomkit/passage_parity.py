"""parity.passages: a built room's passage citations against the live passage route.

Matrix row passage-citations (GG, dynamic-api). The room ships what can be static
(each page's citation in pages.json, the curated citations in citations.json) and
asks the live route for a span; this checks that the static half says exactly what
the route says, and that what a span cite would send resolves to the room's text:

  pages      the room's `cite` for a page == the live page-scoped answer
             (`?slug=&page=`): reference, provenance_level, ocr_confidence.
  spans      the live answer for `?slug=&page=&start=&end=`: its text is the room's
             page text between those offsets (code points, as mb_substr), its
             stable_key is sha256("{document_id}|{page}|{start}|{end}"), and its
             reference is the room's page citation.
  citations  the live `ggrr/v1/citation?key=` answer: its text is the room's page
             text between its offsets, its key is the formula's, and where the
             room ships that key in citations.json the two are equal field by field. A
             document-scope citation (page_number null: the record's page-null row, which
             the room has no page for) is held to citations.json alone.

Two steps, like parity.entities:
1. `roomkit parity --passages-fetch --out ROOM --sample N [--keys KEYS.txt]` makes the
   paced public GETs (read-only, a browser UA, `--pace` seconds apart, 2 by default;
   it stops at the first 429 or 403 and says so) and prints the live file.
2. `roomkit parity --passages LIVE.json --out ROOM` compares; exit 1 on any difference.

The live file (the Mac can write it the same way, through the origin):

    {"site": "glassgovernment", "fetched": "<ISO time>", "source": "<how>",
     "pages":     [{"slug", "page", "status", "response"}],
     "spans":     [{"slug", "page", "start", "end", "status", "response"}],
     "citations": [{"key", "status", "response"}],
     "stopped":   "<why the fetch stopped early>"            (optional)}
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from roomkit import passages as PS

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
WORD = re.compile(r"[a-z]{5,}")


class LiveError(ValueError):
    pass


# --- the room ------------------------------------------------------------------

def room_data(room: Path) -> dict:
    """{api, pages: {slug: [page dicts]}, citations: {key: shape}} from a built room."""
    lock = json.loads((room / "room.lock.json").read_text(encoding="utf-8"))
    cfg = (room / lock["assets"]["assets/rr-config.js"]).read_text(encoding="utf-8")
    api = json.loads(cfg[cfg.index("{"):cfg.rindex("}") + 1]).get("passageUrl", "")
    pages = {}
    for logical, published in lock["assets"].items():
        if logical.endswith("/pages.json"):
            data = json.loads((room / published).read_text(encoding="utf-8"))
            pages[data["slug"]] = data["pages"]
    cites = {}
    if (room / "citations.json").is_file():
        cites = {k: v["citation"] for k, v in
                 json.loads((room / "citations.json").read_text(encoding="utf-8"))["citations"].items()}
    return {"api": api, "pages": pages, "citations": cites}


def _page(room: dict, slug: str, n: int) -> dict | None:
    return next((p for p in room["pages"].get(slug, []) if p["n"] == n), None)


# --- the sample and the fetch --------------------------------------------------

def plan(room: dict, sample: int, keys: list[str] = ()) -> dict:
    """Which pages and spans to ask for: `sample` cited pages spread evenly over the
    room's records (sorted by slug), and on each a span from the first lowercase word
    of 5+ letters past a third of the page to 120 code points on (at most the page)."""
    cited = [(s, p) for s in sorted(room["pages"]) for p in room["pages"][s] if p.get("cite")]
    step = max(1, len(cited) // max(1, sample))
    chosen = cited[::step][:sample]
    spans = []
    for slug, p in chosen:
        text = p["text"]
        m = WORD.search(text, len(text) // 3) or WORD.search(text)
        if m:
            spans.append({"slug": slug, "page": p["n"], "start": m.start(),
                          "end": min(len(text), m.start() + 120)})
    return {"pages": [{"slug": s, "page": p["n"]} for s, p in chosen], "spans": spans,
            "citations": [{"key": k} for k in keys]}


def http_get(url: str, timeout: float = 30.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def fetch(api: str, want: dict, get: Callable[[str], tuple[int, str]] = http_get, pace: float = 2.0,
          sleep: Callable[[float], None] = time.sleep) -> dict:
    """The live file for `want` (plan's output). Paced; stops at the first 429 or 403."""
    if not api:
        raise LiveError("the room has no passage route (pack features.passage-cite off, or no passages block)")
    citation = api.rsplit("/passage", 1)[0] + "/citation"
    out = {"site": "glassgovernment", "fetched": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": f"GET {api} and {citation}, {pace:g} s apart", "pages": [], "spans": [], "citations": []}
    jobs = ([("pages", w, api, {"slug": w["slug"], "page": w["page"]}) for w in want["pages"]]
            + [("spans", w, api, {"slug": w["slug"], "page": w["page"], "start": w["start"], "end": w["end"]})
               for w in want["spans"]]
            + [("citations", w, citation, {"key": w["key"]}) for w in want["citations"]])
    for i, (kind, w, base, q) in enumerate(jobs):
        if i:
            sleep(pace)
        status, body = get(base + "?" + urllib.parse.urlencode(q))
        if status in (429, 403):
            out["stopped"] = f"{status} on {kind} {q}; no further requests"
            break
        try:
            resp = json.loads(body)
        except json.JSONDecodeError:
            resp = None
        out[kind].append({**w, "status": status, "response": resp})
    return out


# --- the comparison ------------------------------------------------------------

def _list(data: dict, key: str) -> list:
    v = data.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, dict) and isinstance(x.get("response"), (dict, type(None)))
                                          for x in v):
        raise LiveError(f"live file: {key} is not a list of fetched answers")
    return v


def compare(live: dict, room: dict) -> dict:
    if not isinstance(live, dict) or live.get("site") != "glassgovernment":
        raise LiveError("live file is not a glassgovernment passages file")
    rep = {"site": live["site"], "fetched": live.get("fetched", ""), "source": live.get("source", ""),
           "stopped": live.get("stopped", ""), "pages": [], "spans": [], "citations": []}

    for x in _list(live, "pages"):
        probs = []
        r, cite = x["response"] or {}, (_page(room, x["slug"], x["page"]) or {}).get("cite")
        if not cite:
            probs.append("the room has no citation for this page")
        elif not r.get("found"):
            probs.append(f"live answered {x['status']} {r.get('error', '')}".strip())
        else:
            p = r.get("passage") or {}
            if r.get("reference") != cite["reference"]:
                probs.append(f"reference differs: live {r.get('reference')!r}, room {cite['reference']!r}")
            for k in ("provenance_level", "ocr_confidence"):
                if p.get(k) != cite[k]:
                    probs.append(f"{k} differs: live {p.get(k)!r}, room {cite[k]!r}")
        rep["pages"].append({"slug": x["slug"], "page": x["page"], "ok": not probs, "problems": probs})

    for x in _list(live, "spans"):
        probs = []
        r, page = x["response"] or {}, _page(room, x["slug"], x["page"])
        if page is None:
            probs.append("the room has no such page")
        elif not r.get("found"):
            probs.append(f"live answered {x['status']} {r.get('error', '')}".strip())
        else:
            p = r.get("passage") or {}
            if p.get("text") != PS.slice_text(page["text"], x["start"], x["end"]):
                probs.append("the live quote is not the room's page text between those offsets")
            if (p.get("offset_start"), p.get("offset_end")) != (x["start"], x["end"]):
                probs.append("live resolved other offsets")
            did = p.get("document_id")
            if not (isinstance(did, int) and p.get("stable_key") == PS.stable_key(did, x["page"], x["start"], x["end"])):
                probs.append("the live stable_key is not sha256(document_id|page|start|end)")
            if page.get("cite") and r.get("reference") != page["cite"]["reference"]:
                probs.append("the live reference is not the room's page citation")
        rep["spans"].append({"slug": x["slug"], "page": x["page"], "start": x["start"], "end": x["end"],
                             "ok": not probs, "problems": probs})

    for x in _list(live, "citations"):
        probs = []
        r = x["response"] or {}
        c = r.get("citation") if r.get("found") else None
        if not c:
            probs.append(f"live answered {x['status']} {r.get('error', '') if isinstance(r, dict) else ''}".strip())
        else:
            if c.get("stable_key") != PS.stable_key(c["document_id"], c.get("page_number"), c["offset_start"], c["offset_end"]):
                probs.append("the live key is not sha256(document_id|page|start|end)")
            if c.get("page_number") is None:
                # A document-scope citation (the record's page-null row): the room
                # exports no such page, so its text is held to citations.json only.
                if x["key"] not in room["citations"]:
                    probs.append("a document-scope citation the room does not ship in citations.json")
            else:
                owner = [s for s, pages in room["pages"].items()
                         if any(p["n"] == c.get("page_number") and PS.slice_text(p["text"], c["offset_start"], c["offset_end"])
                                == c.get("text") for p in pages)]
                if not owner:
                    probs.append("no record in the room has that text on that page between those offsets")
            if x["key"] in room["citations"] and room["citations"][x["key"]] != c:
                diff = sorted(k for k in set(c) | set(room["citations"][x["key"]])
                              if c.get(k) != room["citations"][x["key"]].get(k))
                probs.append(f"citations.json differs from live in {', '.join(diff)}")
        rep["citations"].append({"key": x["key"], "in_room": x["key"] in room["citations"],
                                 "scope": "document" if (c or {}).get("page_number") is None else "page",
                                 "ok": not probs, "problems": probs})

    rep["ok"] = not rep["stopped"] and all(e["ok"] for k in ("pages", "spans", "citations") for e in rep[k])
    return rep


def text(rep: dict) -> str:
    counts = ", ".join(f"{k} {sum(e['ok'] for e in rep[k])}/{len(rep[k])}" for k in ("pages", "spans", "citations"))
    lines = [f"{'AGREES' if rep['ok'] else 'DIFFERS'}: {counts} ({rep['site']}, live read {rep['fetched']})"]
    doc_scope = sum(e.get("scope") == "document" for e in rep["citations"])
    if doc_scope:
        lines.append(f"   {doc_scope} citation(s) document-scope: held to citations.json, no page text to check")
    if rep["stopped"]:
        lines.append(f"   fetch stopped early: {rep['stopped']}")
    for k in ("pages", "spans", "citations"):
        for e in rep[k]:
            if not e["ok"]:
                where = e.get("key") or f"{e['slug']} p.{e['page']}" + (f" {e['start']}-{e['end']}" if "start" in e else "")
                lines += [f"   {k} {where}: {p}" for p in e["problems"]]
    return "\n".join(lines)


def load_live(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveError(f"cannot read {path}: {exc}") from exc
