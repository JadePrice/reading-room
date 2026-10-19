"""A site pack's tokens, derived from the site's design-tokens file through a map.

    packs/<site>/tokens.map.json
    {
      "source": "design-tokens/deflockdane.tokens.css",   (repo-relative)
      "tokens":      {"surface": "--dl-bg-2",               a room token <- a site variable
                      "ink-soft": {"var": "--dl-text-muted", "why": "..."}},
      "tokens_dark": {...},                                  (optional, same shape)
      "literal":     {"page-bg": {"value": "transparent", "why": "the room sits on the site's page"}},
      "literal_dark": {...}
    }

The map is explicit and complete: the pack's `tokens` become exactly the
mapped and literal entries, nothing carried over by hand. A value that does not
come from the file is a `literal` and must say why; so may a mapped one. Every
`why` lands in the pack's `token_notes`, so the pack itself explains each value
that is not simply the site's.

Refused, all problems listed: a map key the room does not have, a token both
mapped and literal, a literal without a why, and a site variable the file does
not define, defines twice at the top level, or cannot resolve
(`tokens_css.read`). The derived pack is then checked like any pack
(`pack.validate`: contrast and the rest), so an import cannot write a pack the
build would refuse.

`derive()` changes nothing; the CLI writes only with `--write`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import css
from . import pack as P
from . import tokens_css

MAP_KEYS = {"source", "tokens", "tokens_dark", "literal", "literal_dark"}


class ImportRefused(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _scheme(mp: dict, scheme: str, toks: tokens_css.Tokens, problems: list[str]) -> tuple[dict, dict]:
    """(tokens, notes) for one scheme ("tokens" or "tokens_dark")."""
    mapped = mp.get(scheme, {})
    literal = mp.get("literal" + scheme[len("tokens"):], {})
    out, notes = {}, {}
    for name in sorted(set(mapped) | set(literal)):
        if name not in css.TOKENS:
            problems.append(f"{scheme}.{name}: not a room token")
            continue
        if name in mapped and name in literal:
            problems.append(f"{scheme}.{name}: both mapped and literal")
            continue
        if name in literal:
            entry = literal[name]
            if not (isinstance(entry, dict) and isinstance(entry.get("value"), str)
                    and isinstance(entry.get("why"), str) and entry["why"].strip()):
                problems.append(f"{scheme}.{name}: a literal needs a value and a why")
                continue
            out[name], notes[f"{scheme}.{name}"] = entry["value"], entry["why"].strip()
            continue
        entry = mapped[name]
        var, why = (entry, "") if isinstance(entry, str) else (entry.get("var"), entry.get("why", ""))
        if not isinstance(var, str) or not var.startswith("--"):
            problems.append(f"{scheme}.{name}: {entry!r} is not a site variable")
            continue
        if var in toks.problems:
            problems += [f"{scheme}.{name} <- {var}: {p}" for p in toks.problems[var]]
            continue
        value = toks.values.get(var)
        if value is None:
            problems.append(f"{scheme}.{name} <- {var}: the file does not define it")
            continue
        if "var(" in value:
            problems.append(f"{scheme}.{name} <- {var}: does not resolve ({value!r})")
            continue
        out[name] = value
        if why:
            notes[f"{scheme}.{name}"] = why
    return out, notes


def derive(map_path: Path, repo: Path) -> dict[str, Any]:
    """The pack next to `map_path` with its tokens derived, plus what changed.

    Returns {"pack", "changes": [(key, old, new)], "variants": {var: [...]}, "source"}.
    """
    map_path = Path(map_path)
    mp = json.loads(map_path.read_text(encoding="utf-8"))
    problems = [f"map: unknown key {k!r}" for k in sorted(set(mp) - MAP_KEYS)]
    source = repo / mp.get("source", "")
    if not mp.get("source") or not source.is_file():
        raise ImportRefused(problems + [f"map: source {mp.get('source')!r} is not a file in the repo"])
    toks = tokens_css.read(source.read_text(encoding="utf-8"))
    pack_path = map_path.parent / "pack.json"
    old = json.loads(pack_path.read_text(encoding="utf-8"))
    new = json.loads(json.dumps(old))
    notes: dict[str, str] = {}
    for scheme in ("tokens", "tokens_dark"):
        if scheme not in mp and not mp.get("literal" + scheme[len("tokens"):]):
            continue
        new[scheme], n = _scheme(mp, scheme, toks, problems)
        notes.update(n)
    new["token_notes"] = dict(sorted(notes.items()))
    if not new["token_notes"]:
        del new["token_notes"]
    if not problems:
        problems += P.validate(new, root=map_path.parent)
    if problems:
        raise ImportRefused(problems)
    changes = []
    for scheme in ("tokens", "tokens_dark"):
        a, b = old.get(scheme) or {}, new.get(scheme) or {}
        changes += [(f"{scheme}.{k}", a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    used = {(v if isinstance(v, str) else v.get("var")) for s in ("tokens", "tokens_dark") for v in mp.get(s, {}).values()}
    return {"pack": new, "changes": changes, "source": mp["source"],
            "variants": {v: toks.variants[v] for v in sorted(used) if v in toks.variants}}


def write(map_path: Path, result: dict[str, Any]) -> None:
    (Path(map_path).parent / "pack.json").write_text(
        json.dumps(result["pack"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
