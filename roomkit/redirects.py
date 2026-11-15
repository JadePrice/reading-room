"""Permanent redirects for pages the room no longer serves (manifest `redirects`).

A facet page is public and in the sitemap (`/library/agency/fbi/`), so when a label
merges into another its old URL must keep working. An exporter step that relabels
(a label map, say) lists each moved page:

    "redirects": [{"from": "agency/fbi/", "to": "agency/federal-bureau-of-investigation/"}]

Both paths are room-relative directories (no leading slash, ending in "/"). The
build writes each as a 301 in the server config: nginx `location = <room><from>`
and Apache `RedirectMatch 301 ^<room><from>$`.

Never a reason to refuse a publish (a retraction publish must always go through):
an entry that is malformed, a duplicate or a chain is left out at parse time; at
build time one whose `from` the room still serves (the page wins) or whose `to` it
does not serve is left out too. Every skipped entry is named in the lock under
`redirects_skipped`, so a dry run shows it. With no redirects, no byte changes.
"""

from __future__ import annotations

import re

PATH = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*/$")


def parse(raw: object) -> tuple[tuple[tuple[str, str], ...], list[str]]:
    """The well-formed (from, to) pairs, in order, and a note for each one left out."""
    if raw is None:
        return (), []
    if not isinstance(raw, list):
        return (), ["redirects is not a list; all left out"]
    pairs: list[tuple[str, str]] = []
    notes: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(raw):
        f = r.get("from") if isinstance(r, dict) else None
        t = r.get("to") if isinstance(r, dict) else None
        if not (isinstance(f, str) and isinstance(t, str) and PATH.match(f) and PATH.match(t)):
            notes.append(f"#{i}: not a pair of room-relative directory paths")
        elif f == t:
            notes.append(f"{f}: redirects to itself")
        elif f in seen:
            notes.append(f"{f}: listed twice; the first kept")
        else:
            seen.add(f)
            pairs.append((f, t))
    froms = {f for f, _t in pairs}
    chains = {f for f, t in pairs if t in froms}
    notes += [f"{f}: its target is itself redirected (a chain)" for f, _t in pairs if f in chains]
    return tuple(p for p in pairs if p[0] not in chains), notes


def active(pairs: tuple[tuple[str, str], ...], files: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """The pairs the server should answer, given the rendered files, and notes for the rest."""
    keep, notes = [], []
    for f, t in pairs:
        if f + "index.html" in files:
            notes.append(f"{f}: the room serves this page, so it is not redirected")
        elif t + "index.html" not in files:
            notes.append(f"{f}: its target {t} is not a page the room serves")
        else:
            keep.append((f, t))
    return keep, notes


def nginx_lines(at: str, pairs: list[tuple[str, str]]) -> list[str]:
    # An exact location wins over every prefix and regex location, so these come first.
    return [f"    location = {at}{f} {{ return 301 {at}{t}; }}" for f, t in pairs]


def htaccess_lines(at: str, pairs: list[tuple[str, str]]) -> list[str]:
    return [f"RedirectMatch 301 ^{re.escape(at + f)}$ {at}{t}" for f, t in pairs]
