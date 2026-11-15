"""
Clean-Room Pydantic v2 Models and Geometry Math for Internet Archive BookReader.

Implements book manifests, 2-up book spread pairing algorithms, viewport fitting math,
and OCR bounding-box percentage projections for reading-room text overlays.
Zero external dependencies, full Pydantic v2 compatibility.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OCRPctBBox(BaseModel):
    """Resolution-independent bounding box expressed in percentages (0.0 to 100.0%)."""

    model_config = ConfigDict(populate_by_name=True)

    left_pct: float
    top_pct: float
    width_pct: float
    height_pct: float

    @property
    def css_style(self) -> str:
        """Returns standard absolute CSS positioning string."""
        return (
            f"left: {self.left_pct:.3f}%; top: {self.top_pct:.3f}%; "
            f"width: {self.width_pct:.3f}%; height: {self.height_pct:.3f}%;"
        )


class OCRWord(BaseModel):
    """Single OCR word with native pixel bounding box [left, top, right, bottom]."""

    model_config = ConfigDict(populate_by_name=True)

    text: str
    bbox: list[int]  # [left, top, right, bottom]

    def to_pct(self, leaf_width: int, leaf_height: int) -> OCRPctBBox:
        left, t, r, b = self.bbox
        left_pct = round((left / leaf_width) * 100.0, 3)
        top_pct = round((t / leaf_height) * 100.0, 3)
        width_pct = round(((r - left) / leaf_width) * 100.0, 3)
        height_pct = round(((b - t) / leaf_height) * 100.0, 3)
        return OCRPctBBox(
            left_pct=left_pct,
            top_pct=top_pct,
            width_pct=width_pct,
            height_pct=height_pct,
        )


class OCRLine(BaseModel):
    """Line of OCR text with child words and native pixel bounding box."""

    model_config = ConfigDict(populate_by_name=True)

    line_id: str
    bbox: list[int]
    text: str
    words: list[OCRWord] = Field(default_factory=list)

    def to_pct(self, leaf_width: int, leaf_height: int) -> OCRPctBBox:
        left, t, r, b = self.bbox
        left_pct = round((left / leaf_width) * 100.0, 3)
        top_pct = round((t / leaf_height) * 100.0, 3)
        width_pct = round(((r - left) / leaf_width) * 100.0, 3)
        height_pct = round(((b - t) / leaf_height) * 100.0, 3)
        return OCRPctBBox(
            left_pct=left_pct,
            top_pct=top_pct,
            width_pct=width_pct,
            height_pct=height_pct,
        )


class SearchResultHighlight(BaseModel):
    """Highlighted search result bounding box projected onto a page spread."""

    model_config = ConfigDict(populate_by_name=True)

    query: str
    matched_text: str
    leaf_index: int
    bbox_pct: OCRPctBBox


class TextOverlayLayer(BaseModel):
    """OCR layer for a specific page leaf with query highlight resolution."""

    model_config = ConfigDict(populate_by_name=True)

    item_id: str
    leaf_index: int
    leaf_width: int
    leaf_height: int
    lines: list[OCRLine] = Field(default_factory=list)

    def search_text(
        self, query: str, case_sensitive: bool = False
    ) -> list[SearchResultHighlight]:
        """Search words within the OCR layer and return percentage highlight boxes."""
        results: list[SearchResultHighlight] = []
        target = query.strip() if case_sensitive else query.strip().lower()
        if not target:
            return results

        for line in self.lines:
            for word in line.words:
                w_text = word.text if case_sensitive else word.text.lower()
                if target in w_text:
                    results.append(
                        SearchResultHighlight(
                            query=query,
                            matched_text=word.text,
                            leaf_index=self.leaf_index,
                            bbox_pct=word.to_pct(self.leaf_width, self.leaf_height),
                        )
                    )
        return results


class LeafDimension(BaseModel):
    """Width and height dimensions for an individual book page leaf."""

    model_config = ConfigDict(populate_by_name=True)

    leaf_index: int
    width: int
    height: int

    @property
    def aspect_ratio(self) -> float:
        return round(self.width / float(self.height), 4) if self.height > 0 else 0.0


class ViewportFit(BaseModel):
    """Calculated layout coordinates and scale factor for rendering inside a viewport."""

    model_config = ConfigDict(populate_by_name=True)

    scale: float
    rendered_width: float
    rendered_height: float
    offset_x: float
    offset_y: float


class PageSpread(BaseModel):
    """A single view unit (1-up or 2-up book spread)."""

    model_config = ConfigDict(populate_by_name=True)

    spread_index: int
    mode: str = "2up"  # "1up" or "2up"
    left_leaf: LeafDimension | None = None
    right_leaf: LeafDimension | None = None

    @property
    def total_width(self) -> int:
        w_left = self.left_leaf.width if self.left_leaf else 0
        w_right = self.right_leaf.width if self.right_leaf else 0
        return w_left + w_right

    @property
    def max_height(self) -> int:
        h_left = self.left_leaf.height if self.left_leaf else 0
        h_right = self.right_leaf.height if self.right_leaf else 0
        return max(h_left, h_right)

    def fit_viewport(
        self, viewport_width: float, viewport_height: float
    ) -> ViewportFit:
        """Calculate uniform scale and centering offsets to fit spread inside viewport."""
        sw = float(self.total_width)
        sh = float(self.max_height)
        if sw <= 0 or sh <= 0:
            return ViewportFit(
                scale=1.0,
                rendered_width=0.0,
                rendered_height=0.0,
                offset_x=0.0,
                offset_y=0.0,
            )

        scale = min(viewport_width / sw, viewport_height / sh)
        rw = round(sw * scale, 2)
        rh = round(sh * scale, 2)
        ox = round((viewport_width - rw) / 2.0, 2)
        oy = round((viewport_height - rh) / 2.0, 2)

        return ViewportFit(
            scale=round(scale, 5),
            rendered_width=rw,
            rendered_height=rh,
            offset_x=ox,
            offset_y=oy,
        )


class BookManifest(BaseModel):
    """Complete manifest of an item for Internet Archive BookReader rendering."""

    model_config = ConfigDict(populate_by_name=True)

    item_id: str
    title: str
    num_pages: int
    leaf_dimensions: list[LeafDimension]
    image_url_template: str = (
        "https://archive.org/download/{item_id}/page/leaf_{leaf_index}_w{width}.jpg"
    )

    def get_leaf_url(self, leaf_index: int, width: int | None = None) -> str:
        """Resolve the image URL for a given leaf index and optional width constraint."""
        w = width if width is not None else 1200
        return self.image_url_template.format(
            item_id=self.item_id, leaf_index=leaf_index, width=w
        )

    def get_2up_spreads(self) -> list[PageSpread]:
        """Construct standard 2-up book spreads (Cover solo on right, then verso/recto pairs)."""
        spreads: list[PageSpread] = []
        leaves_by_idx = {ld.leaf_index: ld for ld in self.leaf_dimensions}

        if not leaves_by_idx:
            return spreads

        # Spread 0: Cover page (Leaf 0) on right side (recto)
        spread_idx = 0
        spreads.append(
            PageSpread(
                spread_index=spread_idx,
                mode="2up",
                left_leaf=None,
                right_leaf=leaves_by_idx.get(0),
            )
        )
        spread_idx += 1

        # Subsequent spreads: pair (1, 2), (3, 4), etc.
        i = 1
        while i < self.num_pages:
            left = leaves_by_idx.get(i)
            right = leaves_by_idx.get(i + 1)
            spreads.append(
                PageSpread(
                    spread_index=spread_idx,
                    mode="2up",
                    left_leaf=left,
                    right_leaf=right,
                )
            )
            spread_idx += 1
            i += 2

        return spreads

    def get_1up_spreads(self) -> list[PageSpread]:
        """Construct 1-up spreads where each leaf is displayed singly."""
        spreads: list[PageSpread] = []
        leaves_by_idx = {ld.leaf_index: ld for ld in self.leaf_dimensions}

        for i in range(self.num_pages):
            leaf = leaves_by_idx.get(i)
            spreads.append(
                PageSpread(
                    spread_index=i,
                    mode="1up",
                    left_leaf=None,
                    right_leaf=leaf,
                )
            )
        return spreads
