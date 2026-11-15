"""The publish scripts' progress bars (publish/bar.py) and verify_served's chunks.

The bar is a filter: it must read rsync's own counter, never fail a publish, and keep
a log short. verify_served is driven against a stand-in host (ssh runs the chunk
locally, curl serves a local tree) so a dropped chunk and a changed file are real.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

from roomkit.publish import bar as B

PUBLISH = Path(__file__).resolve().parents[2] / "roomkit" / "publish"


def _rsync_out(total: int, step: int = 1) -> bytes:
    """rsync --info=progress2 as a pipe sees it: one \\r-redrawn line per file."""
    recs = [f"      1,024 {i * 100 // total}%  1.00MB/s  0:00:00 (xfr#{i}, to-chk={total - i}/{total})"
            for i in range(0, total + 1, step)]
    return ("\r".join(recs) + "\n").encode()


def test_the_rsync_bar_reads_files_left_and_ends_full():
    out = io.StringIO()
    B.rsync("1/3 assets", io.BytesIO(_rsync_out(40)), out, tty=True)
    last = out.getvalue().split("\r")[-1]
    assert "40/40 100%" in last and last.endswith("\n")


def test_off_a_terminal_the_bar_prints_at_each_tenth_not_each_file():
    out = io.StringIO()
    B.rsync("2/3 pages", io.BytesIO(_rsync_out(2000)), out, tty=False)
    lines = out.getvalue().splitlines()
    assert len(lines) == 11 and lines[0].endswith("0/2000   0%") and lines[-1].endswith("2000/2000 100%")


def test_nothing_to_send_still_says_so():
    out = io.StringIO()
    B.rsync("3/3 lock", io.BytesIO(b""), out, tty=False)
    assert out.getvalue().strip().endswith("0/0   0%")


def test_count_continues_across_chunks_and_keeps_the_lines():
    out, tee = io.StringIO(), io.BytesIO()
    n = B.count("verify", 5, io.BytesIO(b"a.html h1\nb.html h2\n"), start=3, tee=tee, out=out, tty=True)
    assert n == 5 and "5/5 100%" in out.getvalue() and tee.getvalue() == b"a.html h1\nb.html h2\n"


def test_the_bar_exits_0_even_on_input_it_does_not_understand():
    r = subprocess.run([sys.executable, str(PUBLISH / "bar.py"), "rsync", "x"], input=b"\xff\xfe garbage\r\n",
                       capture_output=True, check=False)
    assert r.returncode == 0


def _host(tmp_path: Path, files: dict[str, bytes], drop_first: bool = False) -> tuple[Path, Path]:
    """A served tree, and a bin/ whose ssh runs the chunk here and whose curl serves the tree."""
    served, bin_ = tmp_path / "served", tmp_path / "bin"
    for p, b in files.items():
        (served / p).parent.mkdir(parents=True, exist_ok=True)
        (served / p).write_bytes(b)
    bin_.mkdir()
    calls = tmp_path / "ssh-calls"
    # The first call can come back empty, as a dropped connection does.
    drop = f'n=$(cat "{calls}" 2>/dev/null || echo 0); echo $((n+1)) > "{calls}"; [ "$n" = 0 ] && exit 255\n' \
        if drop_first else ""
    (bin_ / "ssh").write_text(f'#!/bin/bash\n{drop}shift; exec "$@"\n')
    (bin_ / "curl").write_text(f'#!/bin/bash\nu="${{@: -1}}"\ncase "$u" in *ipify*) echo 127.0.0.1; exit;; esac\n'
                               f'p="${{u#*://*/library/}}"; cat "{served}/$p" 2>/dev/null\n')
    for f in ("ssh", "curl"):
        (bin_ / f).chmod(0o755)
    return served, bin_


def _verify(tmp_path: Path, bin_: Path, lock: dict, chunk: int = 2) -> subprocess.CompletedProcess:
    (tmp_path / "lock.json").write_text(json.dumps({"files": lock}))
    cmd = (f'PATH="{bin_}:$PATH"; VERIFY_CHUNK={chunk}; source "{PUBLISH / "upload.sh"}"; '
           f'verify_served "{tmp_path / "lock.json"}" host example.org /library/ "{sys.executable}" http')
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=False)


FILES = {f"r{i}/index.html": f"page {i}".encode() for i in range(5)}
LOCK = {p: hashlib.sha256(b).hexdigest() for p, b in FILES.items()}


def test_verify_runs_in_chunks_and_passes_when_every_file_matches(tmp_path):
    _, bin_ = _host(tmp_path, FILES)
    r = _verify(tmp_path, bin_, LOCK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "5/5 served files match the lock" in r.stdout and "verify" in r.stdout


def test_a_dropped_chunk_is_tried_once_more_not_the_whole_run(tmp_path):
    _, bin_ = _host(tmp_path, FILES, drop_first=True)
    r = _verify(tmp_path, bin_, LOCK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "chunk 00000 came back short; trying it once more" in r.stdout
    assert int((tmp_path / "ssh-calls").read_text()) == 4  # 3 chunks of 2, the first twice


def test_a_changed_file_still_fails_verify(tmp_path):
    served, bin_ = _host(tmp_path, FILES)
    (served / "r3/index.html").write_bytes(b"changed")
    r = _verify(tmp_path, bin_, LOCK)
    assert r.returncode == 1 and "4/5 served files match the lock" in r.stdout and "DIFFERS: r3/index.html" in r.stdout
