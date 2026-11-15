"""roomkit head meta (pack features.head-meta): each page's <title> and meta tags as the
site prints them (roomkit/head_meta.py), the exporter's slices joined, and
parity.head_meta (`roomkit parity --head`)."""

from __future__ import annotations

from pathlib import Path

from roomkit import head_meta as HM

HERE = Path(__file__).resolve().parent


def test_read_head_takes_the_first_title_in_head_only():
    h = HM.read_head("<html><head><title>A &amp; B</title></head><body><title>Toggle Menu</title></body></html>")
    assert h["title"] == "A & B"
