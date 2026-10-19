"""Does the live site say what the manifest says? Read-only HTTP GETs.

For every document, fetch the site's own page at `base_url + room_path + slug/`
and check, after HTML-unescaping the page:

  citation   the manifest's citation text appears verbatim
  reader     the reader mount's data-file-url is the manifest's view_url or url
  download   the manifest's download_url appears

This is what makes an exporter that repeats a site's formula (dd's citation is
built inline in its template) safe: any drift between the two shows up here,
row by row, before a static page could publish it.

Polite by default: one request at a time, a pause between them, and a retry
with backoff on 429 (Hostinger rate-limits). A cache-busting query is added so
the comparison is with what the site renders now, not a cached copy.

The second half of the file reads the parity matrix (`parity-matrix.yaml`):
which features the room must match before cutover, and how far it has got.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import Callable

try:
    from roomkit.manifest import READER, Manifest
except ImportError:
    from scripts.roomkit.manifest import READER, Manifest

UA = "roomkit-parity/0.1 (+https://deflockdane.org; read-only)"
READER_URL = re.compile(r'class="rr-reader"[^>]*?data-file-url="([^"]*)"', re.S)


class _DLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_dl = False
        self.in_dt = False
        self.in_dd = False
        self.cur_dt: list[str] = []
        self.cur_dd: list[str] = []
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "dl":
            classes = (dict(attrs).get("class") or "").split()
            if any(c in classes for c in ("ggrr-doc__dl", "deflock-reading-room__dl", "room__dl")):
                self.in_dl = True
        elif self.in_dl:
            if tag == "dt":
                self.in_dt = True
                self.cur_dt = []
            elif tag == "dd":
                self.in_dd = True
                self.cur_dd = []

    def handle_endtag(self, tag: str):
        if tag == "dl" and self.in_dl:
            self.in_dl = False
        elif self.in_dl:
            if tag == "dt":
                self.in_dt = False
            elif tag == "dd":
                self.in_dd = False
                dt_str = unescape(" ".join("".join(self.cur_dt).split()))
                dd_str = unescape(" ".join("".join(self.cur_dd).split()))
                if dt_str:
                    self.rows.append((dt_str, dd_str))

    def handle_data(self, data: str):
        if self.in_dt:
            self.cur_dt.append(data)
        elif self.in_dd:
            self.cur_dd.append(data)


def check_details(expected_details: list[dict], html: str) -> list[str]:
    """Check that doc.display['details'] matches the live page's dl rail."""
    p = _DLParser()
    p.feed(html)
    live_rows = p.rows
    if not live_rows:
        return ["no details list (<dl>) found"]
    if len(live_rows) != len(expected_details):
        return [f"details row count {len(live_rows)} != {len(expected_details)}"]
    problems = []
    for i, (exp, (live_label, live_val)) in enumerate(zip(expected_details, live_rows)):
        lab = exp.get("label", "")
        if lab != live_label:
            problems.append(f"detail #{i} label {live_label!r} != {lab!r}")
            continue
        exp_val = str(exp.get("value", ""))
        if exp_val not in live_val:
            problems.append(f"detail #{i} ({lab}) value {exp_val!r} not in {live_val!r}")
        note = exp.get("note")
        if note and str(note) not in live_val:
            if not (lab == "Permanent copy" and str(note) == "Verified present" and "verified" in live_val.lower()):
                problems.append(f"detail #{i} ({lab}) note {note!r} not in {live_val!r}")
    return problems


def check_header_actions(expected_header: dict, html: str) -> list[str]:
    """Check that doc.display['header'] matches the page's file-meta and actions."""
    problems = []
    text = unescape(html)
    for m in expected_header.get("meta") or []:
        if str(m) not in text:
            problems.append(f"header meta {m!r} not in page")
    orig = expected_header.get("original_url")
    if orig and orig not in html and f'href="{orig}"' not in html:
        if not (orig.endswith("?original=1") and "?original=1" in html):
            problems.append(f"header original_url {orig!r} not in page")
    ia_url = expected_header.get("ia_url")
    if ia_url and ia_url not in html:
        problems.append(f"header ia_url {ia_url!r} not in page")
    if expected_header.get("ia_pending") and "Internet Archive backup pending" not in text:
        problems.append("header ia_pending badge not in page")
    return problems


def check_badges_notice(display: dict, html: str) -> list[str]:
    """Check that doc.display badge and notice match the page."""
    problems = []
    text = unescape(html)
    norm_text = " ".join(text.split())

    badge = display.get("badge")
    badge_kind = display.get("badge_kind")
    if badge:
        if badge not in text:
            problems.append(f"badge {badge!r} not in page")
        if badge_kind and f"--{badge_kind}" not in html:
            problems.append(f"badge_kind {badge_kind!r} not in page")

    notice = display.get("notice")
    if notice:
        heading = notice.get("heading")
        if heading and heading not in text:
            problems.append(f"notice heading {heading!r} not in page")
        body = notice.get("body")
        if body and " ".join(body.split()) not in norm_text:
            problems.append(f"notice body {body!r} not in page")
        report = notice.get("report")
        if report and " ".join(report.split()) not in norm_text:
            problems.append(f"notice report {report!r} not in page")
    return problems


def _plain(html: str) -> str:
    """Strip tags first then unescape entities, preserving entity-encoded brackets."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def check_link_groups(expected_groups: list[dict], html: str) -> list[str]:
    """Check that doc.display['groups'] matches the page's link groups in order."""
    problems = []
    text = unescape(html)
    plain_text = _plain(html)

    last_group_pos = 0
    for gi, g in enumerate(expected_groups):
        heading = g.get("heading", "")
        if not heading:
            continue
        gpos = text.find(heading, last_group_pos)
        if gpos == -1:
            problems.append(f"group #{gi} heading {heading!r} not in page")
            continue
        last_group_pos = gpos

        blurb = g.get("blurb")
        if blurb and " ".join(blurb.split()) not in plain_text:
            problems.append(f"group #{gi} ({heading}) blurb {blurb!r} not in page")

        last_item_pos = gpos
        for ii, it in enumerate(g.get("items", [])):
            label = it.get("label", "")
            if not label:
                continue
            ipos = text.find(label, last_item_pos)
            if ipos == -1:
                if label not in plain_text:
                    problems.append(f"group #{gi} item #{ii} label {label!r} not in page")
                    continue
            else:
                last_item_pos = ipos

            url = it.get("url")
            if url:
                parsed = urllib.parse.urlparse(url)
                path = parsed.path or url
                if url not in html and path not in html:
                    problems.append(f"group #{gi} item #{ii} ({label}) url {url!r} not in page")

            quote = it.get("quote")
            if quote and " ".join(quote.split()) not in plain_text:
                problems.append(f"group #{gi} item #{ii} ({label}) quote {quote!r} not in page")

            kind = it.get("kind")
            if kind and kind not in plain_text:
                problems.append(f"group #{gi} item #{ii} ({label}) kind {kind!r} not in page")

            meta = it.get("meta")
            if meta and meta not in plain_text:
                problems.append(f"group #{gi} item #{ii} ({label}) meta {meta!r} not in page")

    return problems


def check_notes(expected_notes: str | None, html: str) -> list[str]:
    """Check that doc.display['notes'] matches the page's notes block."""
    problems = []
    notes = (expected_notes or "").strip()
    plain_text = _plain(html)

    has_notes_block = (
        'class="ggrr-doc__notes"' in html
        or 'class="deflock-reading-room__notes"' in html
        or 'class="room__notes"' in html
    )

    if notes:
        norm_notes = " ".join(notes.split())
        if norm_notes not in plain_text:
            problems.append(f"notes {notes!r} not in page")
        if not has_notes_block:
            problems.append("notes block absent from page")
    else:
        if has_notes_block:
            problems.append("unexpected notes block in page")

    return problems


def http_get(url: str, timeout: float = 30.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def check_page(doc, html: str) -> list[str]:
    """The ways one live page disagrees with its manifest row. Empty = agrees."""
    problems = []
    text = unescape(html)
    if doc.citation not in text:
        problems.append("citation differs")
    if doc.ext in READER:
        m = READER_URL.search(html)
        want = doc.view_url or doc.file_url
        if not m:
            problems.append("no reader mount")
        elif unescape(m.group(1)) != want:
            problems.append(f"reader url {unescape(m.group(1))!r} != {want!r}")
    if doc.download_url not in text:
        problems.append("download url absent")
    if doc.display and doc.display.get("details"):
        problems.extend(check_details(doc.display["details"], html))
    if doc.display and doc.display.get("header"):
        problems.extend(check_header_actions(doc.display["header"], html))
    if doc.display and (doc.display.get("badge") or doc.display.get("notice")):
        problems.extend(check_badges_notice(doc.display, html))
    if doc.display and doc.display.get("groups"):
        problems.extend(check_link_groups(doc.display["groups"], html))
    notes = doc.display.get("notes") if doc.display else None
    problems.extend(check_notes(notes, html))
    return problems


def pages_from_file(path) -> Callable[[str], tuple[int, str]]:
    """A `get` that answers from a file of "<slug>\t<code>\t<base64 html>" lines
    (exporters/*-fetch-pages.sh), for sites whose edge rate-limits a parity run."""
    import base64
    from pathlib import Path
    pages = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            slug, code, b64 = (line.split("\t") + ["", ""])[:3]
            pages[slug] = (int(code or 0), base64.b64decode(b64).decode("utf-8", "replace"))
    def get(url: str) -> tuple[int, str]:
        slug = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return pages.get(slug, (0, ""))
    return get


def run(m: Manifest, get: Callable[[str], tuple[int, str]] = http_get, pause: float = 1.0,
        bust: bool = True, sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    stamp = str(int(time.time()))
    results = []
    for i, doc in enumerate(m.documents):
        url = f"{m.site.base_url}{m.site.room_path}{doc.slug}/"
        fetch = f"{url}?roomkit_cb={stamp}" if bust else url
        if i:
            sleep(pause)
        status, html = get(fetch)
        for wait in (5, 15, 45):
            if status != 429:
                break
            sleep(wait)
            status, html = get(fetch)
        if status != 200:
            results.append({"slug": doc.slug, "ok": False, "problems": [f"HTTP {status}"]})
            continue
        problems = check_page(doc, html)
        results.append({"slug": doc.slug, "ok": not problems, "problems": problems})
    return results


# --- the parity matrix: what the unified room must do before any cutover ----
#
# scripts/roomkit/parity-matrix.yaml, one row per feature, a disposition and a
# need/status per site (wiki/reading-room-parity.md). `roomkit parity --matrix`
# turns it into a number and an exit code. Malformed rows are refused, never
# guessed at: a matrix that silently misreads a row would report green early.
#
# Sign-off on a `dropped` row. A dropped row needs the user's sign-off, text
# recorded in `signoff` (who and when). Two cases are kept apart:
#   signoff absent or null  -> awaiting sign-off. Reported as such, and it blocks
#                              every site until the user signs.
#   signoff "" or not text  -> malformed, refused. An empty string reads as
#                              "signed with nothing", which is not a decision.
# `signoff` on any other disposition is refused: it would read as a sign-off
# that gates nothing.

SITES = ("deflockdane", "glassgovernment")
DISPOSITIONS = ("static", "static-later", "dynamic-api", "stays-wordpress", "deferred", "dropped")
NEEDS = ("required", "optional", "n/a")
STATUSES = ("missing", "partial", "done")
SURFACES = ("document", "index", "collections", "topics", "entities", "power-maps", "requests", "translation",
            "read-aloud", "sitemaps", "machine-text", "files", "chrome", "admin")
# Dispositions whose required rows the static room has to deliver before cutover.
GATED = ("static", "dynamic-api")
ROW_KEYS = {"id", "surface", "live", "disposition", "sites", "acceptance", "check", "signoff"}
ROW_REQUIRED = ROW_KEYS - {"signoff"}
ROW_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CHECK = re.compile(r"^(?:browser|parity\.[a-z][a-z0-9_]*)$")


class MatrixError(ValueError):
    """The matrix cannot be trusted as written. Every problem is listed."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _row_problems(i: int, row: object) -> list[str]:
    if not isinstance(row, dict):
        return [f"row #{i}: not a mapping"]
    rid = row.get("id") if isinstance(row.get("id"), str) else f"#{i}"
    out = [f"{rid}: unknown key {k!r}" for k in sorted(set(row) - ROW_KEYS, key=str)]
    out += [f"{rid}: missing {k!r}" for k in sorted(ROW_REQUIRED - set(row))]
    if "id" in row and not (isinstance(row["id"], str) and ROW_ID.match(row["id"])):
        out.append(f"{rid}: id {row['id']!r} is not a lowercase-hyphen slug")
    for k in ("live", "acceptance"):
        if k in row and not (isinstance(row[k], str) and row[k].strip()):
            out.append(f"{rid}: {k} is not text")
    if "surface" in row and row["surface"] not in SURFACES:
        out.append(f"{rid}: unknown surface {row['surface']!r}")
    if "check" in row and not (isinstance(row["check"], str) and CHECK.match(row["check"])):
        out.append(f"{rid}: check {row['check']!r} is neither 'browser' nor 'parity.<name>'")
    disp = row.get("disposition")
    if "disposition" in row and disp not in DISPOSITIONS:
        out.append(f"{rid}: unknown disposition {disp!r}")
    if "signoff" in row:
        so = row["signoff"]
        if disp != "dropped":
            out.append(f"{rid}: signoff on a {disp!r} row (only dropped rows are signed off)")
        elif so is not None and not (isinstance(so, str) and so.strip()):
            out.append(f"{rid}: dropped with an empty signoff (leave it null while awaiting the user)")
    sites = row.get("sites")
    if "sites" in row:
        if not isinstance(sites, dict):
            out.append(f"{rid}: sites is not a mapping")
        else:
            out += [f"{rid}: unknown site {s!r}" for s in sorted(set(sites) - set(SITES), key=str)]
            out += [f"{rid}: no entry for site {s!r}" for s in SITES if s not in sites]
            for s in SITES:
                e = sites.get(s)
                if s not in sites:
                    continue
                if not isinstance(e, dict):
                    out.append(f"{rid}: {s} is not {{need, status}}")
                    continue
                out += [f"{rid}: {s}: unknown key {k!r}" for k in sorted(set(e) - {"need", "status"}, key=str)]
                if e.get("need") not in NEEDS:
                    out.append(f"{rid}: {s}: unknown need {e.get('need')!r}")
                if e.get("status") not in STATUSES:
                    out.append(f"{rid}: {s}: unknown status {e.get('status')!r}")
    return out


def parse_matrix(data: object) -> list[dict]:
    """The matrix's rows, checked. Raises MatrixError naming every problem."""
    if not isinstance(data, dict):
        raise MatrixError(["the matrix is not a mapping with a 'rows' list"])
    problems = [f"unknown top-level key {k!r}" for k in sorted(set(data) - {"rows"}, key=str)]
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise MatrixError(problems + ["the matrix has no 'rows' list"])
    seen: set[str] = set()
    for i, row in enumerate(rows):
        problems += _row_problems(i, row)
        rid = row.get("id") if isinstance(row, dict) else None
        if isinstance(rid, str):
            if rid in seen:
                problems.append(f"{rid}: duplicate id")
            seen.add(rid)
    if problems:
        raise MatrixError(problems)
    return rows


def load_matrix(path) -> list[dict]:
    import yaml
    from pathlib import Path
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MatrixError([f"cannot read {path}: {exc}"]) from exc
    return parse_matrix(data)


def awaiting_signoff(row: dict) -> bool:
    return row["disposition"] == "dropped" and row.get("signoff") is None


def blocks(row: dict, site: str) -> bool:
    """Does this row hold up cutover for `site`?"""
    if awaiting_signoff(row):
        return True
    e = row["sites"][site]
    return row["disposition"] in GATED and e["need"] == "required" and e["status"] != "done"


def matrix_report(rows: list[dict], site: str | None = None) -> dict:
    """Rows grouped by status per site, what blocks, and the next row to work on.

    `next` is the first blocking row in matrix order (any site when `site` is
    None), so working down it follows the order the matrix was written in.
    """
    sites = [site] if site else list(SITES)
    out = {"sites": {}, "awaiting_signoff": [r["id"] for r in rows if awaiting_signoff(r)]}
    nxt = None
    for r in rows:
        for s in sites:
            if nxt is None and blocks(r, s):
                nxt = {"id": r["id"], "site": s, "status": r["sites"][s]["status"],
                       "disposition": r["disposition"], "awaiting_signoff": awaiting_signoff(r)}
    for s in sites:
        by_status = {st: [] for st in STATUSES}
        for r in rows:
            e = r["sites"][s]
            by_status[e["status"]].append({"id": r["id"], "need": e["need"], "disposition": r["disposition"],
                                           "blocking": blocks(r, s)})
        gated = [r for r in rows if r["disposition"] in GATED and r["sites"][s]["need"] == "required"]
        out["sites"][s] = {"by_status": by_status,
                           "required_done": sum(r["sites"][s]["status"] == "done" for r in gated),
                           "required": len(gated),
                           "blocking": [r["id"] for r in rows if blocks(r, s)]}
    out["green"] = not any(v["blocking"] for v in out["sites"].values())
    out["next"] = nxt
    return out


def matrix_text(rep: dict) -> str:
    lines = []
    for s, v in rep["sites"].items():
        verdict = "GREEN" if not v["blocking"] else f"BLOCKED by {len(v['blocking'])}"
        lines.append(f"{s}: {v['required_done']}/{v['required']} required rows done; {verdict}")
        for st in reversed(STATUSES):
            rows = v["by_status"][st]
            lines.append(f"  {st} ({len(rows)})")
            lines += [f"    {'*' if r['blocking'] else ' '} {r['id']}  [{r['disposition']}, {r['need']}]" for r in rows]
    for rid in rep["awaiting_signoff"]:
        lines.append(f"awaiting sign-off (dropped, blocks every site): {rid}")
    n = rep["next"]
    lines.append(f"next: {n['id']} ({n['site']}, {'awaiting sign-off' if n['awaiting_signoff'] else n['status']})"
                 if n else "next: nothing blocks")
    lines.append("* = blocks cutover (static or dynamic-api, required, not done; or dropped awaiting sign-off)")
    return "\n".join(lines)
