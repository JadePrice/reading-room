"""Join an exporter's ROOMKIT_SLICE pieces into one manifest.

    python scripts/roomkit/exporters/merge-slices.py OUT.json SLICE.json [SLICE.json ...]

Each piece carries `slice` {offset, limit, total}. The pieces must share the
same site block and total, and their windows must cover 0..total with no gap
and no overlap; anything else is refused (exit 1) and nothing is written. The
merged manifest is what one unsliced export would have printed: documents and
excluded in record order, no `slice` key. Every other key comes from the first
piece (offset 0), which is the one that carries GG's `entities` block.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


class SliceError(ValueError):
    pass


def merge(pieces: list[dict]) -> dict:
    if not pieces:
        raise SliceError("no pieces")
    for i, p in enumerate(pieces):
        if "error" in p:
            raise SliceError(f"piece {i} is an exporter error: {p['error']}")
        if not isinstance(p.get("slice"), dict):
            raise SliceError(f"piece {i} has no slice (exported without ROOMKIT_SLICE?)")
    pieces = sorted(pieces, key=lambda p: p["slice"]["offset"])
    first = pieces[0]
    total = first["slice"]["total"]
    at = 0
    for p in pieces:
        s = p["slice"]
        if p["site"] != first["site"] or s["total"] != total:
            raise SliceError(f"slice at {s['offset']} is from a different export (site or total differs)")
        if s["offset"] != at:
            raise SliceError(f"{'gap' if s['offset'] > at else 'overlap'} at record {at}: next slice starts at {s['offset']}")
        held = len(p["documents"]) + len(p.get("excluded", []))
        want = min(s["limit"], total - s["offset"])
        if held != want:
            raise SliceError(f"slice at {s['offset']} holds {held} records, its window holds {want}")
        at += want
    if at != total:
        raise SliceError(f"slices end at record {at} of {total}")
    out = {k: v for k, v in first.items() if k not in ("documents", "excluded", "slice")}
    out["documents"] = [d for p in pieces for d in p["documents"]]
    out["excluded"] = [e for p in pieces for e in p.get("excluded", [])]
    slugs = [d["slug"] for d in out["documents"]]
    if len(slugs) != len(set(slugs)):
        raise SliceError("a slug appears in more than one slice (the site changed between pieces?)")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        merged = merge([json.loads(Path(a).read_text(encoding="utf-8")) for a in argv[2:]])
    except (SliceError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    Path(argv[1]).write_text(json.dumps(merged, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(merged['documents'])} documents, {len(merged['excluded'])} excluded -> {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
