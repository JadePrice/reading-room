"""publish/room-remove.sh, the step every publish script uses to drop the pages a build no
longer has: it cannot reach outside the room (split from sites/test_publish_scripts.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path

PUBLISH = Path(__file__).resolve().parents[2] / "roomkit" / "publish"


def test_removal_stays_inside_the_room(tmp_path):
    room, outside = tmp_path / "room", tmp_path / "outside"
    for p in ("gone/index.html", "kept/index.html", "assets/old.abc123def456.css", "assets/new.0123456789ab.css"):
        (room / p).parent.mkdir(parents=True, exist_ok=True)
        (room / p).write_text("x")
    outside.mkdir()
    (outside / "victim").write_text("x")
    listing = "\n".join(["gone/index.html", "../outside/victim", str(outside / "victim"),
                         "kept/../../outside/victim", "#ASSETS-KEEP assets/new.0123456789ab.css", ""])
    subprocess.run(["bash", str(PUBLISH / "room-remove.sh")], cwd=room, input=listing,
                   text=True, check=True, capture_output=True)
    left = sorted(str(p.relative_to(room)) for p in room.rglob("*") if p.is_file())
    assert left == ["assets/new.0123456789ab.css", "kept/index.html"]
    assert (outside / "victim").exists()
