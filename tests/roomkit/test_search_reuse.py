"""Keeping the published Pagefind index when it answers the same query
(build.adopt_search).

Pagefind 1.5.2 is not byte-reproducible (search.py): the same corpus gives
differently-named filter files and a different pagefind-entry.json every run.
Without this, every publish of an unchanged room is a git diff, which is how a
reviewable publish becomes noise nobody reads. These tests pin the rule the
lock already carries: same `search` (input hash and binary version) and an index
that hashes to its own lock means the two indexes are interchangeable.

The tests build locks and trees by hand: this is a function over a `files` dict
and a directory, so it needs neither the pinned binary nor a real render.
"""

from __future__ import annotations

import json
from pathlib import Path

from roomkit import build as B
from roomkit import search as S

SEARCH = {"input": "a" * 64, "pagefind": "1.5.2"}
OTHER = {"input": "b" * 64, "pagefind": "1.5.2"}


def _lock(search: dict, files: dict[str, str]) -> bytes:
    return (json.dumps({"search": search, "files": files}, indent=1, sort_keys=True) + "\n").encode()


def _published(tmp_path: Path, search: dict = SEARCH, index: dict[str, bytes] | None = None) -> Path:
    """A room on disk: its lock, and the index that lock describes."""
    out = tmp_path / "room"
    index = {"pagefind/pagefind-entry.json": b'{"en": "en_67a0b144df"}',
             "pagefind/filter/en_3b21ae1.pf_filter": b"filter-one",
             "pagefind/fragment/en_1018a17.pf_fragment": b"fragment-one",
             "index.html": b"<html>a record</html>"} if index is None else index
    for p, b in index.items():
        (out / p).parent.mkdir(parents=True, exist_ok=True)
        (out / p).write_bytes(b)
    (out / B.LOCK).write_bytes(_lock(search, {p: B.sha256(b) for p, b in index.items()}))
    return out


def _built(search: dict = SEARCH, index: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """What render hands back: a fresh index, with Pagefind's new names."""
    index = {"pagefind/pagefind-entry.json": b'{"en": "en_74fce39478"}',
             "pagefind/filter/en_a22accf.pf_filter": b"filter-two",
             "pagefind/fragment/en_1018a17.pf_fragment": b"fragment-one",
             "index.html": b"<html>a record</html>"} if index is None else index
    files = dict(index)
    files[B.LOCK] = _lock(search, {p: B.sha256(b) for p, b in index.items()})
    return files


def test_adopts_the_published_index_when_the_query_is_the_same(tmp_path: Path) -> None:
    out = _published(tmp_path)
    files = _built()

    assert B.adopt_search(files, out) is True

    shipped = {p for p in files if p.startswith(S.OUT + "/")}
    assert shipped == {"pagefind/pagefind-entry.json",
                       "pagefind/filter/en_3b21ae1.pf_filter",
                       "pagefind/fragment/en_1018a17.pf_fragment"}
    assert files["pagefind/filter/en_3b21ae1.pf_filter"] == b"filter-one"
    assert json.loads(files[B.LOCK])["files"]["pagefind/pagefind-entry.json"] == \
        json.loads((out / B.LOCK).read_bytes())["files"]["pagefind/pagefind-entry.json"]


def test_a_second_publish_of_an_unchanged_room_changes_nothing(tmp_path: Path) -> None:
    """The point of the exercise: compare() comes back empty, so git does too."""
    out = _published(tmp_path)
    files = _built()

    B.adopt_search(files, out)

    assert B.compare(files, out) == {"missing": [], "stale": [], "extra": []}


def test_without_adoption_the_same_room_looks_changed(tmp_path: Path) -> None:
    """Guards the test above: a rebuilt index alone does report a change."""
    out = _published(tmp_path)
    files = _built()

    assert B.compare(files, out)["missing"] == []
    assert files["pagefind/pagefind-entry.json"] != (out / "pagefind/pagefind-entry.json").read_bytes()


def test_refuses_when_the_corpus_changed(tmp_path: Path) -> None:
    """A different input hash means a different index: ship the new one."""
    out = _published(tmp_path, search=OTHER)
    files = _built()

    assert B.adopt_search(files, out) is False
    assert "pagefind/filter/en_a22accf.pf_filter" in files


def test_refuses_when_the_published_index_does_not_hash_to_its_lock(tmp_path: Path) -> None:
    """A damaged index is never adopted: the lock would then describe bytes that are not there."""
    out = _published(tmp_path)
    (out / "pagefind/fragment/en_1018a17.pf_fragment").write_bytes(b"tampered")
    files = _built()

    assert B.adopt_search(files, out) is False
    assert "pagefind/filter/en_a22accf.pf_filter" in files


def test_refuses_when_there_is_no_published_room(tmp_path: Path) -> None:
    """First publish: nothing to adopt, the built index ships."""
    files = _built()

    assert B.adopt_search(files, tmp_path / "absent") is False
    assert "pagefind/filter/en_a22accf.pf_filter" in files


def test_refuses_the_stand_in_indexer(tmp_path: Path) -> None:
    """The stand-in is byte-reproducible, so there is nothing to smooth over."""
    out = _published(tmp_path)
    files = _built(search={"input": SEARCH["input"], "pagefind": "stand-in"})

    assert B.adopt_search(files, out) is False


def test_refuses_when_the_room_has_no_search(tmp_path: Path) -> None:
    out = _published(tmp_path)
    files = {"index.html": b"<html>a record</html>"}
    files[B.LOCK] = _lock({}, {"index.html": B.sha256(files["index.html"])})

    assert B.adopt_search(files, out) is False


def test_leaves_everything_else_alone(tmp_path: Path) -> None:
    """Only the index and its lock entries move; a record page is not rewritten."""
    out = _published(tmp_path)
    files = _built(index={"pagefind/pagefind-entry.json": b'{"en": "en_74fce39478"}',
                          "index.html": b"<html>a record, edited since</html>"})

    assert B.adopt_search(files, out) is True
    assert files["index.html"] == b"<html>a record, edited since</html>"
    assert json.loads(files[B.LOCK])["files"]["index.html"] == \
        B.sha256(b"<html>a record, edited since</html>")
