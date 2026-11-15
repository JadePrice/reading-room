"""The index's List / Gallery switch (pack layout.gallery).

Off, nothing ships (the goldens pin that for every pack without it). On, the index
has a two-button group hidden until room-gallery.js runs, and each card with a
thumbnail holds the picture's URL on an empty link: a List visitor downloads no image.
The browser tests check that request log, the reload memory, the filters acting on
both views, real 44px buttons and no sideways scroll at phone widths.
"""

from __future__ import annotations


def test_the_gallery_script_has_no_em_dash():
    from roomkit import room as R
    assert "—" not in R.ROOM_GALLERY_JS and "—" not in R.GALLERY_CSS
