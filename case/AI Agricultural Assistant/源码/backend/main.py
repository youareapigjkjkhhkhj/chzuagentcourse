import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Routers
from backend.routes.health_router import router as health_router
from backend.routes.ask_router import router as ask_router
from backend.routes.weather_router import router as weather_router
from backend.routes.metrics_router import router as metrics_router
from backend.core.config import settings

app = FastAPI(
    title="AgriGPT Backend",
    description="Multimodal AI farming assistant with Groq",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(weather_router)
app.include_router(ask_router)
app.include_router(metrics_router)

# Ensure static dir exists before mounting (avoids startup failure)
_static_dir = Path(__file__).resolve().parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = _static_dir / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(str(favicon_path))
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/")
def root():
    return {
        "message": "AgriGPT Backend running successfully!",
        "endpoints": [
            "/ask/text",
            "/ask/image",
            "/ask/chat",
            "/weather",
            "/health",
            "/metrics/usage",
            "/metrics/quality",
            "/metrics/feedback",
            "/docs"
        ]
    }

@app.on_event("startup")
async def startup_event():
    from backend.core.config import langsmith_enabled, langsmith_api_key

    # Enable LangSmith tracing when configured (key from smith.langchain.com, NOT OpenAI)
    if langsmith_enabled():
        key = langsmith_api_key()
        proj = settings.LANGSMITH_PROJECT or settings.LANGCHAIN_PROJECT or "agrigpt"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = key
        os.environ["LANGCHAIN_PROJECT"] = proj
        os.environ["LANGSMITH_API_KEY"] = key
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = proj
        print("[LangSmith] Tracing enabled → smith.langchain.com")
    else:
        print("[LangSmith] Tracing disabled (set LANGCHAIN_TRACING_V2=true and LANGSMITH_API_KEY to enable)")

    # Log Pinecone vs FAISS for RAG
    if settings.PINECONE_API_KEY and settings.PINECONE_INDEX_NAME:
        print("[Pinecone] Configured for RAG (SubsidyAgent). Run: python -m backend.scripts.populate_pinecone")
    else:
        print("[RAG] Using FAISS (local). Set PINECONE_API_KEY + PINECONE_INDEX_NAME for Pinecone.")

    # Log Redis vs in-memory for chat memory
    from backend.core.memory_manager import redis_available
    if redis_available():
        print("[Redis] Chat memory: persistent (redis)")
    else:
        print("[Redis] Chat memory: in-memory (set REDIS_URL for persistent storage)")

    print("AgriGPT Backend Started: Ready to accept queries")

@app.on_event("shutdown")
async def shutdown_event():
    print(" AgriGPT Backend Shutting down....")
