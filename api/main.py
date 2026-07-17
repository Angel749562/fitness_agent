from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.schemas import (
    CreateSessionRequest,
    HealthResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SessionResponse,
    SessionDetailsResponse,
    SessionListResponse,
    StopSessionResponse,
    TrendsResponse,
)
from memory import load_memory, migrate_json_profile, save_memory
from services.database import database
from services.session_manager import SessionManager

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        database.initialize()
        migrate_json_profile()
    except Exception as exc:
        raise RuntimeError(f"数据库初始化失败：{exc}") from exc
    yield


app = FastAPI(title="Fitness Agent API", lifespan=lifespan)
session_manager = SessionManager()
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/dashboard", StaticFiles(directory=WEB_DIR, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
async def dashboard_root():
    return RedirectResponse(url="/dashboard/")


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok", "service": "fitness-agent-api"}


@app.get("/profile", response_model=ProfileResponse)
async def get_profile():
    return {"profile": load_memory()}


@app.put("/profile", response_model=ProfileResponse)
async def update_profile(request: ProfileUpdateRequest):
    save_memory(request.profile)
    return {"profile": load_memory()}


@app.post("/sessions", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    try:
        session = await session_manager.create_session(
            prompt=request.prompt,
            demo=request.demo,
            workout_ticks=request.workout_ticks,
            workout_tick_delay=request.workout_tick_delay,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"训练数据保存失败：{exc}") from exc
    return session.snapshot()


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)
):
    return database.list_sessions(page, page_size)


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.snapshot()


@app.get("/sessions/{session_id}/details", response_model=SessionDetailsResponse)
async def get_session_details(session_id: str):
    details = database.session_details(session_id)
    if not details:
        raise HTTPException(status_code=404, detail="Session not found")
    return details


@app.get("/trends", response_model=TrendsResponse)
async def get_trends():
    return database.trends()


@app.post("/sessions/{session_id}/stop", response_model=StopSessionResponse)
async def stop_session(session_id: str):
    session = await session_manager.stop_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session.id, "status": session.status}


@app.websocket("/sessions/{session_id}/stream")
async def stream_session(websocket: WebSocket, session_id: str):
    await websocket.accept()

    session = await session_manager.get_session(session_id)
    if not session:
        await websocket.send_json({"type": "error", "data": {"message": "Session not found"}})
        await websocket.close(code=1008)
        return

    await websocket.send_json({
        "type": "session_snapshot",
        "session_id": session.id,
        "timestamp": session.updated_at,
        "data": session.snapshot(),
    })

    if session.status in {"completed", "stopped", "failed", "interrupted"}:
        await websocket.close()
        return

    try:
        while True:
            event = await session.queue.get()
            await websocket.send_json(event)
            if event["type"] in {"final", "error", "stopped"}:
                await websocket.close()
                return
    except WebSocketDisconnect:
        return
