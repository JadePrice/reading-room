"""Machine text (pack features.machine-text): the site's plain-text record index.

GG serves /library/documents.txt (gg-reading-room templates/txt-ggrr-documents.php):
one line per public record with its title, agency, collection, date, license, a
[third-party] mark, its sha256 and an [IA] mark, for crawlers and command-line
tools. The exporter writes the file with the template's own formula (named there)
and the export's time on its "Generated:" line, so the same manifest builds the
same bytes; the room serves those bytes at the same path. roomkit composes no
word of it.

The manifest block (optional):

    "machine_text": {
      "files": [{"url": "<base_url><room_path>documents.txt", "text": "..."}],
      "source": {"<plugin file>": "<sha256>"}
    }

Refused: a URL that is not one `<name>.txt` directly under the room path, the
same path twice, text that is empty, not text or over MAX_BYTES, and a link into
the room that is not a record the room holds (`](<room><slug>/)`). A site whose
file links a record the export left out is refused, not served with a dead link.

/llms-full.txt is the site root's, outside the room's mount: it stays with WordPress
(parity-matrix.yaml llms-full, user 2026-10-21).
"""

from __future__ import annotations

import re
from dataclasses import replace

from . import entities as E

FEATURE = "machine-text"
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.txt$")
MAX_BYTES = 8 * 1024 * 1024
GENERATED = "Generated: "


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def gate(m, pack: dict):
    """The manifest without its machine text when the pack does not turn it on."""
    if getattr(m, "machine_text", None) and not enabled(pack):
        return replace(m, machine_text=None)
    return m


def parse(raw: object, base_url: str, room_path: str, doc_slugs: set[str]) -> tuple[dict | None, list[str]]:
    """{"files": [{url, text, path}]} and every problem; a block with problems is not returned."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict) or not set(raw) <= {"files", "source"} or not isinstance(raw.get("files"), list):
        return None, ["machine_text is not {files: [...], source?}"]
    src = raw.get("source", {})
    if not (isinstance(src, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in src.items())):
        return None, ["machine_text.source is not {file: sha256}"]
    room = base_url + room_path
    link = re.compile(r"\]\(" + re.escape(room) + r"([^)]*)\)")
    problems: list[str] = []
    out = []
    for f in raw["files"]:
        if not isinstance(f, dict) or not isinstance(f.get("url"), str):
            problems.append("a machine_text file is not {url, text}")
            continue
        url = f["url"]
        path = url[len(room):] if url.startswith(room) else ""
        if not NAME.match(path):
            problems.append(f"machine_text: {url!r} is not a <name>.txt directly under {room}")
            continue
        if path in {o["path"] for o in out}:
            problems.append(f"machine_text: {path} twice")
            continue
        text = f.get("text")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"machine_text {path}: text is empty or not text")
            continue
        if len(text.encode("utf-8")) > MAX_BYTES:
            problems.append(f"machine_text {path}: over {MAX_BYTES} bytes")
            continue
        for rest in link.findall(text):
            slug = rest[:-1] if rest.endswith("/") else ""
            if not (E.SLUG.match(slug) and slug in doc_slugs):
                problems.append(f"machine_text {path}: links {room}{rest}, not a record in this room")
        out.append({"url": url, "path": path, "text": text})
    if problems:
        return None, problems
    return {"files": out}, []


def served(block: dict | None) -> set[str]:
    return {f["path"] for f in block["files"]} if block else set()


def comparable(text: str) -> list[tuple[int, str]]:
    """The file's lines by line number, without its "Generated:" line (the time it was written)."""
    return [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if not ln.startswith(GENERATED)]


def compare(live: str, room: str) -> dict:
    """parity.machine_text: the live file and the room's, line by line, the generated time aside."""
    a, b = comparable(live), comparable(room)
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x[1] != y[1]), None)
    if first is None and len(a) != len(b):
        first = min(len(a), len(b))
    out = {"ok": first is None, "live_lines": len(a), "room_lines": len(b)}
    if first is not None:
        la, lb = (a[first] if first < len(a) else None), (b[first] if first < len(b) else None)
        out["first_difference"] = {"live_line": la[0] if la else None, "live": la[1] if la else None,
                                   "room_line": lb[0] if lb else None, "room": lb[1] if lb else None}
    return out


def text_report(rep: dict, path: str) -> str:
    head = f"{'PASSES' if rep['ok'] else 'FAILS'}: {path} {rep['live_lines']} live lines, {rep['room_lines']} in the room"
    if rep["ok"]:
        return head + " (equal, the generated time aside)"
    d = rep["first_difference"]
    return f"{head}\n   first difference:\n     live line {d['live_line']}: {d['live']!r}\n     room line {d['room_line']}: {d['room']!r}"
