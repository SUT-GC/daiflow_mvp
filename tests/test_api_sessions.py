"""Tests for sessions API endpoints."""

from daiflow.models import Session


class TestSessionsAPI:
    async def test_get_session_status(self, client, db_session):
        s = Session(session_id="task:1:plan", type="plan", ref_id="1", status=0)
        db_session.add(s)
        await db_session.commit()

        resp = await client.get("/api/sessions/task:1:plan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "task:1:plan"
        assert data["type"] == "plan"
        assert data["status"] == 0

    async def test_get_session_status_not_found(self, client):
        resp = await client.get("/api/sessions/nonexistent/status")
        assert resp.status_code == 404

    async def test_get_session_logs_no_file(self, client):
        resp = await client.get("/api/sessions/task:1:plan/logs")
        assert resp.status_code == 200
        assert resp.json() == []
