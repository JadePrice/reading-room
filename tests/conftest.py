from http.server import HTTPServer

# Every local test site (the Playwright tests serve built rooms and reader pages
# with http.server) listens with a 128-connection backlog, not socketserver's 5.
# Chromium opens many connections at once; on a loaded machine the overflow kept
# a page script from loading (LLM_WIKI tests/conftest.py, 2026-10-21).
HTTPServer.request_queue_size = 128
