"""exporters/merge-slices.py: an exporter's ROOMKIT_SLICE pieces, joined or refused."""

from __future__ import annotations

import importlib.util
import json

import pytest

from roomkit import build as B

_spec = importlib.util.spec_from_file_location(
    "merge_slices", B.REPO_ROOT / "roomkit/exporters/merge-slices.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SITE = {"name": "example.org", "room_path": "/library/"}


def _piece(offset, limit, total, slugs, excluded=(), site=SITE):
    return {"site": site, "exported_by": "x", "documents": [{"slug": s} for s in slugs],
            "excluded": [{"slug": s, "problem": "no servable file"} for s in excluded],
            "slice": {"offset": offset, "limit": limit, "total": total}}


def test_pieces_join_in_record_order_whatever_order_they_arrive_in():
    out = M.merge([_piece(2, 2, 5, ["c"], excluded=["d"]), _piece(0, 2, 5, ["a", "b"]), _piece(4, 2, 5, ["e"])])
    assert [d["slug"] for d in out["documents"]] == ["a", "b", "c", "e"]
    assert out["excluded"] == [{"slug": "d", "problem": "no servable file"}]
    assert "slice" not in out and out["site"] == SITE and out["exported_by"] == "x"


@pytest.mark.parametrize("pieces, why", [
    ([_piece(0, 2, 4, ["a", "b"]), _piece(3, 2, 4, ["d"])], "gap at record 2"),
    ([_piece(0, 2, 4, ["a", "b"]), _piece(1, 3, 4, ["b", "c", "d"])], "overlap at record 2"),
    ([_piece(0, 2, 4, ["a", "b"])], "slices end at record 2 of 4"),
    ([_piece(0, 2, 4, ["a", "b"]), _piece(2, 2, 5, ["c", "d"])], "different export"),
    ([_piece(0, 2, 4, ["a", "b"]), _piece(2, 2, 4, ["c", "d"], site={"name": "other.org"})], "different export"),
    ([_piece(0, 2, 4, ["a"]), _piece(2, 2, 4, ["c", "d"])], "holds 1 records, its window holds 2"),
    ([_piece(0, 2, 4, ["a", "b"]), _piece(2, 2, 4, ["b", "d"])], "more than one slice"),
    ([{"error": "gg-reading-room is not active"}], "exporter error"),
    ([{"site": SITE, "documents": []}], "no slice"),
])
def test_a_gap_overlap_short_piece_or_mixed_export_is_refused(pieces, why):
    with pytest.raises(M.SliceError, match=why):
        M.merge(pieces)


def test_the_cli_writes_nothing_when_it_refuses(tmp_path, capsys):
    a = tmp_path / "a.json"
    a.write_text(json.dumps(_piece(0, 2, 4, ["a", "b"])))
    out = tmp_path / "out.json"
    assert M.main(["merge-slices.py", str(out), str(a)]) == 1
    assert not out.exists() and "refused" in capsys.readouterr().err
    b = tmp_path / "b.json"
    b.write_text(json.dumps(_piece(2, 2, 4, ["c", "d"])))
    assert M.main(["merge-slices.py", str(out), str(b), str(a)]) == 0
    assert [d["slug"] for d in json.loads(out.read_text())["documents"]] == ["a", "b", "c", "d"]


def test_the_entities_block_comes_from_the_first_piece_alone():
    # The GG exporter writes `entities` into the slice at offset 0 only.
    first = _piece(0, 2, 3, ["a", "b"])
    first["entities"] = {"pages": [{"type": "vendor", "slug": "x"}]}
    merged = M.merge([_piece(2, 2, 3, ["c"]), first])
    assert merged["entities"] == first["entities"]
