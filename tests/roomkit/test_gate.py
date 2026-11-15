"""roomkit gate: a built room's internal links and file sizes (gate.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roomkit import cli
from roomkit import gate as G


def _room(tmp_path: Path, pages: dict[str, str], mount: str = "/rr/") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "room.lock.json").write_text(json.dumps({"mount": mount, "files": {}}))
    for rel, body in pages.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return tmp_path


def test_links_that_land_on_a_file_or_a_directory_index_pass(tmp_path):
    root = _room(tmp_path, {
        "index.html": '<a href="/rr/doc/">d</a><a href="/rr/doc/#page-2">p</a><a href="/rr/doc/?q=x">q</a>'
                      '<script src="/rr/assets/a.js"></script><a href="/rr/">home</a>',
        "doc/index.html": "<p>doc</p>", "assets/a.js": "1"})
    res = G.run(root)
    assert res["ok"] and res["links"] == 5 and res["broken"] == []


def test_a_link_into_the_mount_with_no_file_fails_and_is_named(tmp_path):
    root = _room(tmp_path, {"index.html": '<a href="/rr/gone/">g</a><img src="/rr/assets/missing.png">'})
    res = G.run(root)
    assert not res["ok"]
    assert {(b["page"], b["link"]) for b in res["broken"]} == {
        ("index.html", "/rr/gone/"), ("index.html", "/rr/assets/missing.png")}
    assert "FAILS: 2 of 2 links" in G.text(res)


def test_links_the_tree_cannot_answer_are_not_checked(tmp_path):
    root = _room(tmp_path, {"index.html": (
        '<a href="https://example.test/rr/gone/">x</a><a href="/library/x/">y</a>'
        '<a href="mailto:a@b.c">m</a><a href="//cdn.test/x.js">c</a><a href="#top">t</a>')})
    assert G.run(root)["links"] == 0


def test_a_link_cannot_climb_out_of_the_tree(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    room = tmp_path / "room"
    room.mkdir()
    _room(room, {"index.html": '<a href="/rr/../outside.txt">x</a>'})
    assert not G.run(room)["ok"]


def test_a_file_over_the_limit_fails(tmp_path):
    root = _room(tmp_path, {"index.html": "<p>ok</p>"})
    (root / "big.bin").write_bytes(b"0" * 5000)
    res = G.run(root, max_bytes=4000)
    assert not res["ok"] and res["oversize"] == [{"file": "big.bin", "bytes": 5000}]


def test_a_tree_without_a_lock_is_not_a_room(tmp_path):
    with pytest.raises(G.GateError, match="not a built room"):
        G.run(tmp_path)


def test_the_cli_exits_0_1_and_2(tmp_path, capsys):
    ok = _room(tmp_path / "ok", {"index.html": '<a href="/rr/">h</a>'})
    bad = _room(tmp_path / "bad", {"index.html": '<a href="/rr/nope/">h</a>'})
    assert cli.main(["gate", "--out", str(ok)]) == 0
    assert cli.main(["gate", "--out", str(bad), "--json"]) == 1
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["broken"]
    assert cli.main(["gate", "--out", str(tmp_path / "none")]) == 2
