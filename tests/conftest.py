import pytest


@pytest.fixture(autouse=True)
def no_real_gemini_key(monkeypatch):
    """Tests never reach the paid Gemini API, even when the key is set in the shell."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_local_env_file(monkeypatch, tmp_path):
    """main() must not load the developer's real .env (it may hold API keys)."""
    monkeypatch.setattr("twitch_auto_clipper.cli.ENV_FILE", tmp_path / "missing.env")


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    """CLI tests never read or write the real data/ folder (queued VODs, state, lock)."""
    monkeypatch.setattr("twitch_auto_clipper.cli.DATA_DIR", tmp_path / "data")
