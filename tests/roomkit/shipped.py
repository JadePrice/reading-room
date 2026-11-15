"""The packs this checkout ships, by site name: packs/ (roomkit's own: default, example) and,
when the sites layer is here, sites/packs/. Tests that hold for every pack run over these, so
they name no site and run over whichever packs exist."""

from __future__ import annotations

from roomkit import build as B


def _names(*bases) -> tuple[str, ...]:
    return tuple(sorted({d.name for base in bases if base.is_dir()
                         for d in base.iterdir() if (d / "pack.json").is_file()}))


PACKS = _names(*B.PACK_DIRS)
# The sites layer's packs alone (empty without it).
SITE_PACKS = _names(*B.PACK_DIRS[1:])
