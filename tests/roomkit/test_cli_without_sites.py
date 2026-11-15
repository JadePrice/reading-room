"""roomkit without its sites layer (roomkit/sites/), as the public mirror ships it.

Each case runs the CLI in a subprocess where `roomkit.sites` cannot be imported,
and checks that the core commands still work and that the sites layer's commands are gone.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "roomkit" / "golden" / "manifest.json"
DEFAULT_PACK = REPO / "roomkit" / "packs" / "default"

RUN = """
import sys
sys.modules["roomkit.sites"] = None  # the package is absent
from roomkit import cli
assert cli.SX is None
raise SystemExit(cli.main(sys.argv[1:]))
"""


def _cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", RUN, *argv], cwd=REPO, capture_output=True, text=True,
                          env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}, timeout=300, check=False)


def test_help_lists_no_sites_command():
    r = _cli("--help")
    assert r.returncode == 0, r.stderr
    choices = r.stdout.split("{", 1)[1].split("}", 1)[0].split(",")
    assert "parity" not in choices and {"build", "check", "status", "gate", "pack"} <= set(choices)
    r = _cli("pack", "theme", "--help")
    assert r.returncode == 2 and "invalid choice" in r.stderr


def test_build_check_status_and_gate_work_without_the_sites_layer(tmp_path):
    out = tmp_path / "room"
    common = ("--manifest", str(GOLDEN), "--out", str(out), "--site-pack", str(DEFAULT_PACK))
    r = _cli("build", *common, "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["built"] is True
    assert "dropped-feature check is skipped" in r.stderr
    r = _cli("check", *common, "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["current"] is True
    r = _cli("status", *common, "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["stage"] == "current"
    # The golden manifest's file links point at the site's own file route, outside the room,
    # so the gate reports them (exit 1); it runs, and says the same as with the sites layer.
    r = _cli("gate", "--out", str(out), "--json")
    assert r.returncode in (0, 1), r.stderr
    from roomkit import cli
    assert cli.main(["gate", "--out", str(out), "--json"]) == r.returncode


def test_status_without_a_manifest_names_only_the_core_form():
    r = _cli("status", "--json")
    assert r.returncode == 2 and "status needs --manifest and --out" in r.stderr and "--matrix" not in r.stderr
