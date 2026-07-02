import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory
import monitor
from api.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_profile_file(tmp_path, monkeypatch):
    profile_file = tmp_path / "user_profile.json"
    monkeypatch.setattr(memory, "MEMORY_FILE", str(profile_file))


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_page_returns_html():
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert "实时训练看板" in response.text
    assert "开始训练" in response.text
    assert "结束训练" in response.text


def test_profile_round_trip():
    profile = {"健身目标": "减脂", "年龄": "30", "体重": "75", "运动水平": "初级"}
    response = client.put("/profile", json={"profile": profile})
    assert response.status_code == 200
    assert response.json()["profile"] == profile

    response = client.get("/profile")
    assert response.status_code == 200
    assert response.json()["profile"] == profile


def test_non_demo_session_without_api_key_returns_400(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    response = client.post("/sessions", json={"prompt": "制定训练计划", "demo": False})
    assert response.status_code == 400
    assert "LLM_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_demo_session_websocket_stream_and_snapshot(monkeypatch):
    def fake_tick(hr_center, tick, total):
        samples = [
            {"心率": 150, "运动强度": "高", "配速": 6.2, "步频": 170},
            {"心率": 124, "运动强度": "中", "配速": 7.0, "步频": 172},
        ]
        return samples[tick]

    monkeypatch.setattr(monitor, "simulate_tick", fake_tick)

    with TestClient(app) as live_client:
        response = live_client.post(
            "/sessions",
            json={
                "prompt": "我想减脂，今年30岁，体重75公斤，新手",
                "demo": True,
                "workout_ticks": 2,
                "workout_tick_delay": 0,
            },
        )
        assert response.status_code == 200
        session = response.json()
        assert session["status"] == "running"

        seen = []
        messages = []
        with live_client.websocket_connect(f"/sessions/{session['id']}/stream") as websocket:
            for _ in range(80):
                message = websocket.receive_json()
                messages.append(message)
                seen.append(message["type"])
                if message["type"] in {"final", "error", "stopped"}:
                    break

        assert "session_snapshot" in seen
        assert "session_started" in seen
        assert "llm_output" in seen
        assert "action" in seen
        assert "heart_rate_sample" in seen
        assert "advice_event" in seen
        assert "session_summary" in seen
        assert "workout_tick" not in seen
        assert "workout_summary" not in seen
        assert "final" in seen

        snapshot = next(message for message in messages if message["type"] == "session_snapshot")
        assert "dashboard" in snapshot["data"]
        sample = next(message for message in messages if message["type"] == "heart_rate_sample")
        assert sample["data"]["training_zone"] == "燃脂区"
        assert sample["data"]["heart_rate"] == 150
        assert sample["data"]["cadence"] == 170
        assert sample["data"]["pace"] == 6.2
        advice = next(message for message in messages if message["type"] == "advice_event")
        assert advice["data"]["reason"] == "heart_rate_high"
        assert "心率" in advice["data"]["message"]

        response = live_client.get(f"/sessions/{session['id']}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        summary = payload["dashboard"]["summary"]
        assert summary["average_heart_rate"] == 137
        assert summary["peak_heart_rate"] == 150
        assert summary["in_zone_pct"] == 50
        assert summary["corrections"] == 1


def test_stop_missing_session_returns_404():
    response = client.post("/sessions/missing/stop")
    assert response.status_code == 404


def test_stop_running_session_keeps_summary_metrics(monkeypatch):
    samples = [
        {"心率": 120, "运动强度": "中", "配速": 7.2, "步频": 170},
        {"心率": 150, "运动强度": "高", "配速": 6.4, "步频": 170},
    ]

    def fake_tick(hr_center, tick, total):
        return samples[min(tick, len(samples) - 1)]

    monkeypatch.setattr(monitor, "simulate_tick", fake_tick)

    with TestClient(app) as live_client:
        response = live_client.post(
            "/sessions",
            json={
                "prompt": "我想减脂，今年30岁，体重75公斤，新手",
                "demo": True,
                "workout_ticks": 20,
                "workout_tick_delay": 0.01,
            },
        )
        assert response.status_code == 200
        session = response.json()

        messages = []
        stop_sent = False
        with live_client.websocket_connect(f"/sessions/{session['id']}/stream") as websocket:
            for _ in range(80):
                message = websocket.receive_json()
                messages.append(message)
                if message["type"] == "heart_rate_sample" and not stop_sent:
                    stop_response = live_client.post(f"/sessions/{session['id']}/stop")
                    assert stop_response.status_code == 200
                    assert stop_response.json()["status"] in {"stopping", "stopped"}
                    stop_sent = True
                if message["type"] in {"stopped", "error"}:
                    break

        seen = [message["type"] for message in messages]
        assert "heart_rate_sample" in seen
        assert "session_summary" in seen
        assert "stopped" in seen

        summary_event = next(message for message in messages if message["type"] == "session_summary")
        summary = summary_event["data"]
        assert summary["average_heart_rate"] > 0
        assert summary["peak_heart_rate"] > 0
        assert 0 <= summary["in_zone_pct"] <= 100
        assert summary["corrections"] >= 0
        assert summary["samples"] >= 1
        assert summary["stopped"] is True

        response = live_client.get(f"/sessions/{session['id']}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "stopped"
        dashboard_summary = payload["dashboard"]["summary"]
        assert dashboard_summary["average_heart_rate"] == summary["average_heart_rate"]
        assert dashboard_summary["peak_heart_rate"] == summary["peak_heart_rate"]
        assert dashboard_summary["in_zone_pct"] == summary["in_zone_pct"]
        assert dashboard_summary["corrections"] == summary["corrections"]
