"""Export a folder of PDFs as a roomkit manifest.

The one exporter roomkit ships that needs no particular website: a directory of
PDFs and a `documents.json` beside them that says what each one is. It writes a
manifest (roomkit/manifest.py) on stdout for `roomkit build`.

READ-ONLY and offline: it reads files and runs pdftotext and pdfinfo (poppler),
nothing else.

    python -m roomkit.exporters.folder DIR > MANIFEST.json
    python -m roomkit.cli build --manifest MANIFEST.json --out ROOM --site-pack roomkit/packs/default

DIR/documents.json:

    {
      "site": {
        "name": "records.example.org",           the site's name
        "title": "Reading Room",                 the room's title
        "base_url": "https://records.example.org",   https://, no trailing slash
        "room_path": "/documents/",              where the room is served (default /documents/)
        "files_path": "/files/",                 where the site serves the PDFs themselves
                                                 (default /files/); the room links there,
                                                 percent-encoded, and never copies a PDF
        "template": "example",                   optional: the pack the build uses by default
        "lede": "..."                            optional: the index page's opening line
      },
      "documents": [{
        "file": "minutes-2024-03.pdf",           a PDF in DIR (a path under it); required
        "title": "Council minutes, March 2024",  required
        "sha256": "<64 hex>",                    the PDF's hash; required, and checked
        "date": "2024-03-12",                    optional, shown as written; a leading
                                                 four-digit year becomes the Year filter
        "group": "Council",                      optional: the index groups by it
        "source_url": "https://...",             optional: where the copy came from
        "summary": "..."                         optional
      }]
    }

What it refuses (exit 1, nothing on stdout):
  - a row with no title, file or sha256, or a file outside DIR;
  - a PDF whose bytes do not hash to its sha256;
  - a PDF whose pdftotext page count differs from pdfinfo's;
  - two rows that make the same slug (the slug is the file name, kebab-cased).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote

HEX64 = re.compile(r"^[0-9a-f]{64}$")
YEAR = re.compile(r"^(\d{4})")
URL = re.compile(r"^https://\S+$")


class ExportError(Exception):
    pass


def slug_of(rel: str) -> str:
    stem = re.sub(r"\.pdf$", "", rel, flags=re.IGNORECASE)
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_pages(path: str) -> list[str]:
    """Each page's text, by pdftotext; refused if the count is not pdfinfo's."""
    info = subprocess.run(["pdfinfo", path], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
    if not m:
        raise ExportError(f"{path}: pdfinfo states no page count")
    text = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True,
                          check=True, text=True).stdout
    pages = text.split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    if len(pages) != int(m.group(1)):
        raise ExportError(f"{path}: pdftotext gave {len(pages)} pages, pdfinfo says {m.group(1)}")
    return pages


def _url_path(path: str) -> str:
    return "/" + path.strip("/") + "/"


def document(row: dict, root: str, site: dict, extract=pdf_pages) -> dict:
    if not isinstance(row, dict):
        raise ExportError(f"a documents row is not an object: {row!r}")
    rel, title, sha = row.get("file"), row.get("title"), str(row.get("sha256") or "").lower()
    if not (isinstance(rel, str) and rel and isinstance(title, str) and title.strip() and sha):
        raise ExportError(f"{rel or '(no file)'}: a row needs file, title and sha256")
    if not HEX64.match(sha):
        raise ExportError(f"{rel}: sha256 is not 64 hex characters")
    disk = os.path.realpath(os.path.join(root, rel))
    if not disk.startswith(os.path.realpath(root) + os.sep):
        raise ExportError(f"{rel}: not a file under the folder")
    if sha256_file(disk) != sha:
        raise ExportError(f"{rel}: bytes do not hash to documents.json's sha256")
    url = site["files_path"] + quote("/".join(p for p in rel.split(os.sep) if p))
    date = str(row.get("date") or "")
    group = str(row.get("group") or "")
    source = row.get("source_url")
    if source is not None and not (isinstance(source, str) and URL.match(source)):
        raise ExportError(f"{rel}: source_url is not an https:// URL")
    room_url = f"{site['base_url']}{site['room_path']}"
    parts = [f"{title.rstrip('.')}.", f"{site['title']}, {site['base_url']}{url}."]
    if date:
        parts.append(f"{date}.")
    if source:
        parts.append(f"Source: {source}.")
    details = []
    if date:
        details.append({"label": "Date", "value": date})
    if group:
        details.append({"label": "Group", "value": group})
    if source:
        details.append({"label": "Source", "value": source, "url": source})
    details.append({"label": "SHA-256", "value": sha, "code": True})
    facets = {}
    year = YEAR.match(date)
    if year:
        facets["year"] = year.group(1)
    doc = {
        "slug": slug_of(rel), "title": title, "visibility": "public", "citation": " ".join(parts),
        **({"date": date} if date else {}),
        **({"summary": row["summary"]} if isinstance(row.get("summary"), str) and row["summary"] else {}),
        "file": {"url": url, "download_url": url, "sha256": sha, "bytes": os.path.getsize(disk),
                 "ext": "pdf", "mime": "application/pdf"},
        "pages": [{"n": i, "text": t, "provenance": "pdf"} for i, t in enumerate(extract(disk), 1)],
        "display": {"breadcrumbs": [{"label": site["title"], "url": room_url}, {"label": title}],
                    "details": details},
        "index": {"group": group, "card_date": date, "meta": [m for m in (group, date) if m], "facets": facets},
    }
    return doc


def _site(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ExportError("documents.json has no 'site' object")
    site = {k: raw.get(k) for k in ("name", "title", "base_url")}
    if not all(isinstance(v, str) and v for v in site.values()):
        raise ExportError("site needs name, title and base_url")
    site["room_path"] = _url_path(str(raw.get("room_path") or "/documents/"))
    site["files_path"] = _url_path(str(raw.get("files_path") or "/files/"))
    for k in ("template", "lede"):
        if isinstance(raw.get(k), str) and raw[k]:
            site[k] = raw[k]
    return site


def export(root: str, extract=pdf_pages) -> dict:
    src = os.path.join(root, "documents.json")
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise ExportError("documents.json has no 'documents' list")
    site = _site(data.get("site"))
    docs = [document(r, root, site, extract) for r in data["documents"]]
    slugs = [d["slug"] for d in docs]
    dupes = sorted({s for s in slugs if slugs.count(s) > 1})
    if dupes:
        raise ExportError(f"two PDFs make the same slug: {', '.join(dupes)}")
    groups = list(dict.fromkeys(d["index"]["group"] for d in docs if d["index"]["group"]))
    index = {"title": site["title"], "groups": groups, "group_label": "Group"}
    if site.get("lede"):
        index["lede"] = site["lede"]
    if any(d["index"]["facets"] for d in docs):
        index["facets"] = [{"name": "year", "label": "Year"}]
    out_site = {"name": site["name"], "title": site["title"], "base_url": site["base_url"],
                "room_path": site["room_path"], "index": index}
    if site.get("template"):
        out_site["template"] = site["template"]
    return {"source": {"exporter": "folder", "documents_json_sha256": sha256_file(src)},
            "site": out_site, "documents": docs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m roomkit.exporters.folder",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="the folder holding the PDFs and documents.json")
    args = ap.parse_args(argv)
    try:
        out = export(os.path.expanduser(args.folder))
    except (ExportError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"folder export refused: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
