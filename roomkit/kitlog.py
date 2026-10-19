"""One run log per kit invocation, on stderr and optionally on disk.

Why this exists: across 51,745 lines under `scripts/` there were 1,346 `print(`
calls and 38 logging calls, all 38 of them in `archive_org/`. For a human at a
terminal that is correct -- a kit's printed output *is* its product, and nothing
here changes it. It stops being correct the moment a kit runs unattended: inside
the commit gate, behind `dropkit serve`, or in a pipeline whose stdout someone
piped to `tail`. Then the only record of what happened is a scrollback that no
longer exists, and a failed run is indistinguishable from one that never ran.

Three rules, each load-bearing:

1. **Never stdout.** `status --json` is a contract with whatever is parsing it,
   and a single log line on stdout breaks that contract silently -- the JSON
   still looks like JSON right up until it does not parse. Logs go to stderr,
   or to a file, never to stdout. The test suite asserts this rather than
   trusting it.

2. **Quiet on a terminal by default.** stderr carries WARNING and worse; the
   file, when there is one, carries everything. Adding a log line must not
   change what an existing user sees, or the next person will route around the
   logger to keep their output clean and we are back to print.

3. **Never configure the root logger.** `logging.basicConfig` is a global write
   from library code: one kit imported by another would decide logging for the
   whole process. Each kit gets a named logger with its own handlers, and
   `propagate` is off so it cannot reach a root handler somebody else installed.

Wiring, in a kit's `main()` and nowhere else::

    args = build_parser().parse_args(argv)
    log = kitlog.configure("dropkit", verbose=getattr(args, "verbose", 0))
    with kitlog.run(log, getattr(args, "command", None), argv):
        return args.func(args)

Subcommands stay print-only. The run record is start, finish, duration, exit
code and traceback -- enough to tell a crashed run from an absent one, which is
the question that could not be answered before.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
import uuid
from pathlib import Path

#: Env var naming a directory for per-kit log files. Unset means stderr only:
#: a kit must never create files somewhere the caller did not ask for.
LOG_DIR_VAR = "KITLOG_DIR"

#: Env var overriding the stderr level (e.g. KITLOG_LEVEL=INFO). `-v` also does.
LEVEL_VAR = "KITLOG_LEVEL"

#: Identifies one invocation. Concurrent runs interleave in a shared file, and
#: without this there is no way to tell one run's lines from another's.
RUN_ID = uuid.uuid4().hex[:8]

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(run_id)s] %(message)s"


class _RunIdFilter(logging.Filter):
    """Put RUN_ID on every record so the format string can name it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = RUN_ID
        return True


def _level_from_env(default: int) -> int:
    raw = os.environ.get(LEVEL_VAR, "").strip().upper()
    if not raw:
        return default
    resolved = logging.getLevelNamesMapping().get(raw)
    return resolved if resolved is not None else default


def configure(
    kit: str,
    *,
    verbose: int = 0,
    log_dir: Path | str | None = None,
    stream=None,
) -> logging.Logger:
    """Return the logger for `kit`, configured once.

    Calling this twice returns the same logger without stacking a second copy
    of every handler, because a kit that dispatches to another kit's `main()`
    would otherwise duplicate every line.

    `verbose` is a count: 0 warns, 1 informs, 2 debugs. `log_dir` defaults to
    $KITLOG_DIR and writing is skipped entirely when neither is set.
    """
    logger = logging.getLogger(f"kit.{kit}")
    logger.setLevel(logging.DEBUG)  # handlers do the filtering
    logger.propagate = False  # rule 3: never reach someone else's root handler

    if getattr(logger, "_kitlog_configured", False):
        return logger

    formatter = logging.Formatter(_FORMAT)
    run_id = _RunIdFilter()

    stderr_level = {0: logging.WARNING, 1: logging.INFO}.get(verbose, logging.DEBUG)
    # rule 1: the stream is stderr, and a caller may only substitute another
    # explicit stream (the tests do). stdout is never the default.
    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    handler.setLevel(_level_from_env(stderr_level))
    handler.setFormatter(formatter)
    handler.addFilter(run_id)
    logger.addHandler(handler)

    target = log_dir if log_dir is not None else os.environ.get(LOG_DIR_VAR) or None
    if target:
        path = Path(target).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path / f"{kit}.log", encoding="utf-8")
        except OSError as exc:
            # An unwritable log dir must not take the kit down with it. Say so
            # once on stderr and carry on: the run is the point, not the log.
            logger.warning("kitlog: cannot write to %s (%s); stderr only", path, exc)
        else:
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(run_id)
            logger.addHandler(file_handler)

    logger._kitlog_configured = True  # type: ignore[attr-defined]
    return logger


@contextlib.contextmanager
def run(logger: logging.Logger, command: str | None, argv=None):
    """Bracket one invocation: what was asked, how it ended, how long it took.

    Re-raises everything. This records runs; it does not handle errors, and a
    kit's own `except` clauses in `main()` keep deciding exit codes.
    """
    label = command or "(no command)"
    # argv is None under `python -m`, and "(sys.argv)" in a log is useless to
    # whoever is reading it later. Record the actual arguments.
    logger.info("start %s argv=%s", label, list(argv) if argv is not None else sys.argv[1:])
    started = time.monotonic()
    try:
        yield
    except SystemExit as exc:
        # argparse leaves this way: `--help` and a usage error are both
        # SystemExit, and `--help` is a successful run. Logging it as a crash
        # put an ERROR and a traceback on stderr for every `--help` on every
        # kit, which is how a log earns itself an unread reputation.
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
        if code:
            logger.warning("exit %s with code %s after %.2fs", label, code, time.monotonic() - started)
        else:
            logger.info("done %s in %.2fs", label, time.monotonic() - started)
        raise
    except KeyboardInterrupt:
        logger.warning("interrupted %s after %.2fs", label, time.monotonic() - started)
        raise
    except BaseException:
        logger.exception(
            "fail %s after %.2fs",
            label, time.monotonic() - started,
        )
        raise
    else:
        logger.info("done %s in %.2fs", label, time.monotonic() - started)


def command_of(argv=None, value_flags: tuple[str, ...] = ()) -> str | None:
    """The subcommand in `argv`: its first token that is neither a flag nor a
    flag's value.

    Read from argv rather than from parsed args deliberately. The seven kits
    name their subcommand `command` in five parsers and `cmd` in two, build the
    parser in `main()` in four cases and in a `build_parser()` in three, and one
    dispatches inline with no single call site. Reading argv is the one thing
    that works identically for all of them, and it still works when parsing
    itself is what failed.

    `value_flags` names the kit's own top-level flags that consume the token
    after them. Without it `iakit --root . status` reports its command as "."
    -- a caller has to say which flags eat a value, because argv alone cannot
    tell a flag's value from a subcommand.
    """
    items = list(sys.argv[1:] if argv is None else argv)
    skip = False
    for item in items:
        if skip:
            skip = False
            continue
        if item.startswith("-"):
            skip = item in value_flags  # `--root .` eats the next token
            continue
        return item
    return None


def add_logging_flags(parser) -> None:
    """Add `-v/--verbose` to a kit's top-level parser. Repeatable."""
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Log to stderr: -v for info, -vv for debug. Logs never go to stdout.",
    )
