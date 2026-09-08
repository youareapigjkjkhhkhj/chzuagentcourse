import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from api.routes import router
from api.websocket import run_workflow_streaming, sessions, WorkflowSession

app = FastAPI(title="Supply Chain Orchestrator", version="1.0.0")

app.include_router(router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend", "dist")

if os.path.exists(FRONTEND_DIR):
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(
        "<h1>Supply Chain Orchestrator API</h1><p>Build frontend to serve UI</p>"
    )


@app.get("/vite.svg")
async def vite_asset():
    asset_path = os.path.join(FRONTEND_DIR, "vite.svg")
    if os.path.exists(asset_path):
        return FileResponse(asset_path)
    return HTMLResponse(status_code=404)


@app.websocket("/ws/workflow/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = WorkflowSession(session_id, websocket)
    sessions[session_id] = session

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "start_workflow":
                sku = data.get("sku", "SKU-001")
                await run_workflow_streaming(session, sku)
    except WebSocketDisconnect:
        if session_id in sessions:
            del sessions[session_id]


@app.get("/ws/status")
async def ws_status():
    return {"active_sessions": len(sessions)}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "assets/", "static/", "ws/")):
        return HTMLResponse(status_code=404)
    if "." in full_path:
        return HTMLResponse(status_code=404)

    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
