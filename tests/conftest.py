import pytest


@pytest.fixture(autouse=True)
def no_real_gemini_key(monkeypatch):
    """Tests never reach the paid Gemini API, even when the key is set in the shell."""
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_local_env_file(monkeypatch, tmp_path):
    """main() must not load the developer's real .env (it may hold API keys)."""
    monkeypatch.setattr("twitch_auto_clipper.cli.ENV_FILE", tmp_path / "missing.env")


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    """CLI tests never read or write the real data/ folder (queued VODs, state, lock)."""
    monkeypatch.setattr("twitch_auto_clipper.cli.DATA_DIR", tmp_path / "data")


@pytest.fixture(autouse=True)
def no_job_object(monkeypatch):
    """The test runner itself is never tied to a Windows job object."""
    monkeypatch.setattr("twitch_auto_clipper.cli.kill_children_with_this_process", lambda: None)
