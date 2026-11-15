"""The room's CSS that depends on the site: tokens from the pack, and the scoping rule.

`theme_css(pack)` turns a site pack's tokens (light, dark, the reader bridge)
and its `extra_css` into the stylesheet that follows the shared `room.css`.
`css_selectors(css)` lists a stylesheet's selectors, which is how both
`room.css` and a pack's `extra_css` are held to `#room-content` (pack.py).

No imports beyond the standard library: it travels with the room's core.
"""

from __future__ import annotations

import re

ROOT_ID = "room-content"
# The body of the page, which the room owns whole.
PLAIN_BODY = "body.room-plain"


TOKENS = ("page-bg", "page-ink", "page-ink-soft", "page-link", "surface", "surface-sunk", "ink", "ink-soft",
          "rule", "link", "accent", "on-accent", "focus", "font-body", "font-display", "font-mono",
          "radius", "radius-pill", "measure")


def css_selectors(css: str) -> list[str]:
    """Every selector in `css` (comments and @media/@supports wrappers ignored)."""
    bare = re.sub(r"/\*.*?\*/|@(?:media|supports)[^{]*\{", "", css, flags=re.DOTALL)
    return [sel.strip() for rule in re.findall(r"(?:^|})\s*([^{}@]+)\{", bare) for sel in rule.split(",")]


def theme_css(pack: dict) -> str:
    """The site pack's tokens, its reader bridge and any extra rules, as CSS.

    The room draws the header and footer around `#room-content` itself, so the
    tokens also go on `body.room-plain`, the body follows the toggle through
    `:has()`, and an `identity.backdrop` paints the body (it is the color behind
    a transparent page-bg).
    """
    R, P = f"#{ROOT_ID}", PLAIN_BODY

    def block(roots: tuple[str, ...], toks: dict, reader: dict | None = None) -> str:
        unknown = set(toks) - set(TOKENS)
        if unknown:
            raise ValueError(f"unknown theme tokens: {sorted(unknown)}")
        body = "".join(f"--room-{k}:{v};" for k, v in sorted(toks.items()))
        out = f"{','.join(roots)}{{{body}}}\n"
        if reader:
            out += f"{roots[0]} .rr-reader{{{''.join(f'--rr-{k}:{v};' for k, v in sorted(reader.items()))}}}\n"
        return out

    def roots(room: str, page: str) -> tuple[str, ...]:
        return (room, page)

    css = block(roots(R, P), pack["tokens"], pack.get("reader"))
    if pack.get("tokens_dark"):
        dark, reader = pack["tokens_dark"], pack.get("reader_dark")
        if pack["layout"]["toggle"]:
            light, on = '[data-room-theme="light"]', '[data-room-theme="dark"]'
            css += "@media (prefers-color-scheme:dark){" \
                + block(roots(f"{R}:not({light})", f"{P}:not(:has({R}{light}))"), dark, reader) + "}\n"
            css += block(roots(f"{R}{on}", f"{P}:has({R}{on})"), dark, reader)
        else:
            css += "@media (prefers-color-scheme:dark){" + block(roots(R, P), dark, reader) + "}\n"
    if pack["identity"].get("backdrop"):
        css += f"{P}{{background:{pack['identity']['backdrop']}}}\n"
    return css + pack.get("extra_css", "")
