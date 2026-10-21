# Reader contracts

JSON Schemas (draft 2020-12) for what the reader engine is sent. `tests/reading_room_reader/test_contract.py` validates each one.

| Schema | Producer | Consumer |
|---|---|---|
| `doc-search.schema.json` | GG `ggrr/v1/doc-search` (`class-ggrr-rest.php` `doc_search`), dd `deflock-rr/v1/doc-search` | `rr-reader-pdf.js` in-document search (`docSearchUrl`) |
| `passage.schema.json` | GG `ggrr/v1/passage` (`GGRR_Citations::resolve_passage`); GG only | `rr-reader-pdf.js` cite panel (`passageUrl`) |
| `pages.schema.json` | roomkit `build.py`, `<slug>/pages.<hash>.json` | `rr-reader-pdf.js` static search and page cites, `rr-reader-image.js` transcript and OCR boxes (`data-pages-url`) |

A producer that adds a field updates the schema in the same change; `additionalProperties: false` makes the test fail otherwise. What a schema cannot say is enforced by the producer and named in the schema's `description` (a box's `ymin < ymax`, `xmin < xmax`: roomkit `manifest.py`).

The `$id` host (`llm-wiki.local`) is a placeholder, not a served URL.
