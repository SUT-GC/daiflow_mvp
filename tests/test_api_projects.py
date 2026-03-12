"""Tests for projects API endpoints."""

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from daiflow.models import Project, ProjectRepo, Session, SessionStatus


class TestProjectsCRUD:
    async def test_list_empty(self, client):
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_project(self, client):
        resp = await client.post("/api/projects", json={
            "name": "My Project",
            "description": "A test project",
            "repos": [
                {"git_url": "https://github.com/test/repo", "local_path": "/tmp/repo", "repo_type": "backend"}
            ],
            "skill_names": ["python", "fastapi"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Project"
        assert data["description"] == "A test project"
        assert len(data["repos"]) == 1
        assert data["repos"][0]["repo_type"] == "backend"
        assert data["skill_names"] == ["python", "fastapi"]
        assert data["id"]  # Should have an auto-generated ID

    async def test_get_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "P1"})
        pid = create_resp.json()["id"]

        resp = await client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "P1"

    async def test_get_project_not_found(self, client):
        resp = await client.get("/api/projects/nonexistent")
        assert resp.status_code == 404

    async def test_update_project_name(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Old Name"})
        pid = create_resp.json()["id"]

        resp = await client.put(f"/api/projects/{pid}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_project_repos_diff(self, client):
        """Test that updating repos diffs instead of delete-recreate."""
        create_resp = await client.post("/api/projects", json={
            "name": "P1",
            "repos": [
                {"git_url": "https://github.com/a/repo", "local_path": "/tmp/a", "repo_type": "frontend"},
                {"git_url": "https://github.com/b/repo", "local_path": "/tmp/b", "repo_type": "backend"},
            ],
        })
        pid = create_resp.json()["id"]
        original_repos = create_resp.json()["repos"]

        # Update: keep repo A (same git_url+local_path), remove B, add C
        resp = await client.put(f"/api/projects/{pid}", json={
            "repos": [
                {"git_url": "https://github.com/a/repo", "local_path": "/tmp/a", "repo_type": "frontend", "description": "updated"},
                {"git_url": "https://github.com/c/repo", "local_path": "/tmp/c", "repo_type": "custom"},
            ],
        })
        assert resp.status_code == 200
        updated_repos = resp.json()["repos"]
        assert len(updated_repos) == 2

        # Repo A should keep the same ID (diff match by git_url + local_path)
        repo_a_original = next(r for r in original_repos if r["git_url"] == "https://github.com/a/repo")
        repo_a_updated = next(r for r in updated_repos if r["git_url"] == "https://github.com/a/repo")
        assert repo_a_original["id"] == repo_a_updated["id"]
        assert repo_a_updated["description"] == "updated"

        # Repo C is new
        repo_c = next(r for r in updated_repos if r["git_url"] == "https://github.com/c/repo")
        assert repo_c["repo_type"] == "custom"

    async def test_update_project_not_found(self, client):
        resp = await client.put("/api/projects/nonexistent", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "P1"})
        pid = create_resp.json()["id"]

        resp = await client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Should be gone
        resp = await client.get(f"/api/projects/{pid}")
        assert resp.status_code == 404

    async def test_delete_project_not_found(self, client):
        resp = await client.delete("/api/projects/nonexistent")
        assert resp.status_code == 404

    async def test_list_projects_order(self, client):
        await client.post("/api/projects", json={"name": "First"})
        await client.post("/api/projects", json={"name": "Second"})
        resp = await client.get("/api/projects")
        names = [p["name"] for p in resp.json()]
        # Ordered by created_at desc
        assert names == ["Second", "First"]


class TestInitRetry:
    """Tests for POST /api/projects/{id}/init/retry endpoint."""

    async def _create_project_with_sessions(self, client, db_engine):
        """Helper: create a project and manually insert init sessions."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        resp = await client.post("/api/projects", json={
            "name": "RetryTest",
            "repos": [{"local_path": "/tmp/repo", "repo_type": "frontend"}],
        })
        pid = resp.json()["id"]

        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            # Layer 1: done
            db.add(Session(
                session_id=f"init:{pid}:skill_fetch", type="init", ref_id=pid,
                layer=1, status=SessionStatus.DONE,
            ))
            # Layer 2: done
            db.add(Session(
                session_id=f"init:{pid}:frontend_structure", type="init", ref_id=pid,
                layer=2, status=SessionStatus.DONE,
            ))
            # Layer 3: one done, one failed
            db.add(Session(
                session_id=f"init:{pid}:module_overview", type="init", ref_id=pid,
                layer=3, status=SessionStatus.DONE,
            ))
            db.add(Session(
                session_id=f"init:{pid}:api_interaction", type="init", ref_id=pid,
                layer=3, status=SessionStatus.FAILED, error="glob error",
            ))
            # Layer 4: done (but should be re-run on retry)
            db.add(Session(
                session_id=f"init:{pid}:project_md", type="init", ref_id=pid,
                layer=4, status=SessionStatus.DONE,
            ))
            await db.commit()

        return pid

    async def test_retry_not_found(self, client):
        resp = await client.post("/api/projects/nonexistent/init/retry")
        assert resp.status_code == 404

    async def test_retry_no_failures(self, client, db_engine):
        """Should return 400 when no sessions have failed."""
        resp = await client.post("/api/projects", json={"name": "NoFail"})
        pid = resp.json()["id"]

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            db.add(Session(
                session_id=f"init:{pid}:skill_fetch", type="init", ref_id=pid,
                layer=1, status=SessionStatus.DONE,
            ))
            await db.commit()

        resp = await client.post(f"/api/projects/{pid}/init/retry")
        assert resp.status_code == 400
        assert "No failed sessions" in resp.json()["detail"]

    async def test_retry_resets_failed_and_subsequent(self, client, db_engine):
        """Retry should reset the failed session + all subsequent layer sessions."""
        pid = await self._create_project_with_sessions(client, db_engine)

        # Mock run_init_retry to prevent actual background execution
        with patch("daiflow.routers.projects.run_init_retry"):
            resp = await client.post(f"/api/projects/{pid}/init/retry")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["from_layer"] == 3
        assert f"init:{pid}:api_interaction" in data["failed_session_ids"]

        # Verify DB state: failed layer 3 session reset, layer 4 reset
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            # Layer 3 failed session should be reset to WAITING
            s = await db.get(Session, f"init:{pid}:api_interaction")
            assert s.status == SessionStatus.WAITING
            assert s.error is None

            # Layer 3 done session should NOT be reset
            s = await db.get(Session, f"init:{pid}:module_overview")
            assert s.status == SessionStatus.DONE

            # Layer 4 should be reset to WAITING
            s = await db.get(Session, f"init:{pid}:project_md")
            assert s.status == SessionStatus.WAITING

            # Layer 1 & 2 should remain DONE
            s = await db.get(Session, f"init:{pid}:skill_fetch")
            assert s.status == SessionStatus.DONE
            s = await db.get(Session, f"init:{pid}:frontend_structure")
            assert s.status == SessionStatus.DONE


class TestProjectKnowledge:
    """Tests for GET /api/projects/{id}/knowledge endpoint."""

    async def test_knowledge_not_found(self, client):
        resp = await client.get("/api/projects/nonexistent/knowledge")
        assert resp.status_code == 404

    async def test_knowledge_empty_project(self, client):
        resp = await client.post("/api/projects", json={"name": "EmptyKB"})
        pid = resp.json()["id"]

        resp = await client.get(f"/api/projects/{pid}/knowledge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid
        assert data["files"] == []

    async def test_knowledge_with_files(self, client):
        from daiflow.config import PROJECTS_DIR

        resp = await client.post("/api/projects", json={"name": "KBTest"})
        pid = resp.json()["id"]

        # Create knowledge files on disk
        project_dir = PROJECTS_DIR / pid
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "project.md").write_text("# Project Index\nOverview here.", encoding="utf-8")

        skills_dir = project_dir / "skills" / "frontend_structure"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "SKILL.md").write_text("# Frontend\nStructure details.", encoding="utf-8")

        empty_skill = project_dir / "skills" / "api_interaction"
        empty_skill.mkdir(parents=True, exist_ok=True)
        # No SKILL.md — should show as empty content

        resp = await client.get(f"/api/projects/{pid}/knowledge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid

        names = [f["name"] for f in data["files"]]
        assert "project.md" in names
        assert "frontend_structure" in names
        assert "api_interaction" in names

        # project.md is type index
        pm = next(f for f in data["files"] if f["name"] == "project.md")
        assert pm["type"] == "index"
        assert "Project Index" in pm["content"]

        # frontend_structure has content
        fs = next(f for f in data["files"] if f["name"] == "frontend_structure")
        assert fs["type"] == "skill"
        assert "Frontend" in fs["content"]

        # api_interaction is empty (no SKILL.md)
        ai = next(f for f in data["files"] if f["name"] == "api_interaction")
        assert ai["content"] == ""
