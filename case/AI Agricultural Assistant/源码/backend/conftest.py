"""Pytest configuration. Run before any tests to ensure resume-worthy state."""
import os
import sys
from pathlib import Path

# Add project root so "backend" package is importable
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Set minimal env so app can import without real keys (resume-friendly)
os.environ.setdefault("GROQ_API_KEY", "test-key-for-unit-tests")
