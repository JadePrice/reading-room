"""A progress bar for the publish scripts' long steps, as a filter on a command's output.

    rsync --info=progress2 ... | python bar.py rsync LABEL
        reads rsync's to-chk=M/T counter (files left to check / total) and draws T-M of T.
    COMMAND | python bar.py count LABEL TOTAL [--start N] [--tee FILE]
        one output line is one item done (a verified file); --start continues a bar
        across chunks; --tee keeps the lines.

On a terminal the bar is redrawn in place; anywhere else (a log, CI) it prints at every
10%, so a log does not fill with bars. Exit 0 always: the command's own exit status is
the caller's (bash PIPESTATUS), a bar never fails a publish.
"""

from __future__ import annotations

import argparse
import re
import sys

WIDTH = 30
TO_CHK = re.compile(rb"to-chk=(\d+)/(\d+)")


class Bar:
    def __init__(self, label: str, total: int, out=sys.stdout, tty: bool | None = None):
        self.label, self.total, self.out = label, max(total, 0), out
        self.tty = out.isatty() if tty is None else tty
        self.shown_tenth = -1
        self.open = False

    def line(self, n: int) -> str:
        total = max(self.total, 1)
        n = min(n, total)
        fill = n * WIDTH // total
        return f"   {self.label:<14} [{'#' * fill}{'-' * (WIDTH - fill)}] {n}/{self.total} {n * 100 // total:3d}%"

    def draw(self, n: int) -> None:
        if self.tty:
            self.out.write("\r" + self.line(n))
            self.open = True
        else:
            tenth = min(n, max(self.total, 1)) * 10 // max(self.total, 1)
            if tenth == self.shown_tenth:
                return
            self.shown_tenth = tenth
            self.out.write(self.line(n) + "\n")
        self.out.flush()

    def end(self) -> None:
        if self.open:
            self.out.write("\n")
            self.out.flush()
            self.open = False


def _records(stream):
    """Byte records split on \\r or \\n as they arrive (rsync redraws with \\r)."""
    buf = b""
    while True:
        chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        yield from parts
    if buf:
        yield buf


def rsync(label: str, stream, out=sys.stdout, tty: bool | None = None) -> None:
    bar = None
    for rec in _records(stream):
        m = TO_CHK.search(rec)
        if m:
            left, total = int(m.group(1)), int(m.group(2))
            bar = bar or Bar(label, total, out, tty)
            bar.total = total  # rsync can grow the total while it scans
            bar.draw(total - left)
    if bar is None:
        Bar(label, 0, out, tty).draw(0)  # nothing to send still says so
    else:
        bar.draw(bar.total)
        bar.end()


def count(label: str, total: int, stream, start: int = 0, tee=None, out=sys.stdout,
          tty: bool | None = None) -> int:
    bar = Bar(label, total, out, tty)
    n = start
    bar.draw(n)
    for rec in _records(stream):
        if not rec.strip():
            continue
        if tee is not None:
            tee.write(rec + b"\n")
        n += 1
        bar.draw(n)
    if n >= total:
        bar.end()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("rsync")
    r.add_argument("label")
    c = sub.add_parser("count")
    c.add_argument("label")
    c.add_argument("total", type=int)
    c.add_argument("--start", type=int, default=0)
    c.add_argument("--tee")
    a = ap.parse_args(argv)
    stdin = sys.stdin.buffer
    if a.mode == "rsync":
        rsync(a.label, stdin)
    else:
        tee = open(a.tee, "ab") if a.tee else None  # noqa: SIM115 - closed in the finally below
        try:
            count(a.label, a.total, stdin, a.start, tee)
        finally:
            if tee:
                tee.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
