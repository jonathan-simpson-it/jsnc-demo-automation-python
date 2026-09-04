"""Tests for model/version pinning."""

import tempfile
from src.compliance.versioning import ModelVersionTracker


def test_register_and_get_current():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ModelVersionTracker(db_path=f"{tmpdir}/versions.db")
        tracker.register(
            model_name="deepseek-chat",
            version="1.0.0",
            config_hash="abc123",
            notes="Initial deployment",
        )
        current = tracker.get_current()
        assert current["model_name"] == "deepseek-chat"
        assert current["version"] == "1.0.0"


def test_version_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ModelVersionTracker(db_path=f"{tmpdir}/versions.db")
        tracker.register(model_name="deepseek-chat", version="1.0.0", config_hash="a", notes="v1")
        tracker.register(model_name="deepseek-chat", version="1.1.0", config_hash="b", notes="v2")
        history = tracker.get_history()
        assert len(history) == 2
        assert history[0]["version"] == "1.1.0"  # Most recent first


def test_config_hash_changes():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ModelVersionTracker(db_path=f"{tmpdir}/versions.db")
        tracker.register(model_name="deepseek-chat", version="1.0.0", config_hash="abc", notes="v1")
        tracker.register(model_name="deepseek-chat", version="1.0.0", config_hash="def", notes="Config changed")
        history = tracker.get_history()
        # Same version but different config hash = config change
        assert history[0]["config_hash"] == "def"
        assert history[1]["config_hash"] == "abc"
