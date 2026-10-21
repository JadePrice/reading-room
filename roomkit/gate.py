"""roomkit gate: the checks a built room passes before anything uploads it.

    gate --out DIR [--max-bytes N] [--json]

Reads a built tree (the room.lock.json beside its pages gives the mount) and
writes nothing. Two checks, from hrtarchive's staged-deploy gates:

**Links.** Every href, src, poster, data and action in every .html page that
points into the room's mount must land on a file in the tree: a path ending in
`/` or naming a directory resolves to its index.html, as Apache serves it. A
query or fragment is ignored. Not checked, because the tree cannot answer them:
other schemes (https:, mailto:, data:), paths outside the mount (the site's own
WordPress pages and PDFs, which entity and document pages link on purpose), and
fragments.

**Size.** No file in the tree is larger than `--max-bytes` (default 25 MiB, the
Cloudflare Pages per-file limit that a move off Hostinger would hit). The
room's PDFs are not in the tree, so this guards the pages, thumbnails and
search index only.

Exit 1 when either check fails, 2 when DIR is not a built room.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_BYTES = 25 * 1024 * 1024
LINK_ATTRS = ("href", "src", "poster", "data", "action")


class GateError(ValueError):
    pass


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        for k, v in attrs:
            if k in LINK_ATTRS and v:
                self.found.append(v)


def _target(root: Path, mount: str, link: str) -> Path | None:
    """The file a link into the mount should land on, or None if it is not one."""
    parts = urlsplit(link)
    if parts.scheme or parts.netloc or not parts.path.startswith(mount):
        return None
    rel = unquote(parts.path[len(mount):])
    cand = root / rel
    return cand / "index.html" if (not rel or rel.endswith("/") or cand.is_dir()) else cand


def broken_links(root: Path, mount: str) -> tuple[list[dict], int, int]:
    """(broken, links into the mount, pages read)."""
    broken: list[dict] = []
    checked = pages = 0
    resolved_root = root.resolve()
    for page in sorted(root.rglob("*.html")):
        pages += 1
        p = _Links()
        p.feed(page.read_text(encoding="utf-8", errors="replace"))
        for link in p.found:
            tgt = _target(root, mount, link)
            if tgt is None:
                continue
            checked += 1
            try:
                ok = tgt.resolve().is_file() and resolved_root in tgt.resolve().parents
            except OSError:
                ok = False
            if not ok:
                broken.append({"page": str(page.relative_to(root)), "link": link})
    return broken, checked, pages


def oversize(root: Path, max_bytes: int) -> list[dict]:
    return [{"file": str(f.relative_to(root)), "bytes": f.stat().st_size}
            for f in sorted(root.rglob("*")) if f.is_file() and f.stat().st_size > max_bytes]


def run(root: Path, max_bytes: int = MAX_BYTES) -> dict:
    lock = root / "room.lock.json"
    if not lock.is_file():
        raise GateError(f"{root} has no room.lock.json: not a built room")
    mount = json.loads(lock.read_text(encoding="utf-8")).get("mount")
    if not (isinstance(mount, str) and mount.startswith("/") and mount.endswith("/")):
        raise GateError("room.lock.json has no usable mount")
    broken, checked, pages = broken_links(root, mount)
    big = oversize(root, max_bytes)
    return {"ok": not broken and not big, "mount": mount, "pages": pages, "links": checked,
            "broken": broken, "oversize": big, "max_bytes": max_bytes}


def text(res: dict) -> str:
    n = len(res["broken"])
    head = (f"{n} of {res['links']} links in {res['pages']} pages do not resolve under {res['mount']}" if n
            else f"{res['links']} links in {res['pages']} pages resolve under {res['mount']}")
    lines = [f"{'PASSES' if res['ok'] else 'FAILS'}: {head}"]
    lines += [f"   broken: {b['page']} -> {b['link']}" for b in res["broken"][:20]]
    if n > 20:
        lines.append(f"   ... and {n - 20} more")
    lines += [f"   over {res['max_bytes']} bytes: {o['file']} ({o['bytes']})" for o in res["oversize"]]
    return "\n".join(lines)
