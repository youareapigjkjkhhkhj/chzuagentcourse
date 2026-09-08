"""Tests for SubsidyAgent guardrails."""
import pytest
from backend.core.guardrails import (
    get_retrieved_scheme_names,
    detect_subsidy_hallucination,
)


def test_get_retrieved_scheme_names():
    docs = [
        {"scheme_name": "PM-KISAN"},
        {"scheme_name": "Soil Health Card Scheme"},
    ]
    names = get_retrieved_scheme_names(docs)
    assert "pm-kisan" in names
    assert "soil health card scheme" in names


def test_detect_no_hallucination_when_docs_empty_and_safe_phrase():
    resp = "No verified government scheme information was found for this query."
    is_hall, safe = detect_subsidy_hallucination(resp, [])
    assert not is_hall
    assert safe == resp


def test_detect_hallucination_when_docs_empty_and_invents():
    resp = "You can get ₹10,000 under the Made-Up Scheme by applying at example.gov"
    is_hall, safe = detect_subsidy_hallucination(resp, [])
    assert is_hall
    assert "official records" in safe or "verify" in safe.lower()


def test_detect_no_hallucination_when_grounded():
    docs = [{"scheme_name": "PM-KISAN", "benefits": "₹6000/year"}]
    resp = "PM-KISAN provides ₹6000 per year to farmers."
    is_hall, safe = detect_subsidy_hallucination(resp, docs)
    assert not is_hall
    assert safe == resp
