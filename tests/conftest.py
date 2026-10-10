import pytest

@pytest.fixture(autouse=True)
def isolated_model_environment(monkeypatch):
    """Tests must not use injected credentials or inherit a selected real provider."""
    monkeypatch.setenv('LLM_PROVIDER','local')
    for name in ('GEMINI_MODEL','GEMINI_API_KEY','GEMINI_TIMEOUT',
                 'YANDEX_API_KEY','YANDEX_FOLDER_ID','YANDEX_MODEL','YANDEX_TIMEOUT',
                 'LM_STUDIO_MODEL','LM_STUDIO_URL','LM_STUDIO_API_KEY','LM_STUDIO_TIMEOUT'):
        monkeypatch.delenv(name,raising=False)
