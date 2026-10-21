# Vendored test assets

## axe.min.js: axe-core 4.13.0 (Mozilla Public License 2.0)

The reader's accessibility tests inject this into Chromium. It is pinned and
checked in because a missing axe returns no violations, which looks exactly
like a clean result; `axe_source()` in `tests/reading_room_reader/conftest.py`
refuses to run without it.

sha256 `c24f097bd2f451d4f933e8bc7d8d539f8672a2ebcb5cc9f9f3eec8ca9470a0c1`, the
same file LLM_WIKI pins in `scripts/auditkit/probes/vendor/`. To upgrade:

    npm pack axe-core@<version>
    tar -xzf axe-core-<version>.tgz package/axe.min.js
    cp package/axe.min.js tests/vendor/axe.min.js
