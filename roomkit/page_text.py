"""Page text as HTML and as a download (pack features.page-text).

The document's text sits only in `<slug>/pages.<hash>.json`, drawn from the scan, so a visitor's
browser translator, screen reader, reader mode, zoom and copy cannot reach it. With the switch on,
each record that has page texts also gets

    <slug>/text/index.html    the text as HTML: one section per page, `#p<n>`, no JavaScript
    <slug>/<slug>.txt         the same text as a UTF-8 file with `Page n` headers

and its record page links both. Every one of them says the text was read by a machine and may have
errors; the record is the document file (LABEL, exactly).

Not built for a gated record (display.gate: the text would sit in the open beside a "Show document"
button) or a web snapshot (its text is the capture's, not read from a scan). A record without page
texts has none.

D1 (search-engine indexing of the text pages) is a pack key, `page_text.index`: true leaves the
pages indexable and in the sitemap; false (the default, and what a pack that says nothing gets)
sends `<meta name="robots" content="noindex">` and leaves them out of the sitemap. The .txt files
are never in the sitemap. Room-wide noindex (a staging mount) wins and says "noindex, nofollow".

Cleaning (hyphenated line ends rejoined) is text_clean.py, the rule read-aloud uses.
"""

from __future__ import annotations

from . import text_clean as TC
from .manifest import Document

FEATURE = "page-text"
# The honest label, word for word. Shown at the top of the text page and in the .txt.
LABEL = "Text read by machine from the scan. It may have errors. The record is the document file."


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def indexed(pack: dict) -> bool:
    """D1: whether the text pages may be indexed (and sit in the sitemap). Default: no."""
    return bool((pack.get("page_text") or {}).get("index"))


def on(doc: Document, pack: dict) -> bool:
    """Whether this record gets a text page and a .txt."""
    return bool(enabled(pack) and doc.pages and not doc.is_snapshot and not doc.display.get("gate"))


def text_path(doc: Document) -> str:
    return f"{doc.slug}/text/"


def txt_path(doc: Document) -> str:
    return f"{doc.slug}/{doc.slug}.txt"


def sections(doc: Document) -> list[dict]:
    """One entry per page of the record, in order: {n, paragraphs: [[line, ...], ...]}. A page the
    OCR read nothing from has no paragraphs; it still has its section, so `#p<n>` always exists."""
    return [{"n": p.n, "paragraphs": TC.paragraphs(p.text)} for p in doc.pages]


def txt(doc: Document, record_url: str) -> str:
    """The .txt: title, label, the record's URL, then each page under a `Page n` header."""
    out = [doc.title, LABEL, record_url]
    for s in sections(doc):
        out += ["", f"Page {s['n']}", ""]
        if s["paragraphs"]:
            out.append("\n\n".join("\n".join(p) for p in s["paragraphs"]))
        else:
            out.append("(No text was read from this page.)")
    return "\n".join(out) + "\n"
