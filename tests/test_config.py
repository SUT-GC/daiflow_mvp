"""Tests for daiflow.config module."""

import os
import tempfile
from pathlib import Path

from daiflow.config import init_daiflow_dir, safe_filename


class TestSafeFilename:
    def test_replaces_colons(self):
        assert safe_filename("task:42:plan") == "task_42_plan"

    def test_replaces_multiple_unsafe_chars(self):
        assert safe_filename('a\\b/c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"

    def test_preserves_safe_chars(self):
        assert safe_filename("hello-world_v1.2") == "hello-world_v1.2"

    def test_empty_string(self):
        assert safe_filename("") == ""

    def test_init_session_id(self):
        assert safe_filename("init:proj_1:frontend-structure") == "init_proj_1_frontend-structure"


class TestInitDaiflowDir:
    def test_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old = os.environ.get("DAIFLOW_HOME")
            os.environ["DAIFLOW_HOME"] = tmpdir
            try:
                # Re-import to pick up new env var
                import importlib
                import daiflow.config as cfg
                importlib.reload(cfg)
                cfg.init_daiflow_dir()

                assert cfg.DAIFLOW_HOME.exists()
                assert cfg.SESSIONS_DIR.exists()
                assert cfg.PROJECTS_DIR.exists()
                assert cfg.TASKS_DIR.exists()
            finally:
                if old:
                    os.environ["DAIFLOW_HOME"] = old
                importlib.reload(cfg)

    def test_idempotent(self):
        """Calling init_daiflow_dir twice should not raise."""
        init_daiflow_dir()
        init_daiflow_dir()
