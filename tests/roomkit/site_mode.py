"""A site's pack with the index's 2026-11-10 layout keys removed (lead, newest, added,
cover_summaries, finder), so a test that pins the export's order or the plain finder
(WordPress parity, the collections table, the flat sort) keeps testing that mode.
tests/roomkit/sites/test_index_lead.py tests the keys themselves."""

from __future__ import annotations

import copy

from roomkit import build as B

INDEX_KEYS = ("lead", "newest", "added", "cover_summaries", "finder")


def site_mode(site: str) -> dict:
    p = copy.deepcopy(B.pack_for_site(site))
    for k in INDEX_KEYS:
        p["layout"].pop(k, None)
    return p
