"""parity.search: does the room's corpus search find what the live site finds?

Matrix row `index-fulltext-search`: for a fixed query set, every live hit must
appear in the room's top N. The live side is an input file, never fetched here,
so a site whose search sits behind a rate-limiting edge (dd) can be fed results
fetched through the origin, and GG's can be refetched politely and dated:

    {
      "site": "glassgovernment",                    (one of parity.SITES)
      "fetched": "2026-10-14T19:21:00Z",            when the live results were read
      "source": "GET https://glassgovernment.org/wp-json/ggrr/v1/search?q=<q>",
      "notes": "...",                               (optional, free text)
      "queries": {
        "<query>": ["<slug>" | "<record URL>", ...] the live hits, in the live order
      }
    }

A hit may be a bare slug or any URL of the record (`https://site/library/<slug>/`,
`/reading-room/<slug>/#page-3`): the last path segment is the slug.

The room side is the built room on disk: its own pagefind.js runs in Chromium
(Playwright), with the same options the finder uses, so the ranking compared is
the ranking a reader gets. Top N is the first N results.

A live hit whose record is not in the room (the exporter excluded it, or it is
not public) cannot be found and is not counted as a miss: it is listed under
`not_in_room`, which is the matrix row's explained difference.
"""

from __future__ import annotations

import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

TOP_N = 100
KEYS = {"site", "fetched", "source", "notes", "queries"}


class SearchParityError(ValueError):
    """The live results file cannot be used as written. Every problem is listed."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def slug_of(hit: str) -> str:
    """`<slug>` from a slug or any URL of a record."""
    path = urlsplit(hit).path if ("/" in hit or ":" in hit) else hit
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else ""


def parse_live(data: object, sites: tuple[str, ...]) -> dict:
    """The live results, checked; queries as {query: [slug, ...]}."""
    if not isinstance(data, dict):
        raise SearchParityError(["the live results are not a mapping"])
    problems = [f"unknown key {k!r}" for k in sorted(set(data) - KEYS, key=str)]
    problems += [f"missing {k!r}" for k in ("site", "fetched", "source", "queries") if k not in data]
    if "site" in data and data["site"] not in sites:
        problems.append(f"unknown site {data['site']!r}")
    for k in ("fetched", "source"):
        if k in data and not (isinstance(data[k], str) and data[k].strip()):
            problems.append(f"{k} is not text")
    queries = data.get("queries")
    out: dict[str, list[str]] = {}
    if "queries" in data:
        if not isinstance(queries, dict) or not queries:
            problems.append("queries is not a non-empty mapping of query -> hits")
        else:
            for q, hits in queries.items():
                if not q.strip():
                    problems.append("an empty query")
                elif not (isinstance(hits, list) and all(isinstance(h, str) and slug_of(h) for h in hits)):
                    problems.append(f"{q!r}: hits are not a list of slugs or record URLs")
                else:
                    out[q] = list(dict.fromkeys(slug_of(h) for h in hits))
    if problems:
        raise SearchParityError(problems)
    return {**data, "queries": out}


def load_live(path, sites: tuple[str, ...]) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SearchParityError([f"cannot read {path}: {exc}"]) from exc
    return parse_live(data, sites)


def compare(live: dict[str, list[str]], room: dict[str, list[str]], in_room: set[str], n: int) -> dict:
    """Per query: which live hits are in the room's top `n`. Pure; no browser."""
    rows, found_all, want_all = [], 0, 0
    for q, hits in live.items():
        top = room.get(q, [])[:n]
        want = [h for h in hits if h in in_room]
        found = [h for h in want if h in top]
        rank = {h: room.get(q, []).index(h) + 1 for h in want if h in room.get(q, [])}
        rows.append({"query": q, "live": len(hits), "room_results": len(room.get(q, [])),
                     "found": len(found), "missing": [h for h in want if h not in top],
                     "missing_rank": {h: rank.get(h) for h in want if h not in top},
                     "not_in_room": [h for h in hits if h not in in_room],
                     "recall": round(len(found) / len(want), 4) if want else 1.0})
        found_all += len(found)
        want_all += len(want)
    return {"top_n": n, "queries": rows,
            "recall": round(found_all / want_all, 4) if want_all else 1.0,
            "ok": all(not r["missing"] for r in rows)}


def room_slugs(lock: dict) -> set[str]:
    """The records a built room holds, from its lock (`<slug>/index.html`)."""
    return {p.split("/")[0] for p in lock["files"] if p.count("/") == 1 and p.endswith("/index.html")}


class _Mounted(SimpleHTTPRequestHandler):
    """Serves the room directory at its mount path, as the site would."""
    mount = "/"

    def translate_path(self, path):
        path = urlsplit(path).path
        rest = path[len(self.mount):] if path.startswith(self.mount) else "__outside_the_mount__"
        return str(Path(self.directory) / rest)

    def log_message(self, *a):  # noqa: D401 - quiet
        pass


_SEARCH = """async ([base, queries, n]) => {
  const pf = await import(base + "pagefind.js");
  await pf.options({baseUrl: base.replace(/pagefind\\/$/, ""), excerptLength: 24});
  const out = {};
  for (const q of queries) {
    const res = await pf.search(q);
    const ds = await Promise.all(res.results.slice(0, n).map(r => r.data()));
    out[q] = ds.map(d => d.url);
  }
  return out;
}"""


def room_hits(room: Path, queries: list[str], n: int) -> dict[str, list[str]]:
    """Each query's first `n` results from the built room's own Pagefind, in Chromium.

    Runs in its own thread: Playwright's sync API refuses to start inside a thread
    that already has an event loop (a caller using Playwright itself).
    """
    box: dict = {}
    t = threading.Thread(target=lambda: _run_in_browser(room, queries, n, box))
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return {q: [slug_of(u) for u in us] for q, us in box["urls"].items()}


def _run_in_browser(room: Path, queries: list[str], n: int, box: dict) -> None:
    try:
        from playwright.sync_api import sync_playwright
        lock = json.loads((room / "room.lock.json").read_text(encoding="utf-8"))
        mount = lock["mount"]
        handler = functools.partial(type("H", (_Mounted,), {"mount": mount}), directory=str(room))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                page = b.new_page()
                page.goto(f"http://127.0.0.1:{srv.server_address[1]}{mount}")
                box["urls"] = page.evaluate(_SEARCH, [f"{mount}pagefind/", queries, n])
                b.close()
        finally:
            srv.shutdown()
    except Exception as exc:  # noqa: BLE001 - re-raised in the caller's thread
        box["error"] = exc


def run(live_path, room: Path, n: int = TOP_N, sites: tuple[str, ...] = ()) -> dict:
    live = load_live(live_path, sites)
    lock = json.loads((room / "room.lock.json").read_text(encoding="utf-8"))
    if "search" not in lock:
        raise SearchParityError([f"{room} was built without corpus search (pack features.corpus-search)"])
    # Deeper than n, so a miss can say where the room ranked it.
    got = room_hits(room, list(live["queries"]), max(4 * n, 200))
    return {"site": live["site"], "fetched": live["fetched"], "source": live["source"],
            **compare(live["queries"], got, room_slugs(lock), n)}


def text(rep: dict) -> str:
    lines = [f"{'AGREES' if rep['ok'] else 'DIFFERS'}: recall {rep['recall']:.1%} of live hits in the room's top "
             f"{rep['top_n']} ({rep['site']}, live read {rep['fetched']})"]
    for r in rep["queries"]:
        lines.append(f"   {r['query']!r}: {r['found']}/{r['live'] - len(r['not_in_room'])} found"
                     + (f", {len(r['not_in_room'])} live hit(s) not in the room" if r["not_in_room"] else ""))
        lines += [f"      missing {h} (room rank {r['missing_rank'][h] or 'none'})" for h in r["missing"]]
    return "\n".join(lines)
