"""Roadmap P2: a publish uploads assets and data first, HTML next, the lock last.

publish/upload.sh is driven against a local directory through a stand-in
`rsync` that runs the real one and records what the destination holds after
each pass, so the test reads the order from what landed, not from arguments.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit.manifest import parse
from tests.roomkit.test_roomkit import _manifest

UPLOAD = Path(__file__).resolve().parents[2] / "roomkit" / "publish" / "upload.sh"
RSYNC = shutil.which("rsync")


@pytest.mark.skipif(RSYNC is None, reason="no rsync")
def test_assets_land_before_the_pages_that_name_them_and_the_lock_lands_last(tmp_path):
    src, dest, bin_, log = tmp_path / "room", tmp_path / "served", tmp_path / "bin", tmp_path / "passes.log"
    B.write(B.render(parse(_manifest())), src)
    dest.mkdir()
    bin_.mkdir()
    (bin_ / "rsync").write_text(f'#!/bin/bash\n"{RSYNC}" "$@" || exit\n'
                                f'echo "== pass" >> "{log}"\n'
                                f'(cd "{dest}" && find . -type f | sed "s|^./||" | sort) >> "{log}"\n')
    (bin_ / "rsync").chmod(0o755)
    subprocess.run(["bash", "-c", f'PATH="{bin_}:$PATH"; source "{UPLOAD}"; upload_room "{src}/" "{dest}/"'],
                   check=True, capture_output=True)

    passes = [p.split() for p in log.read_text().split("== pass")[1:]]
    assert len(passes) == 3
    first, second, third = (set(p) for p in passes)
    built = {str(p.relative_to(src)) for p in src.rglob("*") if p.is_file()}
    html = {p for p in built if p.endswith(".html")}
    assert html and not (first & html) and "room.lock.json" not in first
    assert {p for p in built if p.startswith("assets/")} <= first   # every asset before any page
    assert html <= second and "room.lock.json" not in second
    assert third == built                                          # the lock last, and nothing missing
    assert json.loads((dest / "room.lock.json").read_text()) == json.loads((src / "room.lock.json").read_text())


SNAPSHOT = UPLOAD.with_name("room-snapshot.sh")


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.skipif(RSYNC is None, reason="no rsync")
def test_a_publish_can_be_rolled_back_to_the_room_it_replaced(tmp_path):
    """Roadmap P3: snapshot before the upload, publish over it (removing a record),
    restore: the served tree is the old room again, byte for byte."""
    old, new = _manifest(), _manifest()
    new["documents"][0]["title"] = "A changed title"
    new["documents"].pop()                       # a record leaves the room
    a, b, live, prev = (tmp_path / n for n in ("a", "b", "live", "home/prev/room"))
    B.write(B.render(parse(old)), a)
    B.write(B.render(parse(new)), b)
    sh = lambda *args: subprocess.run(["bash", *map(str, args)], check=True, capture_output=True, text=True)
    sh("-c", f'source "{UPLOAD}"; upload_room "{a}/" "{live}/"')
    served_a = _tree(live)

    sh(SNAPSHOT, "snapshot", live, prev)
    sh("-c", f'source "{UPLOAD}"; upload_room "{b}/" "{live}/"')
    gone = set(served_a) - set(_tree(b))
    assert gone
    for p in gone:                               # the publish script's removal step
        (live / p).unlink()
    assert _tree(live) == _tree(b) and _tree(prev) == served_a   # the upload left the snapshot alone

    sh(SNAPSHOT, "restore", live, prev)
    assert _tree(live) == served_a


def test_restore_refuses_without_a_snapshot(tmp_path):
    r = subprocess.run(["bash", str(SNAPSHOT), "restore", str(tmp_path / "live"), str(tmp_path / "none")],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "no snapshot" in r.stderr
