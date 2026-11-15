"""Pages of records on the index and facet pages (pack layout.page_size).

Off, nothing ships. On, room-pager.js shows page_size records at a time under numbered
Previous / Next buttons. It pages what the filters leave showing, keeps the page in the
URL (reload and Back land on it), sends a jump link to the page that holds its group,
and has 44px buttons with no sideways scroll at phone widths. Without JavaScript every
record shows.
"""

from __future__ import annotations

from roomkit import room as R


def test_the_pager_has_no_em_or_en_dash():
    for s in (R.ROOM_PAGER_JS, R.PAGER_CSS):
        assert "—" not in s and "–" not in s
