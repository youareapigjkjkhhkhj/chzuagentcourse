"""
Guardrails for SubsidyAgent: ensure responses are grounded in retrieved docs.
Hallucination detection - flag responses that cite schemes not in retrieved data.
"""
from __future__ import annotations

import re
from typing import List, Dict


def get_retrieved_scheme_names(retrieved_docs: List[Dict[str, str]]) -> set:
    """Extract scheme names from retrieved documents."""
    names = set()
    for doc in retrieved_docs:
        name = doc.get("scheme_name", "").strip()
        if name and name.lower() != "unknown scheme":
            names.add(name.lower())
            # Also add shortened/partial matches for flexible comparison
            words = name.lower().split()
            if len(words) > 1:
                names.add(" ".join(words[:2]))  # e.g. "Pradhan Mantri"
    return names


def detect_subsidy_hallucination(
    response: str,
    retrieved_docs: List[Dict[str, str]],
) -> tuple[bool, str]:
    """
    Check if the response mentions scheme names not present in retrieved docs.
    Returns (is_hallucinated, safe_response).
    If hallucination detected, appends a disclaimer.
    """
    response = str(response or "")
    if not retrieved_docs:
        # No docs = LLM should say "no information found"
        safe_phrases = [
            "no verified", "no information", "not found", "not available",
            "not listed", "contact the", "check with", "no specific scheme"
        ]
        if any(phrase in response.lower() for phrase in safe_phrases):
            return False, response
        disclaimer = (
            "\n\n*Note: This information could not be verified against official records. "
            "Please confirm with your local agriculture office.*"
        )
        return True, response + disclaimer

    valid_names = get_retrieved_scheme_names(retrieved_docs)
    response_lower = response.lower()

    # Check if response primarily references retrieved schemes
    for name in valid_names:
        if name in response_lower or any(w in response_lower for w in name.split()[:2]):
            # At least one retrieved scheme is mentioned - likely grounded
            return False, response

    # Response mentions schemes but none match retrieved - add disclaimer
    scheme_words = {"yojana", "scheme", "nidhi", "bima", "kisan", "pm-", "subsidy"}
    if any(w in response_lower for w in scheme_words) and len(response) > 100:
        disclaimer = (
            "\n\n*Please verify details with the official portal or agriculture department.*"
        )
        return True, response + disclaimer

    return False, response
