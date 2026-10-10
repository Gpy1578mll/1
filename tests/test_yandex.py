import asyncio
import json
import sqlite3
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main, llm, yandex
from scripts import start_yandex

TEXT='Иванов Иван. ООО Ромашка. Email: User@EXAMPLE.COM'
PERSON={'фамилия':'Иванов','имя':'Иван','отчество':None,'дата_рождения':None,'место_рождения':None,
        'исходные_фрагменты':{'фио':'Иванов Иван','дата_рождения':None,'место_рождения':None}}

@pytest.fixture
def configured(monkeypatch,tmp_path):
    monkeypatch.setenv('LLM_PROVIDER','yandex')
    monkeypatch.setenv('YANDEX_FOLDER_ID','test-folder')
    monkeypatch.setenv('YANDEX_API_KEY','fake-yandex-key')
    monkeypatch.setenv('GEMINI_API_KEY','fake-other-key')
    monkeypatch.setenv('LM_STUDIO_API_KEY','fake-local-key')
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.JOBS.clear()

def envelope(result,status='ALTERNATIVE_STATUS_FINAL'):
    return {'result':{'alternatives':[{'status':status,'message':{'role':'assistant','text':json.dumps(result,ensure_ascii=False)}}]}}

def transport(monkeypatch,payloads,status=200):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['headers']=={'Authorization':'Api-Key fake-yandex-key','x-folder-id':'test-folder','x-data-logging-enabled':'false'}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json):
            calls.append((url,json))
            return httpx.Response(status,json=payloads[len(calls)-1],request=httpx.Request('POST',url))
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    return calls

def test_yandex_upload_review_confirmation(configured,monkeypatch):
    calls=transport(monkeypatch,[envelope([PERSON]),envelope({'entities':[{'original_text':'ООО Ромашка','normalized_value':'ООО «Ромашка»','note':''}]}),
                                 envelope({'entities':[]}),envelope({'entities':[{'original_text':'User@EXAMPLE.COM','normalized_value':'User@example.com','note':''}]})])
    with TestClient(main.app) as client:
        assert 'Yandex Cloud' in client.get('/api/config').json()['notice']
        response=client.post('/api/upload',files={'file':('test.txt',TEXT.encode())})
        assert response.status_code==200
        token=response.json()['token']
        for _ in range(100):
            review=client.get('/api/review/'+token).json()
            if review['status']!='processing':break
            time.sleep(.01)
        assert review['status']=='review',review
        assert not (main.DATA/'entities.sqlite3').exists()
        review['entities'][0]['person']['имя']=None
        assert client.post('/api/review/'+token+'/confirm',json={'entities':review['entities']}).status_code==200
    assert len(calls)==4
    assert all(url==yandex.BASE_URL+'/completion' for url,_ in calls)
    assert all(body['modelUri']=='gpt://test-folder/yandexgpt/latest' for _,body in calls)
    assert len({body['messages'][0]['text'] for _,body in calls})==4
    assert calls[0][1]['jsonSchema']['schema']['type']=='array'
    assert calls[1][1]['jsonSchema']['schema']['type']=='object'
    assert 'fake-yandex-key' not in json.dumps(calls)
    with sqlite3.connect(main.DATA/'entities.sqlite3') as db:
        assert db.execute('SELECT provider,model FROM documents').fetchone()==('yandex','gpt://test-folder/yandexgpt/latest')
        assert db.execute('SELECT given_name FROM person_details').fetchone()[0] is None

@pytest.mark.parametrize('body,status,match',[
    ({'message':'fake-yandex-key'},401,'секретный API-ключ'),
    ({'message':'fake-yandex-key'},403,'права'),
    ({'message':'fake-yandex-key'},429,'квота'),
    (envelope([], 'ALTERNATIVE_STATUS_TRUNCATED_FINAL'),200,'лимит токенов'),
    (envelope([], 'ALTERNATIVE_STATUS_CONTENT_FILTER'),200,'ограничениям'),
    ({'result':{'alternatives':[]}},200,'result.alternatives'),
    ({'result':{'alternatives':[{'status':'ALTERNATIVE_STATUS_FINAL','message':{'text':'bad JSON fake-yandex-key'}}]}},200,'невалидный JSON'),
])
def test_yandex_errors_are_safe_no_retry(configured,monkeypatch,body,status,match):
    calls=transport(monkeypatch,[body],status)
    with pytest.raises(llm.ExtractionError,match=match) as error:
        asyncio.run(llm.extract_kind(TEXT,'persons'))
    assert 'fake-yandex-key' not in str(error.value)
    assert len(calls)==1
    assert not (main.DATA/'entities.sqlite3').exists()

@pytest.mark.parametrize('missing',['YANDEX_FOLDER_ID','YANDEX_API_KEY'])
def test_missing_configuration_rejected_without_task(configured,monkeypatch,missing):
    monkeypatch.delenv(missing)
    with TestClient(main.app) as client:
        response=client.post('/api/upload',files={'file':('test.txt',TEXT.encode())})
        assert response.status_code==503
        assert missing in response.json()['detail']
    assert main.JOBS=={}

@pytest.mark.parametrize('status,expected',[(200,0),(401,1),(403,1)])
def test_launcher_checks_access_without_generation(configured,monkeypatch,capsys,status,expected):
    launched=[]
    def post(url,headers,timeout,json):
        assert url.endswith('/tokenizeCompletion')
        assert 'fake-yandex-key' not in url and headers['Authorization']=='Api-Key fake-yandex-key'
        assert json['modelUri']=='gpt://test-folder/yandexgpt/latest'
        assert json['messages'][0]['text']=='Проверка подключения'
        return httpx.Response(status,json={'tokens':[]},request=httpx.Request('POST',url))
    monkeypatch.setattr(start_yandex.httpx,'post',post)
    monkeypatch.setattr(start_yandex.uvicorn,'run',lambda *args,**kwargs:launched.append(True))
    assert start_yandex.main()==expected
    assert len(launched)==(1 if expected==0 else 0)
    assert 'fake-yandex-key' not in capsys.readouterr().out

@pytest.mark.parametrize('model',['https://example.com','../secret','yandexgpt'])
def test_invalid_model_identifier(configured,monkeypatch,model):
    monkeypatch.setenv('YANDEX_MODEL',model)
    with pytest.raises(ValueError):yandex.model_name()
