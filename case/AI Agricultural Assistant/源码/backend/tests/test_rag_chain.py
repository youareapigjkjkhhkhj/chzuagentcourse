"""Tests for LCEL RAG chain."""
import pytest
from backend.services.rag_chain import _format_subsidy_docs


def test_format_subsidy_docs_empty():
    assert "No verified" in _format_subsidy_docs([])


def test_format_subsidy_docs_with_data():
    docs = [
        {"scheme_name": "PM-Kisan", "eligibility": "Farmers", "benefits": "₹6000"},
    ]
    out = _format_subsidy_docs(docs)
    assert "PM-Kisan" in out
    assert "Farmers" in out
    assert "₹6000" in out
