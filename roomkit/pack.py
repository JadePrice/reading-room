"""A site pack: the one place a site customizes the shared reading room.

    packs/<site>/pack.json    validated against packs/pack.schema.json (the
                              structure; Civica validates tenant packs against
                              the same file), then by the checks below.

The schema says what a pack may contain. This module adds what a schema cannot:

- contrast. For each foreground/background pair the template actually paints,
  light and dark: 4.5:1 for text, 3:1 for focus rings and button fills
  (`color.py` parses hex and oklch() with alpha, composites, measures). A
  `page-bg` of `transparent` (the room sits on the site's own page) is measured
  against `identity.backdrop`, which must then be given. This check would have
  stopped the 1.29:1 dd panels of 2026-10-12 at build time;
- every `extra_css` rule scoped under `#room-content` (or the plain page's own
  `body.room-plain`), the rule `room.css` already keeps;
- no feature turned on whose matrix rows are all `dropped`
  (roomkit/parity-matrix.yaml);
- fonts and logos are files inside the pack (no CDN), and they exist.

Every problem is listed; nothing is guessed. A pack that fails is refused whole.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import color as C
from . import css

PACKS = Path(__file__).resolve().parent / "packs"
SCHEMA = PACKS / "pack.schema.json"

COLOR_TOKENS = ("page-bg", "page-ink", "page-ink-soft", "page-link", "surface", "surface-sunk", "ink", "ink-soft",
                "rule", "link", "accent", "on-accent", "focus")
# Selectors extra_css may style: the room's content element, and the plain page
# that the room owns whole (a pack may paint its own body).
SCOPES = ("#room-content", ".room__skip", "body.room-plain")
# What the template paints on what. (foreground, background, minimum, why)
PAIRS = (
    ("page-ink", "page-bg", 4.5, "title and lede on the page"),
    ("page-ink-soft", "page-bg", 4.5, "eyebrow, stats and counts on the page"),
    ("page-link", "page-bg", 4.5, "links on the page"),
    ("ink", "surface", 4.5, "panel text"),
    ("ink-soft", "surface", 4.5, "panel labels and notes"),
    ("link", "surface", 4.5, "panel links"),
    ("ink", "surface-sunk", 4.5, "citation and chip text"),
    ("ink-soft", "surface-sunk", 4.5, "chip kind and quote"),
    ("link", "surface-sunk", 4.5, "linked chip labels"),
    ("on-accent", "accent", 4.5, "button text"),
    ("focus", "page-bg", 3.0, "focus ring on the page"),
    ("focus", "surface", 3.0, "focus ring on a panel"),
    ("accent", "surface", 3.0, "button fill on a panel"),
)
# Feature switch -> the matrix rows it stands for.
FEATURE_ROWS = {
    "collections": ("collections-index", "collection-page", "index-collections-grid"),
    "topics": ("topics",),
    "entities": ("entities-index", "entity-page"),
    "power-maps": ("power-maps",),
    "records-requests": ("records-requests",),
    "translation": ("translation",),
    "read-aloud": ("read-aloud",),
    "passage-cite": ("passage-citations",),
    "corpus-search": ("index-fulltext-search", "index-suggest"),
}


class PackError(ValueError):
    """The pack cannot be used as written. Every problem is listed."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --- the checks, one per concern; validate() runs them all ----------------------

def _page_bg(tokens: dict, backdrop: str, scheme: str) -> tuple[C.RGB | None, list[str]]:
    """The opaque color the page really is, or why it cannot be known."""
    base = C.parse(backdrop) if backdrop else None
    page = tokens["page-bg"].strip()
    if page == "transparent":
        if not base:
            return None, [f"{scheme}: page-bg is transparent, so identity.backdrop must name the color behind it"]
        return base[0], []
    p = C.parse(page)
    if not p:
        return None, [f"{scheme}: page-bg {page!r} is not a hex or oklch() color, so contrast cannot be checked"]
    if p[1] < 1:
        if not base:
            return None, [f"{scheme}: page-bg is translucent, so identity.backdrop must name the color behind it"]
        return C.over(p, base[0]), []
    return p[0], []


def contrast_problems(tokens: dict, backdrop: str, scheme: str) -> list[str]:
    """Every PAIRS pair below its minimum, with the ratio and what it paints."""
    page, out = _page_bg(tokens, backdrop, scheme)
    if page is None:
        return out
    solid = {"page-bg": page}
    for name in ("surface", "surface-sunk", "accent"):
        c = C.parse(tokens[name])
        if c:
            solid[name] = C.over(c, page)
    for name in COLOR_TOKENS[1:]:
        if not C.parse(tokens[name]):
            out.append(f"{scheme}: {name} {tokens[name]!r} is not a hex or oklch() color")
    for fg, bg, need, why in PAIRS:
        c = C.parse(tokens[fg])
        if not c or bg not in solid:
            continue
        ratio = C.contrast(C.over(c, solid[bg]), solid[bg])
        if ratio < need:
            out.append(f"{scheme}: {fg} on {bg} is {ratio:.2f}:1, needs {need}:1 ({why})")
    return out


def schema_problems(pack: object) -> list[str]:
    import jsonschema
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(pack)'}: {e.message}"
            for e in sorted(validator.iter_errors(pack), key=lambda e: list(map(str, e.absolute_path)))]


def token_problems(pack: dict) -> list[str]:
    out = [f"tokens: missing {t!r}" for t in COLOR_TOKENS if t not in pack["tokens"]]
    if pack.get("tokens_dark") is not None:
        out += [f"tokens_dark: missing {t!r}" for t in COLOR_TOKENS if t not in pack["tokens_dark"]]
    return out


def scope_problems(pack: dict) -> list[str]:
    return [f"extra_css: rule {sel!r} is not scoped under {' or '.join(SCOPES)}"
            for sel in css.css_selectors(pack.get("extra_css", "")) if not sel.startswith(SCOPES)]


def file_problems(pack: dict, root: Path) -> list[str]:
    ident = pack["identity"]
    files = [f["src"] for f in pack.get("fonts", [])]
    files += [ident["logo"]["src"]] if ident.get("logo") else []
    files += [ident["favicon"]] if ident.get("favicon") else []
    return [f"{f}: not a file in the pack" for f in files if not (root / f).is_file()]


def feature_problems(pack: dict, matrix: list[dict]) -> list[str]:
    dropped = {r["id"] for r in matrix if r["disposition"] == "dropped"}
    return [f"features.{feat}: on, but the parity matrix drops {', '.join(FEATURE_ROWS[feat])}"
            for feat, on in sorted(pack.get("features", {}).items()) if on and set(FEATURE_ROWS[feat]) <= dropped]


def validate(pack: object, root: Path | None = None, matrix: list[dict] | None = None) -> list[str]:
    """Every problem with `pack`. `root` is the pack directory (for its files);
    `matrix` the parity matrix rows (for dropped features)."""
    out = schema_problems(pack)
    if out:
        return out
    out = token_problems(pack)
    if not out:
        backdrop, dark = pack["identity"].get("backdrop", ""), pack.get("tokens_dark")
        out += contrast_problems(pack["tokens"], backdrop, "light" if dark else "tokens")
        out += contrast_problems(dark, backdrop, "dark") if dark else []
    out += scope_problems(pack)
    out += file_problems(pack, root) if root is not None else []
    out += feature_problems(pack, matrix) if matrix is not None else []
    return out


def load(path: Path | str, matrix: list[dict] | None = None) -> dict:
    """A validated pack from a pack directory (or its pack.json). Raises PackError."""
    p = Path(path)
    root, file = (p, p / "pack.json") if p.is_dir() else (p.parent, p)
    try:
        pack = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError([f"cannot read {file}: {exc}"]) from exc
    problems = validate(pack, root, matrix)
    if problems:
        raise PackError([f"{file}: {x}" for x in problems])
    return pack


def for_site(site: str) -> dict:
    """The pack shipped with roomkit for `site` (packs/<site>/)."""
    return load(PACKS / site)
