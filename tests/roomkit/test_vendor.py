"""The room's core as another codebase carries it: copied, pinned, checked.

The proof that matters: a copy imported under another package name renders
the same bytes as roomkit itself, so a host application page and a roomkit page cannot
disagree about the room.
"""

from __future__ import annotations

import json
import sys

import pytest

from roomkit import cli
from roomkit import vendor as Vn

PIN = "0" * 40


@pytest.fixture
def copy(tmp_path):
    dest = tmp_path / "room_copy"
    Vn.write(dest, PIN)
    sys.path.insert(0, str(tmp_path))
    yield dest
    sys.path.remove(str(tmp_path))
    for name in [n for n in sys.modules if n.split(".")[0] == "room_copy"]:
        del sys.modules[name]


def test_write_copies_the_core_and_pins_every_file(copy):
    pin = json.loads((copy / Vn.PIN).read_text())
    assert pin["commit"] == PIN and set(pin["files"]) == set(Vn.core())
    assert "templates/room/base.html" in pin["files"] and "packs/pack.schema.json" in pin["files"]
    assert not any(p.startswith(("cli", "build", "parity", "vendor")) for p in pin["files"])


def test_check_is_current_after_write_and_names_every_kind_of_drift(copy, monkeypatch):
    assert Vn.check(copy)["current"]
    (copy / "templates/room/404.html").write_text("edited in the copy")
    (copy / "color.py").unlink()
    st = Vn.check(copy)
    assert st["modified"] == ["templates/room/404.html"] and st["missing"] == ["color.py"] and not st["current"]
    real = Vn.core()
    monkeypatch.setattr(Vn, "core", lambda src=Vn.ROOT: {**real, "view.py": b"# moved on upstream\n"})
    assert Vn.check(copy)["behind"] == ["view.py"]


def test_files_outside_the_core_are_left_alone(copy):
    (copy / "packs" / "tenant-a").mkdir(parents=True)
    (copy / "packs" / "tenant-a" / "pack.json").write_text("{}")
    assert Vn.check(copy)["current"]
    Vn.write(copy, PIN)
    assert (copy / "packs" / "tenant-a" / "pack.json").read_text() == "{}"


def test_write_refuses_while_the_core_has_uncommitted_changes(monkeypatch):
    monkeypatch.setattr(Vn, "_git", lambda *a: " M roomkit/view.py" if a[0] == "status" else "abc")
    with pytest.raises(Vn.VendorError, match="uncommitted changes"):
        Vn.source_commit()


def test_vendor_check_cli_exits_1_on_drift_and_speaks_json(copy, capsys):
    assert cli.main(["vendor", "check", "--to", str(copy), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["current"] is True
    (copy / "room.py").write_text("# edited\n")
    assert cli.main(["vendor", "check", "--to", str(copy)]) == 1
    assert "DRIFTED" in capsys.readouterr().out
    assert cli.main(["vendor", "check", "--to", str(copy.parent / "nowhere")]) == 2


def test_the_core_imports_nothing_outside_itself():
    import ast
    for rel in Vn.CORE_MODULES:
        tree = ast.parse((Vn.ROOT / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert not node.module.startswith("scripts"), (rel, node.module)
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("scripts") for a in node.names), rel
