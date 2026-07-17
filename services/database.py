import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, create_engine, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class ProfileRecord(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[str] = mapped_column(String(40), default=utc_now)


class WorkoutSessionRecord(Base):
    __tablename__ = "workout_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    updated_at: Mapped[str] = mapped_column(String(40))
    demo: Mapped[bool] = mapped_column(default=False)
    workout_ticks: Mapped[int] = mapped_column(Integer, default=12)
    workout_tick_delay: Mapped[float] = mapped_column(Float, default=1.0)
    dashboard: Mapped[str] = mapped_column(Text, default="{}")
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    samples: Mapped[list["HeartRateSampleRecord"]] = relationship(
        cascade="all, delete-orphan", order_by="HeartRateSampleRecord.sample_index"
    )
    advice_events: Mapped[list["AdviceEventRecord"]] = relationship(
        cascade="all, delete-orphan", order_by="AdviceEventRecord.id"
    )


class HeartRateSampleRecord(Base):
    __tablename__ = "heart_rate_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("workout_sessions.id"), index=True)
    timestamp: Mapped[str] = mapped_column(String(40))
    sample_index: Mapped[int] = mapped_column(Integer)
    data: Mapped[str] = mapped_column(Text)


class AdviceEventRecord(Base):
    __tablename__ = "advice_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("workout_sessions.id"), index=True)
    timestamp: Mapped[str] = mapped_column(String(40))
    sample_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data: Mapped[str] = mapped_column(Text)


class Database:
    def __init__(self, url: str | None = None):
        default_path = Path(__file__).resolve().parents[1] / "fitness_agent.db"
        self.url = url or os.getenv("FITNESS_DATABASE_URL", f"sqlite:///{default_path.as_posix()}")
        connect_args = {"check_same_thread": False} if self.url.startswith("sqlite") else {}
        self.engine = create_engine(self.url, connect_args=connect_args)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.Session.begin() as db:
            db.execute(
                update(WorkoutSessionRecord)
                .where(WorkoutSessionRecord.status.in_(["running", "stopping"]))
                .values(status="interrupted", updated_at=utc_now(), error="服务重启导致训练中断")
            )

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def save_profile(self, profile: dict[str, str]) -> None:
        with self.Session.begin() as db:
            record = db.get(ProfileRecord, 1)
            payload = json.dumps(profile, ensure_ascii=False)
            if record:
                record.data = payload
                record.updated_at = utc_now()
            else:
                db.add(ProfileRecord(id=1, data=payload))

    def load_profile(self) -> dict[str, str]:
        with self.Session() as db:
            record = db.get(ProfileRecord, 1)
            return json.loads(record.data) if record else {}

    def create_session(self, snapshot: dict[str, Any], demo: bool, ticks: int, delay: float) -> None:
        with self.Session.begin() as db:
            db.add(WorkoutSessionRecord(
                id=snapshot["id"], status=snapshot["status"], prompt=snapshot["prompt"],
                created_at=snapshot["created_at"], updated_at=snapshot["updated_at"],
                demo=demo, workout_ticks=ticks, workout_tick_delay=delay,
                dashboard=json.dumps(snapshot.get("dashboard", {}), ensure_ascii=False),
            ))

    def persist_event(self, snapshot: dict[str, Any], event_type: str,
                      timestamp: str, data: dict[str, Any]) -> None:
        with self.Session.begin() as db:
            record = db.get(WorkoutSessionRecord, snapshot["id"])
            if not record:
                raise RuntimeError(f"会话 {snapshot['id']} 不存在，无法保存事件")
            record.status = snapshot["status"]
            record.updated_at = snapshot["updated_at"]
            record.dashboard = json.dumps(snapshot.get("dashboard", {}), ensure_ascii=False)
            record.final_answer = snapshot.get("final_answer")
            record.error = snapshot.get("error")
            payload = json.dumps(data, ensure_ascii=False)
            if event_type == "heart_rate_sample":
                db.add(HeartRateSampleRecord(
                    session_id=record.id, timestamp=timestamp,
                    sample_index=int(data.get("sample_index", 0)), data=payload,
                ))
            elif event_type == "advice_event":
                db.add(AdviceEventRecord(
                    session_id=record.id, timestamp=timestamp,
                    sample_index=data.get("sample_index"), reason=data.get("reason"), data=payload,
                ))

    @staticmethod
    def _snapshot(record: WorkoutSessionRecord) -> dict[str, Any]:
        return {
            "id": record.id, "status": record.status, "prompt": record.prompt,
            "created_at": record.created_at, "updated_at": record.updated_at,
            "dashboard": json.loads(record.dashboard or "{}"),
            "final_answer": record.final_answer, "error": record.error,
        }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.Session() as db:
            record = db.get(WorkoutSessionRecord, session_id)
            return self._snapshot(record) if record else None

    def list_sessions(self, page: int, page_size: int) -> dict[str, Any]:
        with self.Session() as db:
            total = db.scalar(select(func.count()).select_from(WorkoutSessionRecord)) or 0
            records = db.scalars(
                select(WorkoutSessionRecord).order_by(WorkoutSessionRecord.created_at.desc())
                .offset((page - 1) * page_size).limit(page_size)
            ).all()
            return {"items": [self._snapshot(r) for r in records], "total": total,
                    "page": page, "page_size": page_size}

    def session_details(self, session_id: str) -> dict[str, Any] | None:
        with self.Session() as db:
            record = db.get(WorkoutSessionRecord, session_id)
            if not record:
                return None
            result = self._snapshot(record)
            result["samples"] = [dict(json.loads(row.data), timestamp=row.timestamp) for row in record.samples]
            result["advice_events"] = [dict(json.loads(row.data), timestamp=row.timestamp) for row in record.advice_events]
            return result

    def trends(self) -> dict[str, Any]:
        with self.Session() as db:
            records = db.scalars(
                select(WorkoutSessionRecord)
                .where(WorkoutSessionRecord.status.in_(["completed", "stopped"]))
                .order_by(WorkoutSessionRecord.created_at.asc())
            ).all()
            points = []
            for record in records:
                dashboard = json.loads(record.dashboard or "{}")
                summary = dashboard.get("summary")
                if not summary:
                    continue
                started = dashboard.get("workout_started_at")
                finished = dashboard.get("workout_finished_at")
                duration = 0
                if started and finished:
                    duration = max(0, round((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()))
                points.append({
                    "session_id": record.id, "created_at": record.created_at,
                    "duration_seconds": duration,
                    "average_heart_rate": summary.get("average_heart_rate", 0),
                    "peak_heart_rate": summary.get("peak_heart_rate", 0),
                    "in_zone_pct": summary.get("in_zone_pct", 0),
                    "corrections": summary.get("corrections", 0),
                })
            return {
                "workout_count": len(points),
                "total_duration_seconds": sum(p["duration_seconds"] for p in points),
                "points": points,
            }


database = Database()
