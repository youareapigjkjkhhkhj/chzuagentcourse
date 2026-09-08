from fastapi import APIRouter, Form

router = APIRouter(prefix="/simple", tags=["Simple"])

@router.post("/echo")
def simple_echo(text: str = Form(...)):
    """
    Ultra-simple endpoint with NO agent imports.
    Just echoes text back.
    """
    return {
        "status": "success",
        "echo": text.upper(),
        "message": "This endpoint has ZERO dependencies on agents"
    }

@router.post("/fake-analysis")
def fake_analysis(query: str = Form(...)):
    """
    Fake analysis endpoint - no master_agent import.
    """
    return {
        "status": "success",
        "query": query,
        "analysis": f"Fake response for: {query}. No agents were called."
    }