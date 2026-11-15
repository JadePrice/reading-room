"""
Tests for clean-room BookReader 2-up spread geometry, viewport math, and OCR highlighting.
"""

from __future__ import annotations

from roomkit.bookreader import (
    BookManifest,
    TextOverlayLayer,
)

SAMPLE_BOOK_MANIFEST = {
    "item_id": "examplecommoncoun1995exam",
    "title": "Proceedings of the Common Council of the City of Example 1995",
    "num_pages": 4,
    "leaf_dimensions": [
        {"leaf_index": 0, "width": 1800, "height": 2600},
        {"leaf_index": 1, "width": 1820, "height": 2620},
        {"leaf_index": 2, "width": 1810, "height": 2610},
        {"leaf_index": 3, "width": 1815, "height": 2615},
    ],
    "image_url_template": "https://archive.org/download/{item_id}/page/leaf_{leaf_index}_w{width}.jpg",
}

SAMPLE_OCR_LEAF = {
    "item_id": "examplecommoncoun1995exam",
    "leaf_index": 1,
    "leaf_width": 1820,
    "leaf_height": 2620,
    "lines": [
        {
            "line_id": "line_01",
            "bbox": [150, 200, 1670, 260],
            "text": "CITY OF EXAMPLE COMMON COUNCIL REGULAR MEETING",
            "words": [
                {"text": "CITY", "bbox": [150, 200, 280, 260]},
                {"text": "OF", "bbox": [300, 200, 360, 260]},
                {"text": "EXAMPLE", "bbox": [380, 200, 680, 260]},
                {"text": "COMMON", "bbox": [700, 200, 980, 260]},
                {"text": "COUNCIL", "bbox": [1000, 200, 1280, 260]},
                {"text": "REGULAR", "bbox": [1300, 200, 1550, 260]},
                {"text": "MEETING", "bbox": [1570, 200, 1670, 260]},
            ],
        },
        {
            "line_id": "line_02",
            "bbox": [150, 320, 1600, 375],
            "text": "Item 42: Resolution approving automated surveillance equipment contract.",
            "words": [
                {"text": "Item", "bbox": [150, 320, 240, 375]},
                {"text": "42:", "bbox": [250, 320, 310, 375]},
                {"text": "Resolution", "bbox": [330, 320, 560, 375]},
                {"text": "approving", "bbox": [580, 320, 770, 375]},
                {"text": "automated", "bbox": [790, 320, 1010, 375]},
                {"text": "surveillance", "bbox": [1030, 320, 1310, 375]},
                {"text": "equipment", "bbox": [1330, 320, 1540, 375]},
                {"text": "contract.", "bbox": [1550, 320, 1600, 375]},
            ],
        },
    ],
}


def test_book_manifest_and_leaves():
    manifest = BookManifest.model_validate(SAMPLE_BOOK_MANIFEST)
    assert manifest.item_id == "examplecommoncoun1995exam"
    assert manifest.num_pages == 4
    assert len(manifest.leaf_dimensions) == 4

    leaf0 = manifest.leaf_dimensions[0]
    assert leaf0.width == 1800
    assert leaf0.height == 2600
    assert leaf0.aspect_ratio == round(1800 / 2600.0, 4)

    url = manifest.get_leaf_url(1, width=1600)
    assert (
        url
        == "https://archive.org/download/examplecommoncoun1995exam/page/leaf_1_w1600.jpg"
    )


def test_2up_spread_generation_and_pairing():
    manifest = BookManifest.model_validate(SAMPLE_BOOK_MANIFEST)
    spreads_2up = manifest.get_2up_spreads()

    # For 4 pages (0, 1, 2, 3):
    # Spread 0: Left=None, Right=Leaf 0 (Cover)
    # Spread 1: Left=Leaf 1, Right=Leaf 2
    # Spread 2: Left=Leaf 3, Right=None (last odd page)
    assert len(spreads_2up) == 3

    s0 = spreads_2up[0]
    assert s0.left_leaf is None
    assert s0.right_leaf is not None
    assert s0.right_leaf.leaf_index == 0
    assert s0.total_width == 1800
    assert s0.max_height == 2600

    s1 = spreads_2up[1]
    assert s1.left_leaf is not None and s1.left_leaf.leaf_index == 1
    assert s1.right_leaf is not None and s1.right_leaf.leaf_index == 2
    assert s1.total_width == 1820 + 1810
    assert s1.max_height == max(2620, 2610)

    s2 = spreads_2up[2]
    assert s2.left_leaf is not None and s2.left_leaf.leaf_index == 3
    assert s2.right_leaf is None


def test_viewport_fit_calculations():
    manifest = BookManifest.model_validate(SAMPLE_BOOK_MANIFEST)
    spreads = manifest.get_2up_spreads()
    spread1 = spreads[1]  # total width = 3630, max height = 2620

    # Fit into 1920 x 1080 viewport
    fit = spread1.fit_viewport(1920.0, 1080.0)
    expected_scale = min(1920.0 / 3630.0, 1080.0 / 2620.0)
    assert round(fit.scale, 4) == round(expected_scale, 4)
    assert fit.rendered_width <= 1920.0
    assert fit.rendered_height <= 1080.0
    assert fit.offset_x >= 0.0
    assert fit.offset_y >= 0.0


def test_ocr_percentage_projection_and_search():
    ocr_layer = TextOverlayLayer.model_validate(SAMPLE_OCR_LEAF)
    assert ocr_layer.leaf_index == 1
    assert len(ocr_layer.lines) == 2

    # Check percentage conversion on line 1
    line1 = ocr_layer.lines[0]
    line1_pct = line1.to_pct(ocr_layer.leaf_width, ocr_layer.leaf_height)
    expected_l_pct = round((150 / 1820.0) * 100.0, 3)
    assert line1_pct.left_pct == expected_l_pct
    assert "left: " in line1_pct.css_style
    assert "%" in line1_pct.css_style

    # Search for "surveillance"
    hits = ocr_layer.search_text("surveillance")
    assert len(hits) == 1
    hit = hits[0]
    assert hit.matched_text == "surveillance"
    assert hit.leaf_index == 1
    assert hit.bbox_pct.width_pct > 0
    assert hit.bbox_pct.height_pct > 0

    # Search for non-existent token
    no_hits = ocr_layer.search_text("nonexistentterm")
    assert len(no_hits) == 0


def test_bookreader_roundtrip_serialization():
    manifest = BookManifest.model_validate(SAMPLE_BOOK_MANIFEST)
    json_str = manifest.model_dump_json()
    reloaded = BookManifest.model_validate_json(json_str)
    assert reloaded.item_id == manifest.item_id
    assert len(reloaded.leaf_dimensions) == len(manifest.leaf_dimensions)

    ocr = TextOverlayLayer.model_validate(SAMPLE_OCR_LEAF)
    ocr_json = ocr.model_dump_json()
    reloaded_ocr = TextOverlayLayer.model_validate_json(ocr_json)
    assert reloaded_ocr.leaf_index == ocr.leaf_index
    assert len(reloaded_ocr.lines) == len(ocr.lines)
