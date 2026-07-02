from typing import Any, Literal

from pydantic import BaseModel, Field


SessionStatus = Literal["running", "completed", "stopping", "stopped", "failed"]


class HealthResponse(BaseModel):
    status: str
    service: str


class ProfileResponse(BaseModel):
    profile: dict[str, str]


class ProfileUpdateRequest(BaseModel):
    profile: dict[str, str]


class CreateSessionRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    demo: bool = False
    workout_ticks: int = Field(12, ge=0, le=300)
    workout_tick_delay: float = Field(1.0, ge=0, le=60)


class SessionResponse(BaseModel):
    id: str
    status: SessionStatus
    prompt: str
    created_at: str
    updated_at: str
    dashboard: dict[str, Any] = Field(default_factory=dict)
    final_answer: str | None = None
    error: str | None = None


class StopSessionResponse(BaseModel):
    id: str
    status: SessionStatus


class SessionEvent(BaseModel):
    type: str
    session_id: str
    timestamp: str
    data: dict[str, Any]
