import importlib
from pathlib import Path


def test_config_uses_environment_paths(monkeypatch, tmp_path):
    database = tmp_path / "test.db"
    uploads = tmp_path / "uploads"
    monkeypatch.setenv("RAG_DB_PATH", str(database))
    monkeypatch.setenv("RAG_UPLOAD_DIR", str(uploads))

    from app import config

    importlib.reload(config)

    assert config.DB_PATH == Path(database)
    assert config.UPLOAD_DIR == Path(uploads)
