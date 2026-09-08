"""Resume-worthy API tests. Run to verify system is ready for work."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


# --- Core availability ---


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "message" in data
    assert "endpoints" in data
    endpoints = data.get("endpoints", [])
    assert "/metrics/usage" in endpoints
    assert "/metrics/quality" in endpoints
    assert "/health" in endpoints


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "OK"
    assert "models" in data
    assert "dependencies" in data


def test_health_models_configured(client):
    """Resume checkpoint: models must be set to supported (non-deprecated) IDs."""
    r = client.get("/health")
    assert r.status_code == 200
    models = r.json().get("models", {})
    text = str(models.get("text_model", ""))
    vision = str(models.get("vision_model", ""))
    assert text, "TEXT_MODEL_NAME must be set"
    assert vision, "VISION_MODEL_NAME must be set"
    # Reject decommissioned Groq models
    assert "llama-3.1-70b-versatile" not in text, "Use llama-3.3-70b-versatile"
    assert "llama-3.2-vision-preview" not in vision, "Use meta-llama/llama-4-scout-*"


# --- Metrics ---


def test_metrics_usage(client):
    r = client.get("/metrics/usage?days=7")
    assert r.status_code == 200
    data = r.json()
    assert "total_requests" in data
    assert "by_agent" in data
    assert "by_type" in data
    assert "by_day" in data
    assert data["days"] == 7
    assert isinstance(data["total_requests"], int)


def test_metrics_quality(client):
    r = client.get("/metrics/quality?days=30")
    assert r.status_code == 200
    data = r.json()
    assert "total_responses" in data
    assert "positive" in data
    assert "negative" in data
    assert "satisfaction_rate" in data
    assert data["days"] == 30
    assert isinstance(data["total_responses"], int)


def test_metrics_feedback_post(client):
    """Feedback endpoint accepts valid input."""
    r = client.post(
        "/metrics/feedback",
        params={"request_id": "test-resume-001", "feedback": "positive"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "recorded"
    assert data.get("request_id") == "test-resume-001"
