"""roomkit's Cloudflare Pages header rules (pack `host`, build.py _pages_headers).

A site that is static HTML on Cloudflare Pages has no .htaccess, no nginx, one
root `_headers` file for the whole site. Two properties of that format are what
these tests are about, because both fail silently on deploy:

- A header that two matching rules set is joined with a comma, not overridden.
  So the assets rule must detach the page rule's Cache-Control before setting
  its own, or every asset gets a nonsense combined value.
- 100 rules, 2,000 characters a line. Past the limit Pages simply stops reading.

The splice is here too: the site's own CSP, HSTS and noindex rules share that
file, so a second run has to be a no-op.

The site's name in the markers is the pack's (`identity.site`), written on the
fragment's first line by the build. A caller cannot rename a site by passing a
hostname. The tests that build a real pack's fragment are in
tests/roomkit/sites/test_pages_headers_sites.py.
"""

from __future__ import annotations

from roomkit import build as B
from roomkit import pages_headers as P

MOUNT = "/documents/"


def test_the_splice_refuses_a_fragment_that_names_no_pack(tmp_path):
    headers = tmp_path / "_headers"
    fragment = tmp_path / "_headers.room"
    fragment.write_text(f"{MOUNT}*\n  Cache-Control: no-store\n", encoding="utf-8")

    assert P.main(["splice", "--headers", str(headers), "--fragment", str(fragment),
                   "--mount", MOUNT]) == 1
    assert not headers.exists()


def test_check_counts_rules_the_way_pages_does():
    too_many = "\n".join(f"/p{i}/*\n  X-Robots-Tag: noindex" for i in range(P.MAX_RULES + 1))

    assert len(P.rules(too_many)) == P.MAX_RULES + 1
    assert any("over Pages' limit" in p for p in P.check(too_many))


def test_pack_csp_picks_strict_over_plain_and_off_when_neither():
    assert B._pack_csp({"features": {"csp": True, "csp-strict": True}}) == B.CSP_STRICT
    assert B._pack_csp({"features": {"csp": True}}) == B.CSP
    assert B._pack_csp({"features": {}}) == ""
