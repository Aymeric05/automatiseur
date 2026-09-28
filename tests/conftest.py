import pytest


@pytest.fixture(autouse=True)
def no_real_gemini_key(monkeypatch):
    """Tests never reach the paid Gemini API, even when the key is set in the shell."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
