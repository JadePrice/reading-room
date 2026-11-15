"""The accessibility toolbar (pack `a11y_toolbar`), the part that holds for any pack: the
switch off ships nothing, the schema refuses what is not ported, and the script keeps the
wp-accessibility plugin's cookies and classes (templates/room/room-a11y.js).

A pack that turns the toolbar on carries the plugin's own stylesheets and font; no pack
roomkit ships does. The tests of a pack that does are the sites layer's
(tests/roomkit/sites/test_a11y_toolbar.py)."""

from __future__ import annotations

import copy

from roomkit import build as B
from roomkit import pack as K
from roomkit import room as R
from tests.roomkit import test_golden as G

FILES = {"css": "plugins/wp-accessibility/a11y.css", "icons_css": "plugins/wp-accessibility/a11y-toolbar.css",
         "icon_font": "plugins/wp-accessibility/a11y.woff2", "contrast_css": "plugins/wp-accessibility/a11y-contrast.css"}
TOOLBAR = {
    "source": {"plugin": "wp-accessibility", "version": "2.4.5", "page": "https://example.org/records/",
               "captured": "2026-11-13"},
    "wpatb": {"responsive": "a11y-non-responsive", "is_rtl": "ltr", "is_right": "default",
              "custom_location": "standard-location", "enable_contrast": "true", "enable_grayscale": "false",
              "enable_fontsize": "true", "contrast": "Toggle High Contrast", "fontsize": "Toggle Font size",
              "custom_fontsize": "0", "factor": "1.6"},
    **FILES,
}


def test_with_the_switch_off_nothing_of_the_toolbar_ships():
    for case in G.CORE_CASES:
        page = G.render_golden(case).decode()
        assert "a11y-toolbar" not in page and "room-a11y" not in page, case


def test_schema_refuses_what_is_not_ported_and_a_file_not_in_the_pack(tmp_path):
    for rel in FILES.values():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    pack = {k: v for k, v in B.pack_for_site("example").items() if k != K.ROOT_KEY}
    pack["a11y_toolbar"] = copy.deepcopy(TOOLBAR)
    assert K.validate(pack, tmp_path) == []
    for key, value in (("enable_grayscale", "true"), ("custom_fontsize", "1"), ("custom_location", "custom-location")):
        bad = copy.deepcopy(pack)
        bad["a11y_toolbar"]["wpatb"][key] = value
        assert any(f"a11y_toolbar/wpatb/{key}" in p for p in K.validate(bad, tmp_path)), key
    missing = copy.deepcopy(pack)
    missing["a11y_toolbar"]["contrast_css"] = "plugins/wp-accessibility/gone.css"
    assert "plugins/wp-accessibility/gone.css: not a file in the pack" in K.validate(missing, tmp_path)


def test_the_script_keeps_the_plugins_cookies_classes_and_stylesheet_id():
    js = R.ROOM_A11Y_JS
    for name in ('"a11y-high-contrast"', '"a11y-larger-fontsize"', '"highContrastStylesheet"', '"contrast"',
                 '"fontsize"', '"data-wpa-resized"', "path=/; SameSite=Strict;"):
        assert name in js, name
    # No inline script and no storage beyond the plugin's own cookies (CSP script-src 'self').
    assert "localStorage" not in js and "eval(" not in js
