"""Corpus search: a Pagefind index over every record, built with the room.

Turned on by a pack's `features.corpus-search` (off unless the pack says so).
The index answers the finder's text search and its suggestions in the browser;
nothing is fetched from a server at page view, and every file it needs ships in
the room under `pagefind/`.

    records(m, at)     what is indexed, per record: title, summary, citation,
                       agency, group (agency/collection), the public notes the
                       record page shows (display.notes; site B's live search reads
                       them too), facets, date, and the
                       page texts from pages.json,
                       or, for a record with no pages, its search_text
    record_html(rec)   that record as the HTML Pagefind reads. Pure, so the
                       goldens pin exactly what Pagefind is given
    pagefind(pages)    runs the pinned Pagefind binary over those pages and
                       returns the files the room ships

Page anchors. A hit inside a page's text links to `<record>/#page-N` when the
reader can open that page (PDF: rr-reader-pdf.js reads `#page-N`); other
records link to the record only, as does a hit in `search_text`, which has
no pages to point at (manifest.py).

Determinism. Pagefind 1.5.2 is NOT byte-reproducible: it writes each filter's
values in a random order, so `filter/*.pf_filter`, `pagefind.*.pf_meta` and
the hashes in their names (and in pagefind-entry.json) change between runs of
the same input; the fragments and index shards are stable. The output is also
only as stable as the binary, so the version is pinned (PAGEFIND_VERSION, and
requirements-dev.txt) and a different binary is refused, not used. So nothing
pins Pagefind's bytes: room.lock.json records `search.input`, a hash of every
indexed field (what `pages` hands Pagefind), and `check` calls the index
current when that and the version match and the shipped files are the ones the
lock lists (build.compare). The goldens run a stand-in indexer that writes the
HTML Pagefind would have read (tests/roomkit/test_golden.py), as they do for
the reader engine.

Masked. Social Security numbers (###-##-####) are taken out of every text
before it is indexed. The index ships each record's whole text as data anyone
can download, and the FBI files' search_text carries the SSNs of the people
they watched (2026-10-14: 36 in 16 records; page text had none). Nobody
searches by one, the search text is never shown, and the PDFs are untouched.

Refusals: a pack that turns the feature on without the pinned Pagefind
installed fails the build with the install command. Nothing falls back to a
build without search.
"""

from __future__ import annotations

import gzip
import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from html import escape
from pathlib import Path

from .manifest import PDF, Manifest

FEATURE = "corpus-search"
PAGEFIND_VERSION = "1.5.2"
INSTALL = f"uv pip install 'pagefind[bin]=={PAGEFIND_VERSION}' (requirements-dev.txt)"
OUT = "pagefind"
URLS = "result-urls.json"  # {Pagefind result id: record URL}, written by pagefind() (result_urls)
# Pagefind's own UI bundles are not used (the room draws its own finder), so
# they are not shipped. Everything else Pagefind writes is.
UNUSED = ("pagefind-ui.js", "pagefind-ui.css", "pagefind-modular-ui.js", "pagefind-modular-ui.css",
          "pagefind-component-ui.js", "pagefind-component-ui.css", "pagefind-highlight.js")

Indexer = Callable[[dict[str, str]], dict[str, bytes]]
SSN = re.compile(r"\b(?!(?:000|666))\d{3}(?:\s*-\s*|\s+)(?!(?:00))\d{2}(?:\s*-\s*|\s+)(?!(?:0000))\d{4}\b")
REDACTED_SSN = "[REDACTED-SSN]"

# Parametric Zone Weights (Stanford IR Ch. 6: Parametric and zone indexes)
# Provides non-uniform term scoring between salient structural zones and body text.
WEIGHT_TITLE: float = 10.0
WEIGHT_SUMMARY: float = 5.0
WEIGHT_CITATION: float = 4.0
WEIGHT_NOTES: float = 3.0
WEIGHT_AGENCY: float = 2.0
WEIGHT_GROUP: float = 2.0
WEIGHT_BODY: float = 1.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "title": WEIGHT_TITLE,
    "summary": WEIGHT_SUMMARY,
    "citation": WEIGHT_CITATION,
    "notes": WEIGHT_NOTES,
    "agency": WEIGHT_AGENCY,
    "group": WEIGHT_GROUP,
    "body": WEIGHT_BODY,
    "text": WEIGHT_BODY,
}

# Civic domain thesaurus for query expansion (Stanford IR Ch. 9)
# Defined directly to preserve vendor self-containment (tests/roomkit/test_vendor.py).
CIVIC_ACRONYM_SYNONYMS: dict[str, list[str]] = {
    "alpr": [
        "automated license plate reader",
        "automated license plate recognition",
        "flock",
        "flock safety",
        "falcon",
        "license plate surveillance",
    ],
    "bwc": [
        "body worn camera",
        "body camera",
        "axon",
        "in-car camera",
        "fleet video",
    ],
    "foia": [
        "freedom of information act",
        "open records",
        "public records",
    ],
    "pfas": [
        "per- and polyfluoroalkyl substances",
        "forever chemicals",
        "afff",
        "pfoa",
        "pfos",
    ],
    "mou": [
        "memorandum of understanding",
        "intergovernmental agreement",
        "iga",
        "cooperative agreement",
    ],
    "nda": [
        "non-disclosure agreement",
        "confidentiality agreement",
    ],
    "dcf": [
        "department of children and families",
    ],
    "mpd": [
        "metropolitan police department",
    ],
    "rtcc": [
        "real time crime center",
        "real time information center",
        "rtic",
    ],
}

_WORD_SPLIT = re.compile(r"[\s,.-/]+")


def expand_civic_query(query: str, thesaurus: dict[str, list[str]] | None = None) -> list[str]:
    """Expand civic acronyms in a search query with their domain synonyms (Stanford IR Ch. 9)."""
    if not query:
        return []
    lexicon = thesaurus or CIVIC_ACRONYM_SYNONYMS
    tokens = [t.lower().strip("'\"") for t in _WORD_SPLIT.split(query) if t.strip("'\"")]
    expansions: list[str] = []
    for token in tokens:
        if token in lexicon:
            expansions.extend(lexicon[token])
    return sorted(dict.fromkeys(expansions))




class SearchError(ValueError):
    """The index cannot be built as asked."""


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def mask_sensitive(text: str, replacement: str = "") -> str:
    """Mask Social Security numbers and sensitive patterns in archival text."""
    if not text:
        return text
    return SSN.sub(replacement, text)


def _masked(text: str) -> str:
    return mask_sensitive(text, "")


def records(m: Manifest, at: str) -> list[dict]:
    """What the index holds, one dict per record, in manifest order."""
    out = []
    multi = [f["name"] for f in m.site.index.get("facets", []) if f.get("multi")]
    for d in m.documents:
        anchors = d.ext in PDF
        out.append({
            "slug": d.slug, "url": f"{at}{d.slug}/", "title": d.title,
            "summary": _masked(d.summary),
            "citation": _masked(d.citation),
            "agency": _masked(d.agency),
            "date": d.date,
            "group": _masked(d.index.get("group", "")),
            "notes": _masked(d.display.get("notes", "")),
            "facets": dict(sorted(d.index.get("facets", {}).items())),
            # A multi-valued facet (vendor): one filter value each, as room-search.js asks for it.
            "multi": {n: list(d.index.get("browse", {}).get(n, [])) for n in multi},
            "pages": [{"n": p.n, "anchor": f"page-{p.n}" if anchors else "", "text": _masked(p.text)}
                      for p in d.pages],
            "text": _masked(d.search_text),
        })
    return out


def _e(s: str) -> str:
    return escape(s, quote=True)


def record_html(rec: dict, *, weights: dict[str, float] | None = None) -> str:
    """One record as the page Pagefind indexes (never served).

    Searchable: title, summary, citation, agency, group, notes, each page's text and
    the record's search_text (no heading, so a hit there reports the record).
    Filters (group and every facet) and the date sort sit in an ignored block,
    so they narrow and order results without adding words.

    If `weights` is provided (e.g. `DEFAULT_WEIGHTS`), elements are tagged with
    Pagefind's `data-pagefind-weight` attribute for parametric zone weighting
    (Stanford IR Ch. 6: scoring title/summary higher than OCR body text).
    """
    def _w(key: str) -> str:
        if weights and key in weights:
            return f' data-pagefind-weight="{weights[key]}"'
        return ""

    body = [f"<h1{_w('title')}>{_e(rec['title'])}</h1>"]
    body += [f"<p{_w(k)}>{_e(rec[k])}</p>" for k in ("summary", "citation", "agency", "group", "notes", "text")
             if rec.get(k)]
    meta = [f'<span data-pagefind-meta="title">{_e(rec["title"])}</span>']
    if rec["group"]:
        meta.append(f'<span data-pagefind-filter="group">{_e(rec["group"])}</span>')
    meta += [f'<span data-pagefind-filter="{_e(k)}">{_e(v)}</span>' for k, v in rec["facets"].items() if v]
    meta += [f'<span data-pagefind-filter="{_e(k)}">{_e(v)}</span>'
             for k, vs in rec.get("multi", {}).items() for v in vs if v]
    if rec["date"]:
        meta.append(f'<span data-pagefind-sort="date">{_e(rec["date"])}</span>')
    for p in rec["pages"]:
        # A heading with an id is what makes Pagefind report the hit at that anchor.
        h = f'<h2 id="{p["anchor"]}">' if p["anchor"] else "<h2>"
        body.append(f"{h}Page {p['n']}</h2><p{_w('body')}>{_e(p['text'])}</p>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body>'
            f'<main data-pagefind-body>{"".join(body)}'
            f'<div data-pagefind-ignore>{"".join(meta)}</div></main></body></html>\n')


def pages(m: Manifest, at: str, *, weights: dict[str, float] | None = None) -> dict[str, str]:
    """Pagefind's input: `<slug>/index.html` -> record_html, which Pagefind turns
    into the URL `/<slug>/` (the browser adds the mount as baseUrl)."""
    return {f"{r['slug']}/index.html": record_html(r, weights=weights) for r in records(m, at)}



def _executable() -> Path:
    try:
        from pagefind_bin import get_executable
        return Path(get_executable())
    except (ImportError, FileNotFoundError) as exc:
        raise SearchError(f"features.{FEATURE} is on but Pagefind is not installed ({exc}); {INSTALL}") from exc


def binary() -> Path:
    """The pinned Pagefind binary (pip `pagefind[bin]`), or a SearchError saying how to get it."""
    exe = _executable()
    got = subprocess.run([str(exe), "--version"], capture_output=True, text=True, check=False).stdout.split()
    if got[-1:] != [PAGEFIND_VERSION]:
        raise SearchError(f"Pagefind {' '.join(got[1:]) or '?'} found, roomkit pins {PAGEFIND_VERSION}; {INSTALL}")
    return exe


def pagefind(site_pages: dict[str, str]) -> dict[str, bytes]:
    """Run the pinned Pagefind over `site_pages`; the files to ship, keyed `pagefind/...`."""
    exe = binary()
    with tempfile.TemporaryDirectory(prefix="roomkit-pagefind-") as tmp:
        site, out = Path(tmp) / "site", Path(tmp) / "out"
        for rel, html in site_pages.items():
            p = site / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")
        r = subprocess.run([str(exe), "--site", str(site), "--output-path", str(out), "--force-language", "en"],
                           capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise SearchError(f"pagefind failed ({r.returncode}): {(r.stderr or r.stdout).strip()[-400:]}")
        files = {f"{OUT}/{p.relative_to(out).as_posix()}": p.read_bytes()
                 for p in sorted(out.rglob("*")) if p.is_file() and p.name not in UNUSED}
    files[f"{OUT}/{URLS}"] = result_urls(files)
    return files


def result_urls(files: dict[str, bytes]) -> bytes:
    """{result id: record URL} from Pagefind's fragments (fragment/<id>.pf_fragment, gzip of
    "pagefind_dcd" + JSON with the page's url). room-search.js reads it to sort a text search's
    hits the way the site's list sorts (index-facets) without loading every hit's fragment."""
    urls = {}
    for path, data in files.items():
        name = path.rsplit("/", 1)[-1]
        if "/fragment/" not in path or not name.endswith(".pf_fragment"):
            continue
        raw = gzip.decompress(data)
        if not raw.startswith(b"pagefind_dcd"):
            raise SearchError(f"{path}: not a Pagefind fragment this roomkit reads (Pagefind {PAGEFIND_VERSION})")
        urls[name[: -len(".pf_fragment")]] = json.loads(raw[len(b"pagefind_dcd"):])["url"]
    if not urls:
        raise SearchError("Pagefind wrote no fragments")
    return (json.dumps(urls, sort_keys=True, separators=(",", ":")) + "\n").encode()


def stand_in(site_pages: dict[str, str]) -> dict[str, bytes]:
    """An indexer that writes what Pagefind would read, for tests and goldens:
    the pinned output is the indexed fields, not Pagefind's bytes."""
    return {f"{OUT}/input.json": (json.dumps(site_pages, ensure_ascii=False, sort_keys=True, indent=0) + "\n").encode()}


def index_files(m: Manifest, at: str, indexer: Indexer | None = None) -> dict[str, bytes]:
    files = (indexer or pagefind)(pages(m, at))
    bad = sorted(p for p in files if not p.startswith(OUT + "/"))
    if bad:
        raise SearchError(f"the indexer wrote outside {OUT}/: {bad[:3]}")
    return files
