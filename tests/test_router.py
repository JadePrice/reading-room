"""Unit tests for the decision and query router."""

from __future__ import annotations

from roomkit.router import route_query


def test_vendor_routing() -> None:
    res = route_query("axon")
    assert res["intent"] == "entity_vendor"
    assert res["matched_target"] == "axon"
    assert res["confidence"] >= 0.95
    assert not res["is_person_search"]


def test_agency_routing() -> None:
    res = route_query("dane county sheriff records")
    assert res["intent"] == "entity_agency"
    assert res["matched_target"] == "dane county sheriff"
    assert res["confidence"] >= 0.95


def test_record_type_routing() -> None:
    res = route_query("body cameras master contract")
    assert res["intent"] == "record_type_filter"
    assert res["matched_target"] == "contract"
    assert res["confidence"] >= 0.85


def test_person_search_guardrail() -> None:
    res = route_query("officer John Doe surveillance search")
    assert res["is_person_search"] is True


def test_general_fulltext_routing() -> None:
    res = route_query("historical documentation on municipal governance")
    assert res["intent"] == "body_fulltext"
    assert not res["is_person_search"]
    assert res["elapsed_ms"] < 10.0
