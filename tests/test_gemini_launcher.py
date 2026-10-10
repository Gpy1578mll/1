import httpx
import pytest
from scripts import start_gemini

@pytest.mark.parametrize('status,expected',[(200,0),(403,1),(404,1),(429,1)])
def test_launcher_checks_model_and_hides_key(monkeypatch,capsys,status,expected):
    monkeypatch.setenv('GEMINI_API_KEY','fake-launcher-key')
    monkeypatch.setenv('GEMINI_MODEL','test-gemini')
    started=[]
    def get(url,headers,params,timeout):
        assert url.endswith('/models') and 'fake-launcher-key' not in url
        assert headers=={'x-goog-api-key':'fake-launcher-key'}
        return httpx.Response(status,json={'models':[{'name':'models/test-gemini','supportedGenerationMethods':['generateContent']}]},request=httpx.Request('GET',url))
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

def test_launcher_reports_invalid_key_before_model_prompt(monkeypatch,capsys):
    monkeypatch.setenv('GEMINI_API_KEY','fake-secret')
    monkeypatch.setenv('GEMINI_MODEL','gemini-flash-latest')
    def get(url,**kwargs):
        assert url.endswith('/models')
        return httpx.Response(400,json={'error':{'status':'INVALID_ARGUMENT','message':'fake-secret',
            'details':[{'reason':'API_KEY_INVALID','metadata':{'key':'fake-secret'}}]}},request=httpx.Request('GET',url))
    monkeypatch.setattr(start_gemini.httpx,'get',get)
    monkeypatch.setattr('builtins.input',lambda *args:pytest.fail('Must not ask for model when key is rejected'))
    assert start_gemini.main()==1
    out=capsys.readouterr().out
    assert 'API_KEY_INVALID' in out
    assert 'fake-secret' not in out

def test_launcher_selects_returned_model_by_number(monkeypatch,capsys):
    monkeypatch.setenv('GEMINI_API_KEY','fake-secret')
    monkeypatch.setenv('GEMINI_MODEL','unknown')
    def get(url,**kwargs):
        return httpx.Response(200,json={'models':[{'name':'models/test-flash','supportedGenerationMethods':['generateContent']}]},
                              request=httpx.Request('GET',url))
    monkeypatch.setattr(start_gemini.httpx,'get',get)
    monkeypatch.setattr('builtins.input',lambda *args:'1')
    launched=[]
    monkeypatch.setattr(start_gemini.uvicorn,'run',lambda *args,**kwargs:launched.append(True))
    assert start_gemini.main()==0
    assert start_gemini.os.environ['GEMINI_MODEL']=='test-flash'
    assert launched==[True]


def test_model_listing_pagination_and_generation_filter(monkeypatch):
    calls=[]
    def get(url,params,**kwargs):
        calls.append(params)
        body={'models':[{'name':'models/embed-only','supportedGenerationMethods':['embedContent']}], 'nextPageToken':'next'} if len(calls)==1 else {
            'models':[{'name':'models/flash','supportedGenerationMethods':['generateContent']}]}
        return httpx.Response(200,json=body,request=httpx.Request('GET',url))
    monkeypatch.setattr(start_gemini.httpx,'get',get)
    assert start_gemini.gemini.available_models('fake-secret')==['flash']
    assert len(calls)==2 and calls[1]['pageToken']=='next'

@pytest.mark.parametrize('body,expected',[
    ({'error':{'details':[{'reason':'API_KEY_EXPIRED'}]}},'истёк'),
    ({'error':{'status':'FAILED_PRECONDITION','message':'fake-secret'}},'условии'),
    ({'error':{'details':[{'reason':'untrusted fake-secret'}], 'message':'fake-secret'}},'Проверьте'),
])
def test_google_diagnostic_uses_only_known_codes(body,expected):
    response=httpx.Response(400,json=body)
    description=start_gemini.gemini.error_description(response)
    assert expected in description
    assert 'fake-secret' not in description
