"""The room's core, copied into another codebase, and how far that copy has drifted.

Civica renders the same reading room (plan 2026-10-13-unified-reading-room-
frontend, Milestone 6). LLM_WIKI stays canonical; Civica carries a verbatim
copy of the core, pinned to a commit:

    roomkit vendor write --to /srv/projects/civica/app/room
    roomkit vendor check --to /srv/projects/civica/app/room [--json]

`write` copies CORE and records VENDORED.json: the source commit and the sha256
of every file. It refuses while a core file has uncommitted changes, because the
pin would then name a commit that does not hold what was copied.

`check` changes nothing. It reports:
  modified  a file in the copy no longer matches VENDORED.json (edited in place;
            fix it upstream and vendor again, never in the copy)
  missing   a file VENDORED.json lists is gone from the copy
  behind    the source has moved on since the pin (vendor again to take it)
Exit 1 if any is non-empty.

The core is the part with no roomkit-only dependencies: the manifest, the view
model, the template and its environment, CSS, color and site-pack checks. It
imports itself relatively, so the copy works as any package.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
PIN = "VENDORED.json"
CORE_MODULES = ("__init__.py", "manifest.py", "entities.py", "passages.py", "view.py", "room.py", "css.py", "color.py", "pack.py",
                "search.py")
CORE_TREES = ("templates/room",)
CORE_FILES = ("packs/pack.schema.json",)


class VendorError(ValueError):
    pass


def core(src: Path = ROOT) -> dict[str, bytes]:
    """The core's files, by path relative to the package."""
    rels = list(CORE_MODULES) + list(CORE_FILES)
    for tree in CORE_TREES:
        rels += [str(p.relative_to(src)) for p in sorted((src / tree).rglob("*")) if p.is_file()
                 and "__pycache__" not in p.parts]
    return {rel: (src / rel).read_bytes() for rel in sorted(rels)}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def source_commit(src: Path = ROOT) -> str:
    """HEAD, refusing if a core file differs from it (the pin would be false)."""
    paths = [str((src / rel).relative_to(REPO)) for rel in core(src)]
    dirty = _git("status", "--porcelain", "--", *paths)
    if dirty:
        raise VendorError("core files have uncommitted changes; commit them first:\n" + dirty)
    return _git("rev-parse", "HEAD")


def write(dest: Path, commit: str, src: Path = ROOT) -> dict:
    """Copy the core into `dest` and pin it. Files of `dest` outside the core are left alone."""
    files = core(src)
    for rel, data in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    pin = {"source": "LLM_WIKI scripts/roomkit", "commit": commit,
           "files": {rel: _sha(data) for rel, data in files.items()}}
    (dest / PIN).write_text(json.dumps(pin, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return pin


def check(dest: Path, src: Path = ROOT) -> dict:
    """How the copy in `dest` stands against its pin and against the source."""
    try:
        pin = json.loads((dest / PIN).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VendorError(f"no readable {PIN} in {dest}: {exc}") from exc
    pinned, now = pin["files"], {rel: _sha(b) for rel, b in core(src).items()}
    missing = sorted(rel for rel in pinned if not (dest / rel).is_file())
    modified = sorted(rel for rel in pinned if rel not in missing and _sha((dest / rel).read_bytes()) != pinned[rel])
    behind = sorted(rel for rel in set(pinned) | set(now) if pinned.get(rel) != now.get(rel))
    return {"commit": pin["commit"], "modified": modified, "missing": missing, "behind": behind,
            "current": not (modified or missing or behind)}
