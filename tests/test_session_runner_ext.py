"""Extended tests for session_runner: append_log, run_boundary, ToolCallTracker."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from daiflow.session_runner import append_log, _ToolCallTracker


# ── append_log Tests ──


class TestAppendLog:
    async def test_creates_file_and_appends(self):
        """append_log should create the log file and append JSON events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            with patch("daiflow.session_runner.SESSIONS_DIR", sessions_dir), \
                 patch("daiflow.session_runner.safe_filename", lambda s: s.replace(":", "_")):
                await append_log("test:s1", {"type": "text_delta", "content": "hello"})
                await append_log("test:s1", {"type": "done"})

            log_file = sessions_dir / "test_s1.jsonl"
            assert log_file.exists()

            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 2
            assert json.loads(lines[0])["type"] == "text_delta"
            assert json.loads(lines[0])["content"] == "hello"
            assert json.loads(lines[1])["type"] == "done"

    async def test_creates_parent_dirs(self):
        """append_log should create parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "nested" / "sessions"

            with patch("daiflow.session_runner.SESSIONS_DIR", sessions_dir), \
                 patch("daiflow.session_runner.safe_filename", lambda s: s):
                await append_log("s1", {"type": "test"})

            assert (sessions_dir / "s1.jsonl").exists()

    async def test_unicode_content(self):
        """append_log should handle unicode content correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            with patch("daiflow.session_runner.SESSIONS_DIR", sessions_dir), \
                 patch("daiflow.session_runner.safe_filename", lambda s: s):
                await append_log("s_unicode", {"type": "text_delta", "content": "你好世界"})

            log_file = sessions_dir / "s_unicode.jsonl"
            event = json.loads(log_file.read_text(encoding="utf-8").strip())
            assert event["content"] == "你好世界"

    async def test_multiple_sessions(self):
        """Different session_ids write to different files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            with patch("daiflow.session_runner.SESSIONS_DIR", sessions_dir), \
                 patch("daiflow.session_runner.safe_filename", lambda s: s):
                await append_log("session_a", {"type": "text_delta", "content": "a"})
                await append_log("session_b", {"type": "text_delta", "content": "b"})

            assert (sessions_dir / "session_a.jsonl").exists()
            assert (sessions_dir / "session_b.jsonl").exists()


# ── run_boundary log filtering Tests ──


class TestRunBoundaryFiltering:
    """Test the _read_logs_sync function's run_boundary filtering logic."""

    def test_no_boundary_returns_all(self, tmp_path):
        """When there's no run_boundary, all logs are returned."""
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        events = [
            {"type": "user_message", "content": "hello"},
            {"type": "text_delta", "content": "world"},
            {"type": "done"},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=False)
        assert len(result) == 3

    def test_boundary_filters_old_events(self, tmp_path):
        """Events before the last run_boundary should be filtered out."""
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        events = [
            {"type": "user_message", "content": "old attempt"},
            {"type": "text_delta", "content": "old data"},
            {"type": "done"},
            {"type": "run_boundary", "ts": "2024-01-01T00:00:00Z"},
            {"type": "user_message", "content": "new attempt"},
            {"type": "text_delta", "content": "new data"},
            {"type": "done"},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=False)
        assert len(result) == 3
        assert result[0]["content"] == "new attempt"
        assert result[1]["content"] == "new data"
        assert result[2]["type"] == "done"

    def test_multiple_boundaries_uses_last(self, tmp_path):
        """When multiple boundaries exist, only events after the LAST are returned."""
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        events = [
            {"type": "user_message", "content": "first attempt"},
            {"type": "run_boundary", "ts": "2024-01-01T00:00:00Z"},
            {"type": "user_message", "content": "second attempt"},
            {"type": "run_boundary", "ts": "2024-01-02T00:00:00Z"},
            {"type": "user_message", "content": "third attempt"},
            {"type": "done"},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=False)
        assert len(result) == 2
        assert result[0]["content"] == "third attempt"

    def test_all_attempts_returns_everything(self, tmp_path):
        """all_attempts=True should return all events including those before boundaries."""
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        events = [
            {"type": "user_message", "content": "old"},
            {"type": "run_boundary", "ts": "2024-01-01T00:00:00Z"},
            {"type": "user_message", "content": "new"},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=True)
        assert len(result) == 3

    def test_offset_and_limit(self, tmp_path):
        """Offset and limit should be applied after boundary filtering."""
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        events = [
            {"type": "run_boundary", "ts": "2024-01-01T00:00:00Z"},
            {"type": "text_delta", "content": "a"},
            {"type": "text_delta", "content": "b"},
            {"type": "text_delta", "content": "c"},
            {"type": "text_delta", "content": "d"},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = _read_logs_sync(log_file, limit=2, offset=1, all_attempts=False)
        assert len(result) == 2
        assert result[0]["content"] == "b"
        assert result[1]["content"] == "c"

    def test_empty_file(self, tmp_path):
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "empty.jsonl"
        log_file.write_text("")

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=False)
        assert result == []

    def test_invalid_json_lines_skipped(self, tmp_path):
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        log_file.write_text('{"type": "text_delta", "content": "ok"}\nnot json\n{"type": "done"}\n')

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=False)
        assert len(result) == 2
        assert result[0]["type"] == "text_delta"
        assert result[1]["type"] == "done"

    def test_boundary_at_end_returns_empty(self, tmp_path):
        """If the last event is a run_boundary, result should be empty."""
        from daiflow.routers.sessions import _read_logs_sync

        log_file = tmp_path / "test.jsonl"
        events = [
            {"type": "user_message", "content": "old"},
            {"type": "run_boundary", "ts": "2024-01-01T00:00:00Z"},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = _read_logs_sync(log_file, limit=5000, offset=0, all_attempts=False)
        assert result == []


# ── _ToolCallTracker Tests ──


class TestToolCallTracker:
    def test_tracks_tool_call_args(self):
        tracker = _ToolCallTracker()
        event = {
            "type": "tool_call",
            "tool_name": "write_file",
            "args": {"path": "/tmp/f.py"},
            "tool_call_id": "tc_1",
        }
        tracker.on_event(event)

        # Now enrich a tool_result with the tracked args
        result_event = {
            "type": "tool_result",
            "tool_call_id": "tc_1",
            "content": "OK",
        }
        tracker.enrich(result_event)
        assert result_event["args"] == {"path": "/tmp/f.py"}

    def test_enrich_removes_from_cache(self):
        tracker = _ToolCallTracker()
        tracker.on_event({
            "type": "tool_call",
            "tool_name": "write_file",
            "args": {"path": "/tmp/f.py"},
            "tool_call_id": "tc_1",
        })

        result = {"type": "tool_result", "tool_call_id": "tc_1"}
        tracker.enrich(result)
        assert "args" in result

        # Second enrich should not add args (already popped)
        result2 = {"type": "tool_result", "tool_call_id": "tc_1"}
        tracker.enrich(result2)
        assert "args" not in result2

    def test_detects_read_skill(self):
        tracker = _ToolCallTracker()
        event = {
            "type": "tool_call",
            "tool_name": "read_skill",
            "args": {"skill_name": "frontend-structure"},
            "tool_call_id": "tc_2",
        }
        result = tracker.on_event(event)
        assert result is not None
        assert result["type"] == "skill_loaded"
        assert result["skill_name"] == "frontend-structure"

    def test_non_skill_tool_returns_none(self):
        tracker = _ToolCallTracker()
        event = {
            "type": "tool_call",
            "tool_name": "write_file",
            "args": {"path": "/tmp/f.py"},
            "tool_call_id": "tc_3",
        }
        result = tracker.on_event(event)
        assert result is None

    def test_read_skill_without_name_returns_none(self):
        tracker = _ToolCallTracker()
        event = {
            "type": "tool_call",
            "tool_name": "read_skill",
            "args": {},
            "tool_call_id": "tc_4",
        }
        result = tracker.on_event(event)
        assert result is None

    def test_cache_overflow_clears(self):
        tracker = _ToolCallTracker(max_cached=3)
        for i in range(4):
            tracker.on_event({
                "type": "tool_call",
                "tool_name": "write_file",
                "args": {"n": i},
                "tool_call_id": f"tc_{i}",
            })
        # After overflow, old entries should be cleared
        result = {"type": "tool_result", "tool_call_id": "tc_0"}
        tracker.enrich(result)
        assert "args" not in result  # tc_0 was cleared

    def test_enrich_no_call_id(self):
        tracker = _ToolCallTracker()
        result = {"type": "tool_result", "tool_call_id": ""}
        tracker.enrich(result)
        assert "args" not in result

    def test_enrich_unknown_call_id(self):
        tracker = _ToolCallTracker()
        result = {"type": "tool_result", "tool_call_id": "unknown"}
        tracker.enrich(result)
        assert "args" not in result

    def test_non_tool_call_event_ignored(self):
        tracker = _ToolCallTracker()
        # Should not raise for non-tool_call events
        event = {"type": "text_delta", "content": "hello"}
        # on_event only processes tool_call types, but we should handle gracefully
        # It checks event["type"] == "tool_call" so will skip
        # Actually it will KeyError if we pass non-tool_call... let's check
        # Looking at code: it checks event["type"] == "tool_call" so it returns None
        result = tracker.on_event(event)
        assert result is None
