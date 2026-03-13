"""Tests for jobs API endpoints and repo_monitor service."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from daiflow.models import Job, JobRun, JobRunStatus, Project, ProjectRepo


class TestJobsCRUD:
    async def _create_project(self, client) -> str:
        resp = await client.post("/api/projects", json={"name": "TestProj"})
        return resp.json()["id"]

    async def test_list_empty(self, client):
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_job(self, client):
        pid = await self._create_project(client)
        resp = await client.post("/api/jobs", json={
            "project_id": pid,
            "type": "repo_monitor",
            "enabled": True,
            "interval": 300,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid
        assert data["type"] == "repo_monitor"
        assert data["enabled"] is True
        assert data["interval"] == 300
        assert data["id"]

    async def test_create_job_min_interval(self, client):
        """Interval should be clamped to minimum 60s."""
        pid = await self._create_project(client)
        resp = await client.post("/api/jobs", json={
            "project_id": pid,
            "interval": 10,
        })
        assert resp.status_code == 200
        assert resp.json()["interval"] == 60

    async def test_create_duplicate_rejected(self, client):
        """Same project + type should return 409."""
        pid = await self._create_project(client)
        resp1 = await client.post("/api/jobs", json={"project_id": pid, "type": "repo_monitor"})
        assert resp1.status_code == 200

        resp2 = await client.post("/api/jobs", json={"project_id": pid, "type": "repo_monitor"})
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    async def test_create_different_projects_ok(self, client):
        """Different projects can have same job type."""
        pid1 = await self._create_project(client)
        pid2 = await self._create_project(client)
        resp1 = await client.post("/api/jobs", json={"project_id": pid1})
        resp2 = await client.post("/api/jobs", json={"project_id": pid2})
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    async def test_list_jobs(self, client):
        pid = await self._create_project(client)
        await client.post("/api/jobs", json={"project_id": pid})
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_update_job(self, client):
        pid = await self._create_project(client)
        create_resp = await client.post("/api/jobs", json={"project_id": pid, "interval": 300})
        job_id = create_resp.json()["id"]

        resp = await client.put(f"/api/jobs/{job_id}", json={"enabled": False, "interval": 600})
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["interval"] == 600

    async def test_update_job_min_interval(self, client):
        pid = await self._create_project(client)
        create_resp = await client.post("/api/jobs", json={"project_id": pid})
        job_id = create_resp.json()["id"]

        resp = await client.put(f"/api/jobs/{job_id}", json={"interval": 5})
        assert resp.status_code == 200
        assert resp.json()["interval"] == 60

    async def test_update_job_not_found(self, client):
        resp = await client.put("/api/jobs/nonexistent", json={"enabled": False})
        assert resp.status_code == 404

    async def test_delete_job(self, client):
        pid = await self._create_project(client)
        create_resp = await client.post("/api/jobs", json={"project_id": pid})
        job_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Should be gone
        list_resp = await client.get("/api/jobs")
        assert len(list_resp.json()) == 0

    async def test_delete_job_not_found(self, client):
        resp = await client.delete("/api/jobs/nonexistent")
        assert resp.status_code == 404


class TestJobRuns:
    async def _create_job(self, client) -> tuple[str, str]:
        resp = await client.post("/api/projects", json={"name": "P"})
        pid = resp.json()["id"]
        resp = await client.post("/api/jobs", json={"project_id": pid})
        return pid, resp.json()["id"]

    async def test_list_runs_empty(self, client):
        _, job_id = await self._create_job(client)
        resp = await client.get(f"/api/jobs/{job_id}/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_runs_with_data(self, client, db_engine):
        _, job_id = await self._create_job(client)

        # Insert a run directly
        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            run = JobRun(
                job_id=job_id,
                status=JobRunStatus.SUCCESS,
                result=json.dumps({"repos_changed": []}),
                finished_at=datetime.now(timezone.utc),
            )
            db.add(run)
            await db.commit()

        resp = await client.get(f"/api/jobs/{job_id}/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["job_id"] == job_id

    async def test_list_recent_runs(self, client, db_engine):
        _, job_id = await self._create_job(client)

        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            db.add(JobRun(
                job_id=job_id,
                status=JobRunStatus.SUCCESS,
                result="{}",
                finished_at=datetime.now(timezone.utc),
            ))
            db.add(JobRun(
                job_id=job_id,
                status=JobRunStatus.FAILED,
                result="{}",
                error="timeout",
                finished_at=datetime.now(timezone.utc),
            ))
            await db.commit()

        resp = await client.get("/api/jobs/runs/recent")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 2
        statuses = {r["status"] for r in runs}
        assert "success" in statuses
        assert "failed" in statuses


class TestJobTrigger:
    async def test_trigger_job(self, client):
        resp = await client.post("/api/projects", json={"name": "P"})
        pid = resp.json()["id"]
        resp = await client.post("/api/jobs", json={"project_id": pid})
        job_id = resp.json()["id"]

        with patch("daiflow.routers.jobs.run_job", new_callable=AsyncMock):
            resp = await client.post(f"/api/jobs/{job_id}/trigger")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_trigger_all(self, client):
        with patch("daiflow.routers.jobs.run_all_jobs", new_callable=AsyncMock):
            resp = await client.post("/api/jobs/trigger-all")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestRepoMonitorService:
    """Tests for repo_monitor.run_job and related functions."""

    async def test_run_job_not_found(self, db_engine):
        from daiflow.services.repo_monitor import run_job

        with patch("daiflow.services.repo_monitor.get_background_db") as mock_bg:
            session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def fake_bg():
                async with session_factory() as s:
                    yield s

            mock_bg.side_effect = fake_bg
            result = await run_job("nonexistent_id")
            assert result == {"error": "job not found"}

    async def test_run_job_skip_if_running(self):
        from daiflow.services.repo_monitor import _running_jobs, run_job

        _running_jobs.add("test_job_id")
        try:
            result = await run_job("test_job_id")
            assert result["status"] == "skipped"
            assert "already running" in result["reason"]
        finally:
            _running_jobs.discard("test_job_id")

    async def test_run_job_success_no_repos(self, db_engine):
        """Job with a project that has no git repos should succeed with empty changes."""
        from daiflow.services.repo_monitor import run_job

        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

        # Create project + job
        async with session_factory() as db:
            p = Project(name="EmptyProj")
            db.add(p)
            await db.flush()
            job = Job(project_id=p.id, type="repo_monitor", enabled=1, interval=300)
            db.add(job)
            await db.commit()
            job_id = job.id

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_bg():
            async with session_factory() as s:
                yield s

        with patch("daiflow.services.repo_monitor.get_background_db", side_effect=fake_bg):
            result = await run_job(job_id)

        assert result["status"] == "success"
        assert result["repos_changed"] == []
        assert result["run_id"]

        # Verify run was persisted
        async with session_factory() as db:
            runs = (await db.execute(select(JobRun).where(JobRun.job_id == job_id))).scalars().all()
            assert len(runs) == 1
            assert runs[0].status == JobRunStatus.SUCCESS

    async def test_run_all_jobs(self, db_engine):
        """run_all_jobs should execute all enabled jobs."""
        from daiflow.services.repo_monitor import run_all_jobs

        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

        async with session_factory() as db:
            p = Project(name="P")
            db.add(p)
            await db.flush()
            j1 = Job(project_id=p.id, type="repo_monitor", enabled=1, interval=300)
            j2 = Job(project_id=p.id, type="other_type", enabled=0, interval=300)  # disabled
            db.add(j1)
            db.add(j2)
            await db.commit()
            j1_id = j1.id

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_bg():
            async with session_factory() as s:
                yield s

        with patch("daiflow.services.repo_monitor.get_background_db", side_effect=fake_bg):
            results = await run_all_jobs()

        # Only the enabled job should run
        assert len(results) == 1
        assert results[0]["job_id"] == j1_id


class TestRepoMonitorModels:
    """Test Job and JobRun model creation and relationships."""

    async def test_create_job(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        job = Job(project_id=p.id, type="repo_monitor", enabled=1, interval=300)
        db_session.add(job)
        await db_session.commit()

        loaded = await db_session.get(Job, job.id)
        assert loaded is not None
        assert loaded.type == "repo_monitor"
        assert loaded.enabled == 1
        assert loaded.interval == 300

    async def test_create_job_run(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        job = Job(project_id=p.id, type="repo_monitor")
        db_session.add(job)
        await db_session.flush()

        run = JobRun(
            job_id=job.id,
            status=JobRunStatus.SUCCESS,
            result=json.dumps({"repos_changed": []}),
            finished_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        await db_session.commit()

        loaded = await db_session.get(JobRun, run.id)
        assert loaded is not None
        assert loaded.status == JobRunStatus.SUCCESS
        assert loaded.job_id == job.id

    async def test_cascade_delete_job(self, db_session):
        """Deleting a job should cascade-delete its runs."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        job = Job(project_id=p.id, type="repo_monitor")
        db_session.add(job)
        await db_session.flush()

        run = JobRun(job_id=job.id, status=JobRunStatus.SUCCESS, result="{}")
        db_session.add(run)
        await db_session.commit()

        run_id = run.id
        await db_session.delete(job)
        await db_session.commit()

        assert await db_session.get(JobRun, run_id) is None

    async def test_job_run_status_enum(self):
        assert JobRunStatus.RUNNING == 0
        assert JobRunStatus.SUCCESS == 1
        assert JobRunStatus.FAILED == 2

    async def test_project_repo_master_hash(self, db_session):
        """ProjectRepo should have a master_hash column."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        repo = ProjectRepo(
            project_id=p.id,
            git_url="https://github.com/test/repo",
            repo_type="backend",
            master_hash="abc123",
        )
        db_session.add(repo)
        await db_session.commit()

        loaded = await db_session.get(ProjectRepo, repo.id)
        assert loaded.master_hash == "abc123"
