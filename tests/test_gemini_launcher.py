import httpx
import pytest
from scripts import start_gemini

@pytest.mark.parametrize('status,expected',[(200,0),(403,1),(404,1),(429,1)])
def test_launcher_checks_model_and_hides_key(monkeypatch,capsys,status,expected):
    monkeypatch.setenv('GEMINI_API_KEY','fake-launcher-key')
    monkeypatch.setenv('GEMINI_MODEL','test-gemini')
    started=[]
    def get(url,headers,timeout):
        assert url.endswith('/test-gemini') and 'fake-launcher-key' not in url
        assert headers=={'x-goog-api-key':'fake-launcher-key'}
        return httpx.Response(status,json={'supportedGenerationMethods':['generateContent']},request=httpx.Request('GET',url))
    monkeypatch.setattr(start_gemini.httpx,'get',get)
    monkeypatch.setattr(start_gemini.uvicorn,'run',lambda *args,**kwargs:started.append(kwargs))
    assert start_gemini.main()==expected
    assert len(started)==(1 if status==200 else 0)
    assert 'fake-launcher-key' not in capsys.readouterr().out

def test_launcher_refuses_echoed_key_input(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    def insecure(prompt):raise start_gemini.getpass.GetPassWarning('No secure terminal')
    monkeypatch.setattr(start_gemini.getpass,'getpass',insecure)
    assert start_gemini.main()==1
