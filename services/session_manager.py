import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import agent
import monitor


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionState:
    id: str
    prompt: str
    status: str
    created_at: str
    updated_at: str
    demo: bool
    workout_ticks: int
    workout_tick_delay: float
    llm: Any
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    stop_event: threading.Event = field(default_factory=threading.Event)
    history: list[str] = field(default_factory=list)
    dashboard: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None
    error: str | None = None
    task: asyncio.Task | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "prompt": self.prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "dashboard": self.dashboard,
            "final_answer": self.final_answer,
            "error": self.error,
        }


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def create_session(self, prompt: str, demo: bool, workout_ticks: int,
                             workout_tick_delay: float) -> SessionState:
        llm = agent.create_llm(demo=demo)
        session_id = str(uuid4())
        now = utc_now()
        session = SessionState(
            id=session_id,
            prompt=prompt,
            status="running",
            created_at=now,
            updated_at=now,
            demo=demo,
            workout_ticks=workout_ticks,
            workout_tick_delay=workout_tick_delay,
            llm=llm,
            history=[f"用户请求: {prompt}"],
        )

        async with self._lock:
            self.sessions[session_id] = session

        self._loop = asyncio.get_running_loop()
        await self.emit(session, "session_started", session.snapshot())
        session.task = asyncio.create_task(self._run_session(session))
        return session

    async def get_session(self, session_id: str) -> SessionState | None:
        async with self._lock:
            return self.sessions.get(session_id)

    async def stop_session(self, session_id: str) -> SessionState | None:
        session = await self.get_session(session_id)
        if not session:
            return None

        if session.status == "running":
            session.status = "stopping"
            session.updated_at = utc_now()
            session.stop_event.set()
            await self.emit(session, "stop_requested", {"reason": "stop_requested"})
        return session

    async def emit(self, session: SessionState, event_type: str, data: dict[str, Any]):
        session.updated_at = utc_now()
        self._update_dashboard(session, event_type, data)
        await session.queue.put({
            "type": event_type,
            "session_id": session.id,
            "timestamp": session.updated_at,
            "data": data,
        })

    def _update_dashboard(self, session: SessionState, event_type: str, data: dict[str, Any]):
        if event_type == "heart_rate_sample":
            session.dashboard.setdefault("workout_started_at", session.updated_at)
            session.dashboard["last_sample"] = data
            session.dashboard["last_sample_at"] = session.updated_at
        elif event_type == "advice_event":
            session.dashboard["last_advice"] = data
            session.dashboard["last_advice_at"] = session.updated_at
        elif event_type == "session_summary":
            session.dashboard["summary"] = data
            session.dashboard["summary_at"] = session.updated_at
            session.dashboard["workout_finished_at"] = session.updated_at
        elif event_type == "final":
            session.dashboard["final_answer"] = data.get("final_answer")
        elif event_type in {"error", "stopped"}:
            session.dashboard["terminal_event"] = {"type": event_type, "data": data}

    def emit_from_thread(self, session: SessionState, event_type: str, data: dict[str, Any]):
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self.emit(session, event_type, data), self._loop)

    async def _run_session(self, session: SessionState):
        try:
            result = await asyncio.to_thread(self._run_react_session, session)
            session.history = result.get("history", session.history)
            session.final_answer = result.get("final_answer")
            session.error = result.get("error")

            if session.status == "stopping" or result.get("status") == "stopped":
                session.status = "stopped"
                await self.emit(session, "stopped", {"reason": "训练已停止"})
            elif result.get("status") == "completed":
                session.status = "completed"
            else:
                session.status = "failed"
                if not session.error:
                    session.error = "会话未能完成。"
                await self.emit(session, "error", {"message": session.error})
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)
            await self.emit(session, "error", {"message": str(exc)})
        finally:
            session.updated_at = utc_now()

    def _run_react_session(self, session: SessionState) -> dict[str, Any]:
        def event_sink(event_type: str, data: dict[str, Any]):
            self.emit_from_thread(session, event_type, data)

        def stop_checker() -> bool:
            return session.stop_event.is_set()

        def workout_runner(profile: dict, plan_summary: str) -> str:
            final_summary = "训练监测已停止。"
            for event in monitor.iter_workout_events(
                profile,
                plan_summary,
                ticks=session.workout_ticks,
                tick_delay=session.workout_tick_delay,
                stop_checker=stop_checker,
            ):
                self.emit_from_thread(session, event["type"], event["data"])
                if event["type"] == "session_summary":
                    final_summary = event["data"]["summary"]
                elif event["type"] == "stopped" and final_summary == "训练监测已停止。":
                    final_summary = (
                        f"训练监测已停止。已完成 {event['data']['completed_ticks']}/"
                        f"{event['data']['total_samples']} 拍。"
                    )
            return final_summary

        return agent.run_react_loop(
            session.history,
            llm=session.llm,
            event_sink=event_sink,
            stop_checker=stop_checker,
            workout_runner=workout_runner,
        )
