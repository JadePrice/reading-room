"""Read a design-tokens CSS file (design-tokens/*.tokens.css): its custom properties.

    tokens = read(css_text)
    tokens.values      {"--dl-bg": "#08090b", ...}   top-level :root, var() resolved
    tokens.problems    {"--name": ["defined twice ...", ...]}: duplicates, unresolved
                       references, cycles (all of them), by the property they affect
    tokens.variants    {"--dl-text": ["@media (prefers-contrast: more): #f8fafc"], ...}

Only top-level `:root` blocks are the site's tokens. A property defined twice
there is a duplicate: which one a browser uses depends on order, and a pack
must not inherit whichever block happened to win (dd's live theme dims
--dl-text-dim to 2.46:1 in a later block; that is why). Definitions inside an
at-rule (`@media (prefers-contrast: more)`) are variants: listed, not imported.

`var(--x)` and `var(--x, fallback)` resolve against the top-level values; an
unknown name without a fallback, or a cycle, is a problem, never a guess.
Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COMMENT = re.compile(r"/\*.*?\*/", re.S)
DECL = re.compile(r"^\s*(--[A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$", re.S)
VAR = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")


@dataclass
class Tokens:
    values: dict[str, str] = field(default_factory=dict)
    problems: dict[str, list[str]] = field(default_factory=dict)
    variants: dict[str, list[str]] = field(default_factory=dict)


def _blocks(css: str) -> list[tuple[str, str]]:
    """Top-level (prelude, body) pairs, braces matched."""
    out, depth, start, prelude_from = [], 0, 0, 0
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append((css[prelude_from:start].strip(), css[start + 1:i]))
                prelude_from = i + 1
    return out


def _decls(body: str) -> list[tuple[str, str]]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == ";" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [(m.group(1), m.group(2)) for p in parts if (m := DECL.match(p))]


def _flag(t: Tokens, name: str, why: str) -> None:
    if why not in t.problems.setdefault(name, []):
        t.problems[name].append(why)


def read(css: str) -> Tokens:
    t = Tokens()
    raw: dict[str, str] = {}
    for prelude, body in _blocks(COMMENT.sub("", css)):
        if prelude == ":root":
            for name, value in _decls(body):
                if name in raw:
                    _flag(t, name, f"defined twice at the top level ({raw[name]!r}, then {value!r})")
                else:
                    raw[name] = value
        elif prelude.startswith("@"):
            for inner, ibody in _blocks(body):
                if inner == ":root":
                    for name, value in _decls(ibody):
                        t.variants.setdefault(name, []).append(f"{prelude}: {value}")

    def resolve(name: str, seen: tuple[str, ...]) -> str | None:
        if name in seen:
            _flag(t, seen[0], f"refers to itself through {' -> '.join(seen + (name,))}")
            return None
        value = raw[name]

        def sub(m: re.Match) -> str:
            ref, fallback = m.group(1), m.group(2)
            if ref in raw:
                got = resolve(ref, seen + (name,))
                return got if got is not None else m.group(0)
            if fallback is not None:
                return fallback.strip()
            _flag(t, name, f"refers to {ref}, which the file does not define")
            return m.group(0)
        return VAR.sub(sub, value)

    for name in raw:
        got = resolve(name, ())
        if got is not None:
            t.values[name] = got
    return t
