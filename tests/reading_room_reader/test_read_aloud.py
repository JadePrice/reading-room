"""Static promises of the read-aloud pilot. No browser needed.

rr-read-aloud.js is site code, not engine: it ships beside the vendored copy,
never inside it. These are the things that must hold so it stays CSP-clean,
egress-free, and honest about what it can read.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from tests.reading_room_reader.conftest import ENGINE

ALOUD = ENGINE / "read-aloud" / "rr-read-aloud.js"
SPEC = ENGINE / "read-aloud" / "README.md"

SRC = ALOUD.read_text()


def test_spec_exists_beside_the_prototype():
    assert SPEC.is_file()
    assert "speechSynthesis" in SPEC.read_text()


def test_no_inline_handlers_or_eval():
    assert "setAttribute('on" not in SRC
    assert 'setAttribute("on' not in SRC
    assert not re.search(r"(^|[^\w$])eval\s*\(", SRC)


def test_no_remote_urls():
    # Same-origin pages.json only; no CDN, no cloud synthesis endpoint.
    assert "http://" not in SRC and "https://" not in SRC


def test_speech_is_user_gated_and_cancellable():
    assert "speechSynthesis" in SRC
    assert "data-read-aloud" in SRC  # opt-in per mount, off by default
    assert SRC.count("cancel()") >= 2  # pagechange + stop paths
    assert "pagehide" in SRC  # no ghost audio after navigation


def test_stays_es5_like_the_engine():
    assert not re.search(r"(^|[^\w$])(const|let)\s+", SRC)
    assert "=>" not in SRC


def test_chunking_is_lossless_and_bounded():
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    harness = r"""
global.window = {};
global.document = { readyState: "complete",
  querySelectorAll: function(){ return []; }, addEventListener: function(){} };
require(process.argv[1]);
var A = global.window.RRReadAloud;
var ocr = "THE BOARD OF SUPERVISORS  will hold a public hearing\non Tuesday."
  + " Item 12: short. "
  + "This is a very long sentence that keeps going past two hundred characters"
  + " so the chunker must hold it whole because chunks never split mid-sentence"
  + " until the period at the very end of the sentence here.";
var chunks = A._chunkText(ocr);
if (chunks.join(" ") !== A._cleanText(ocr)) throw new Error("chunk loss");
var longest = Math.max.apply(null, chunks.map(function(c){ return c.length; }));
if (longest > 220) throw new Error("chunk too long: " + longest);
if (JSON.stringify(A._chunkText("   ")) !== "[]") throw new Error("empty input");
console.log("chunks=" + chunks.length + " longest=" + longest);
"""
    run = subprocess.run(
        [node, "-e", harness, str(ALOUD)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr


def _run_node_harness(body):
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    harness = (
        "global.window = {};\n"
        "global.document = { readyState: 'complete',\n"
        "  querySelectorAll: function(){ return []; }, addEventListener: function(){} };\n"
        "require(process.argv[1]);\n"
        "var A = global.window.RRReadAloud;\n" + body
    )
    run = subprocess.run(
        [node, "-e", harness, str(ALOUD)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr


def test_hyphenated_linebreaks_rejoined():
    # IA BookReader parity: "hear-\ning" must speak as "hearing", and the
    # lossless invariant must still hold on hyphenated input.
    _run_node_harness(
        "var ocr = 'The hear-\\ning will resume. Vigilancia con lec-\\ntor.';\n"
        "var flat = A._cleanText(ocr);\n"
        "if (flat !== 'The hearing will resume. Vigilancia con lector.')\n"
        "  throw new Error('hyphen not rejoined: ' + flat);\n"
        "var chunks = A._chunkText(ocr);\n"
        "if (chunks.join(' ') !== flat) throw new Error('chunk loss on hyphenated input');\n"
        "console.log('hyphen ok chunks=' + chunks.length);\n"
    )


def test_es_voice_pick_prefers_spanish():
    # Translation-AI interplay: ES machine text must get an ES voice when one
    # exists, else fall back to null (caller then uses the same voice).
    _run_node_harness(
        "var voices = [{name:'Alex',lang:'en-US'},{name:'Mónica',lang:'es-ES'}];\n"
        "var v = A._pickVoice(voices, 'es');\n"
        "if (!v || v.name !== 'Mónica') throw new Error('es voice not picked');\n"
        "var v2 = A._pickVoice(voices, 'en');\n"
        "if (!v2 || v2.name !== 'Alex') throw new Error('en voice not picked');\n"
        "var v3 = A._pickVoice([{name:'Alex',lang:'en-US'}], 'es');\n"
        "if (v3 !== null) throw new Error('expected null with no es voice');\n"
        "console.log('voice pick ok');\n"
    )


def test_chrome_watchdog_present_and_cleared():
    # chromium #679437: pause/resume every 14s while speaking; timer cleared
    # on every stop path so no ghost interval survives the panel.
    assert "setInterval" in SRC
    assert "14000" in SRC
    assert SRC.count("clearInterval") >= 2  # stop() + play() re-arm
    assert "speechSynthesis.pause()" in SRC
    assert "speechSynthesis.resume()" in SRC


def test_voices_listener_never_clobbers():
    # addEventListener only — no handler-property assignment, so co-located
    # site code keeps its own voices listener.
    assert ".onvoiceschanged =" not in SRC
    assert "addEventListener('voiceschanged'" in SRC


def test_machine_translation_is_announced():
    # Provider may serve {text, isMachine}; spoken MT must be labeled.
    assert "isMachine" in SRC
    assert "'machine translation, '" in SRC or '"machine translation, "' in SRC
