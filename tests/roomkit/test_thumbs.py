"""Card thumbnails the room serves itself (manifest index.thumb) and parity.thumbnails.

The room copies each card's thumbnail into its own tree, so a card does not
depend on a route only the site's server answers (matrix row index-thumbnails).
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import search as S
from roomkit import thumb_parity as TP
from roomkit.manifest import THUMB_MAX, parse
from tests.roomkit.test_roomkit import _dd_manifest

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg body" * 10
PNG = b"\x89PNG\r\n\x1a\n" + b"png body"


def _thumb(raw: bytes = JPEG, mime: str = "image/jpeg", **over) -> dict:
    t = {"mime": mime, "sha256": hashlib.sha256(raw).hexdigest(), "data": base64.b64encode(raw).decode()}
    t.update(over)
    return t


def _with_thumb(thumb: dict | None = None) -> dict:
    data = _dd_manifest()
    ix = data["documents"][0]["index"]
    ix.pop("thumb_url")
    ix["thumb"] = thumb or _thumb()
    return data


def _render(data):
    m = parse(data)
    assert not m.refusals, m.refusals
    return B.render(m, mount="/rr-staging/", noindex=True, indexer=S.stand_in)


# --- the manifest -------------------------------------------------------------

@pytest.mark.parametrize("thumb,reason", [
    ({"mime": "image/jpeg", "data": ""}, "is not {mime, sha256, data} strings"),
    (dict(_thumb(), extra="x"), "is not {mime, sha256, data} strings"),
    (_thumb(mime="image/gif"), "is not one of"),
    (_thumb(data="not base64!"), "is not base64"),
    (_thumb(sha256="0" * 64), "does not hash to"),
    (_thumb(PNG, "image/jpeg"), "is not image/jpeg"),
    (_thumb(b"RIFF\x00\x00\x00\x00WAVE", "image/webp"), "is not image/webp"),
    (_thumb(b"\xff\xd8\xff" + b"x" * THUMB_MAX), "bytes (1 to"),
    (_thumb(b""), "bytes (1 to"),
])
def test_a_thumb_that_is_not_the_image_it_says_is_refused(thumb, reason):
    m = parse(_with_thumb(thumb))
    assert len(m.refusals) == 1 and reason in m.refusals[0][1], m.refusals


def test_a_row_names_its_thumbnail_once():
    data = _with_thumb()
    data["documents"][0]["index"]["thumb_url"] = "https://example.test/t.png"
    assert "both thumb and thumb_url" in parse(data).refusals[0][1]


# --- the build ----------------------------------------------------------------

def test_the_room_serves_its_own_copy_of_the_thumbnail_under_a_content_hash():
    files = _render(_with_thumb())
    name = B.published(files, "assets/thumbs/camera-contract.jpg")
    assert name == f"assets/thumbs/camera-contract.{hashlib.sha256(JPEG).hexdigest()[:12]}.jpg"
    assert files[name] == JPEG and "assets/thumbs/camera-contract.jpg" not in files
    assert f'<img src="/rr-staging/{name}"' in files["index.html"].decode()
    assert json.loads(files["room.lock.json"])["files"][name] == hashlib.sha256(JPEG).hexdigest()
    # Cached for a year like the other hashed assets, because the name changes with the bytes.
    assert "(css|js|json|jpg|png|webp)" in files[".htaccess"].decode()
    assert _render(_with_thumb()) == files


def test_a_room_without_thumbnails_keeps_its_cache_rule_byte_for_byte():
    files = _render(_dd_manifest())
    assert "(css|js|json)$" in files[".htaccess"].decode()
    assert not [p for p in files if p.startswith("assets/thumbs/")]
    # thumb_url (a remote thumbnail) is still the card's src as given.
    assert '<img src="https://example.test/t.png"' in files["index.html"].decode()


def test_check_finds_a_thumbnail_swapped_on_disk(tmp_path):
    files, out = _render(_with_thumb()), tmp_path / "room"
    B.write(files, out)
    assert B.compare(files, out) == {"missing": [], "stale": [], "extra": []}
    swapped = B.published(files, "assets/thumbs/camera-contract.jpg")
    (out / swapped).write_bytes(PNG)
    assert B.compare(files, out)["stale"] == [swapped]


# --- parity.thumbnails --------------------------------------------------------

def _room(tmp_path, data):
    out = tmp_path / "room"
    B.write(_render(data), out)
    return out


def _live(tmp_path, rows) -> object:
    p = tmp_path / "live.tsv"
    p.write_text("#fetched\t2026-10-20T00:00:00Z\n" + "".join("\t".join(r) + "\n" for r in rows))
    return p


JPEG_SHA = hashlib.sha256(JPEG).hexdigest()


def _ok(sha=JPEG_SHA):
    return ["camera-contract", "https://example.test/reading-room/camera-contract/thumb/", "200", "image/jpeg", sha]


NONE = ["site-photo", "-", "-", "-", "-"]


def test_parity_passes_when_each_card_shows_the_live_bytes(tmp_path):
    rep = TP.run(_live(tmp_path, [_ok(), NONE]), _room(tmp_path, _with_thumb()))
    assert rep["ok"] and rep["counts"] == {"same": 1, "none": 1}, rep


@pytest.mark.parametrize("live,data,result", [
    (_ok("0" * 64), _with_thumb(), "differs"),
    (_ok(), _dd_manifest(), "not-copied"),           # the card still points at the live route
    (["camera-contract", "-", "-", "-", "-"], _with_thumb(), "extra"),
    (["camera-contract", "https://x.test/t/", "404", "text/html", "e3"], _with_thumb(), "extra"),
])
def test_parity_names_each_kind_of_difference(tmp_path, live, data, result):
    rep = TP.run(_live(tmp_path, [live, NONE]), _room(tmp_path, data))
    assert not rep["ok"] and [d["result"] for d in rep["differences"]] == [result], rep


def test_a_broken_live_thumbnail_is_explained_not_copied(tmp_path):
    data = _with_thumb()
    data["documents"][0]["index"].pop("thumb")
    rep = TP.run(_live(tmp_path, [["camera-contract", "https://x.test/t/", "404", "text/html", "e3"], NONE]),
                 _room(tmp_path, data))
    assert rep["ok"] and rep["live_broken"] == ["camera-contract"], rep
    assert "live-broken camera-contract" in TP.text(rep)


def test_a_live_thumbnail_the_room_lacks_or_a_card_on_one_side_is_a_difference(tmp_path):
    data = _with_thumb()
    data["documents"][0]["index"].pop("thumb")
    rep = TP.run(_live(tmp_path, [_ok(), ["gone", "-", "-", "-", "-"]]), _room(tmp_path, data))
    assert sorted((d["slug"], d["result"]) for d in rep["differences"]) == [
        ("camera-contract", "missing"), ("gone", "missing-card"), ("site-photo", "extra-card")], rep


def test_the_live_file_is_refused_when_it_is_not_the_fetch_scripts(tmp_path):
    p = tmp_path / "live.tsv"
    p.write_text("camera-contract\t200\n")
    with pytest.raises(TP.ThumbParityError, match="not slug, src"):
        TP.read_live(p)
    p.write_text("#fetched\tx\n")
    with pytest.raises(TP.ThumbParityError, match="no cards"):
        TP.read_live(p)
    p.write_text("a\t-\t-\t-\t-\na\t-\t-\t-\t-\n")
    with pytest.raises(TP.ThumbParityError, match="twice"):
        TP.read_live(p)


def test_the_cli_exits_by_the_result(tmp_path, capsys):
    room = _room(tmp_path, _with_thumb())
    assert cli.main(["parity", "--thumbs", str(_live(tmp_path, [_ok(), NONE])), "--out", str(room)]) == 0
    assert cli.main(["parity", "--thumbs", str(_live(tmp_path, [_ok("0" * 64), NONE])), "--out", str(room)]) == 1
    assert cli.main(["parity", "--thumbs", str(tmp_path / "missing.tsv"), "--out", str(room)]) == 2
    assert "parity.thumbnails DIFFERENT" in capsys.readouterr().out
