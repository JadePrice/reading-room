"""parity.thumbnails: does every card show the thumbnail it shows live?

Matrix row `index-thumbnails`. As for the other parity checks, the live side is
an input file, never fetched here: `exporters/deflockdane-fetch-thumbs.sh`
reads dd's live index through the origin and fetches each card's <img>:

    #fetched\t<ISO time>
    <slug>\t<img src or ->\t<http code or ->\t<content type or ->\t<sha256 or ->

The room side is the built room's index.html: each card's thumbnail and the
file it names in the room, hashed from disk.

Per card:
  same          live serves an image (200, image/*) and the room's copy has its bytes
  differs       both show one, the bytes differ
  missing       live shows one, the room's card has none
  not-copied    the room's card points off the room (the live route), so the
                card stops working when the live route goes (cutover)
  live-broken   live's card has an <img> that does not load (a 404); the room
                shows none. The row's explained difference, not a miss
  extra         the room shows a thumbnail where live shows none or a broken one
and a card on one side only is `missing-card` / `extra-card`.

`ok` when every card is `same`, `live-broken` or shows none on both sides.
"""

from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path


class ThumbParityError(ValueError):
    """The live file or the room cannot be read as this check needs."""


def read_live(path: Path) -> dict:
    """{"fetched": ..., "cards": {slug: {"src", "code", "type", "sha256"}}} from the fetch script's TSV."""
    fetched, cards = "", {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        cols = line.split("\t")
        if cols[0] == "#fetched" and len(cols) == 2:
            fetched = cols[1]
            continue
        if len(cols) != 5 or not cols[0]:
            raise ThumbParityError(f"{path}:{n}: not slug, src, code, type, sha256 (exporters/*-fetch-thumbs.sh)")
        if cols[0] in cards:
            raise ThumbParityError(f"{path}:{n}: {cols[0]} twice")
        cards[cols[0]] = dict(zip(("src", "code", "type", "sha256"), (c if c != "-" else "" for c in cols[1:])))
    if not cards:
        raise ThumbParityError(f"{path}: no cards")
    return {"fetched": fetched, "cards": cards}


class _Cards(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: dict[str, str] = {}
        self._img = self._title = False
        self._src = ""

    def handle_starttag(self, tag, attrs):
        a, cls = dict(attrs), (dict(attrs).get("class") or "").split()
        if tag == "li" and "room__card" in cls:
            self._src = ""
        elif tag == "a" and "room__thumb" in cls:
            self._img = True
        elif tag == "img" and self._img:
            self._src = a.get("src") or ""
        elif tag == "h3" and "room__card-title" in cls:
            self._title = True
        elif tag == "a" and self._title:
            self.cards[(a.get("href") or "").rstrip("/").rsplit("/", 1)[-1]] = self._src

    def handle_endtag(self, tag):
        if tag == "a":
            self._img = False
        elif tag == "h3":
            self._title = False


def room_cards(room: Path) -> dict:
    """{slug: {"src", "sha256"}} for every card on the built index; sha256 only for a file in the room."""
    lock = room / "room.lock.json"
    if not lock.is_file():
        raise ThumbParityError(f"{room}: no room.lock.json (not a built room)")
    at = json.loads(lock.read_text())["mount"]
    p = _Cards()
    p.feed((room / "index.html").read_text(encoding="utf-8"))
    out = {}
    for slug, src in p.cards.items():
        f = room / src[len(at):] if src.startswith(at) else None
        out[slug] = {"src": src, "sha256": hashlib.sha256(f.read_bytes()).hexdigest() if f and f.is_file() else ""}
    return out


def compare(live: dict, room: dict) -> dict:
    rows = []
    for slug in sorted(set(live["cards"]) | set(room)):
        lv, rm = live["cards"].get(slug), room.get(slug)
        if lv is None or rm is None:
            rows.append({"slug": slug, "result": "extra-card" if lv is None else "missing-card"})
            continue
        shown = lv["code"] == "200" and lv["type"].startswith("image/")
        if not rm["src"]:
            result = "missing" if shown else ("live-broken" if lv["src"] else "none")
        elif not rm["sha256"]:
            result = "not-copied"
        elif not shown:
            result = "extra"
        else:
            result = "same" if rm["sha256"] == lv["sha256"] else "differs"
        rows.append({"slug": slug, "result": result})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    bad = [r for r in rows if r["result"] not in ("same", "live-broken", "none")]
    return {"check": "thumbnails", "fetched": live["fetched"], "cards": len(rows), "counts": counts,
            "differences": bad, "live_broken": [r["slug"] for r in rows if r["result"] == "live-broken"],
            "ok": not bad}


def run(live_path: Path, room: Path) -> dict:
    return compare(read_live(live_path), room_cards(room))


def text(rep: dict) -> str:
    head = (f"parity.thumbnails {'OK' if rep['ok'] else 'DIFFERENT'}: {rep['cards']} cards, "
            + ", ".join(f"{k} {v}" for k, v in sorted(rep["counts"].items())) + f" (live read {rep['fetched']})")
    body = [f"   {d['result']} {d['slug']}" for d in rep["differences"]]
    body += [f"   live-broken {s} (live's <img> does not load; the room shows none)" for s in rep["live_broken"]]
    return "\n".join([head, *body])
