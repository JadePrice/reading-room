"""Color math for contrast checks: parse a CSS color, composite it, measure it.

Standard library only and nothing from the rest of the repo, so it travels
with the room's core (Civica vendors it). The wiki's accessibility gate keeps
its own copy of WCAG's formula (it runs as a bare script and cannot import
this); tests/roomkit/test_pack.py holds the two to the same answers.

Parses the literal colors the site packs use: `#rgb`, `#rrggbb`,
`rgb()`/`rgba()` (comma or space syntax, alpha as a number or %) and
`oklch(L C H [/ A])`. Anything else (`var()`, named colors, `color-mix()`)
returns None: a contrast check cannot measure what it cannot resolve, so the
caller refuses it rather than guessing.
"""

from __future__ import annotations

import math
import re

RGB = tuple[float, float, float]  # gamma-encoded sRGB, 0..1

HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_N = r"([\d.]+)(%?)"
RGB_FN = re.compile(r"^rgba?\(\s*" + _N + r"\s*,?\s*" + _N + r"\s*,?\s*" + _N
                    + r"\s*(?:[,/]\s*" + _N + r")?\s*\)$")
OKLCH = re.compile(r"^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*(?:/\s*([\d.]+)(%?))?\s*\)$")


def _encode(v: float) -> float:
    """Linear light to the sRGB transfer curve, clipped to the gamut."""
    v = min(1.0, max(0.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _oklch(lum: float, chroma: float, hue_deg: float) -> RGB:
    # OKLCH -> OKLab -> LMS -> linear sRGB (Ottosson's matrices), then encoded.
    h = math.radians(hue_deg)
    a, b = chroma * math.cos(h), chroma * math.sin(h)
    l_ = (lum + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lum - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lum - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (_encode(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
            _encode(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
            _encode(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_))


def parse(value: str) -> tuple[RGB, float] | None:
    """(sRGB, alpha) for a hex, rgb()/rgba() or oklch() literal; None for anything else."""
    v = value.strip()
    m = HEX.match(v)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255), 1.0
    m = RGB_FN.match(v)
    if m:
        chan = [float(m.group(i)) / (100 if m.group(i + 1) else 255) for i in (1, 3, 5)]
        alpha = 1.0 if m.group(7) is None else float(m.group(7)) / (100 if m.group(8) else 1)
        return (min(1.0, chan[0]), min(1.0, chan[1]), min(1.0, chan[2])), min(1.0, alpha)
    m = OKLCH.match(v)
    if not m:
        return None
    lum = float(m.group(1)) / (100 if m.group(2) else 1)
    alpha = 1.0 if m.group(5) is None else float(m.group(5)) / (100 if m.group(6) else 1)
    return _oklch(lum, float(m.group(3)), float(m.group(4))), alpha


def over(color: tuple[RGB, float], backdrop: RGB) -> RGB:
    """`color` painted over an opaque `backdrop` (sRGB blending, as browsers do)."""
    rgb, alpha = color
    return (alpha * rgb[0] + (1 - alpha) * backdrop[0],
            alpha * rgb[1] + (1 - alpha) * backdrop[1],
            alpha * rgb[2] + (1 - alpha) * backdrop[2])


def relative_luminance(rgb: RGB) -> float:
    """WCAG 2.x relative luminance of a gamma-encoded sRGB color."""
    lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: RGB, bg: RGB) -> float:
    """WCAG contrast ratio, 1..21."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
