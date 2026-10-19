"""Decision and query routing primitives for reading room discovery.

Provides fast, local, deterministic intent classification and guardrails.
"""

from __future__ import annotations

import re
import time
from typing import Any

VENDORS = {
    "axon",
    "flock",
    "flock safety",
    "motorola",
    "vigilant",
    "clearview",
    "clearview ai",
    "voyager labs",
}

AGENCIES = {
    "fbi",
    "dhs",
    "doj",
    "dane county sheriff",
    "madison police",
    "capitol police",
    "uw-madison police",
    "wi doa",
}

RECORD_TYPES = {
    "contract",
    "mou",
    "moa",
    "agreement",
    "invoice",
    "requisition",
    "report",
    "policy",
    "pia",
}

_PERSON_RE = re.compile(r"\b(officer|target|subject|suspect|person|resident)\b")


def route_query(q: str) -> dict[str, Any]:
    """Route a search query into an intent category locally with 0 dependencies.

    Returns intent, confidence, matched target, and surveillance policy check.
    """
    t0 = time.perf_counter()
    q_norm = q.lower().strip()

    is_person = bool(_PERSON_RE.search(q_norm))

    intent = "body_fulltext"
    confidence = 0.70
    matched_target = None

    if q_norm in VENDORS or any(v in q_norm for v in VENDORS):
        intent = "entity_vendor"
        confidence = 0.98
        matched_target = next((v for v in VENDORS if v in q_norm), None)
    elif q_norm in AGENCIES or any(a in q_norm for a in AGENCIES):
        intent = "entity_agency"
        confidence = 0.95
        matched_target = next((a for a in AGENCIES if a in q_norm), None)
    elif any(r in q_norm for r in RECORD_TYPES):
        intent = "record_type_filter"
        confidence = 0.88
        matched_target = next((r for r in RECORD_TYPES if r in q_norm), None)
    elif "cointelpro" in q_norm:
        intent = "collection_cointelpro"
        confidence = 0.99
        matched_target = "cointelpro"

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "query": q,
        "intent": intent,
        "matched_target": matched_target,
        "confidence": confidence,
        "is_person_search": is_person,
        "elapsed_ms": round(elapsed_ms, 3),
    }
