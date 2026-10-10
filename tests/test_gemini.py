import asyncio
import copy
import json
import sqlite3
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main, llm
from app.gemini import response_schema
from app.persons import PERSON_SCHEMA

TEXT = 'Иванов Иван. ООО Ромашка. Email: User@EXAMPLE.COM'
PERSON = {'фамилия':'Иванов','имя':'Иван','отчество':None,'дата_рождения':None,'место_рождения':None,
          'исходные_фрагменты':{'фио':'Иванов Иван','дата_рождения':None,'место_рождения':None}}

@pytest.fixture
def configured(monkeypatch,tmp_path):
    monkeypatch.setenv('LLM_PROVIDER','gemini')
    monkeypatch.setenv('GEMINI_MODEL','models/test-gemini')
    monkeypatch.setenv('GEMINI_API_KEY','fake-test-key')
    monkeypatch.setenv('LM_STUDIO_API_KEY','fake-local-key')
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.JOBS.clear()


def transport(monkeypatch,payloads,status=200):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['headers']=={'x-goog-api-key':'fake-test-key'}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json):
            calls.append((url,copy.deepcopy(json)))
            body=payloads[len(calls)-1]
            response=httpx.Response(status,json=body,request=httpx.Request('POST',url))
            return response
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    return calls

def envelope(result):
    return {'candidates':[{'finishReason':'STOP','content':{'parts':[
        {'thought':True,'text':'private reasoning'}, {'text':json.dumps(result,ensure_ascii=False)}]}}]}

def test_gemini_entire_workflow_with_operator_correction(configured,monkeypatch):
    calls=transport(monkeypatch,[envelope([PERSON]),envelope({'entities':[{'original_text':'ООО Ромашка','normalized_value':'ООО «Ромашка»','note':''}]}),
        envelope({'entities':[]}),envelope({'entities':[{'original_text':'User@EXAMPLE.COM','normalized_value':'User@example.com','note':''}]})])
    with TestClient(main.app) as client:
        config=client.get('/api/config').json()
        assert config['provider']=='gemini'
        assert 'Google' in config['notice'] and 'fake-test-key' not in json.dumps(config)
        response=client.post('/api/upload',files={'file':('test.txt',TEXT.encode())})
        assert response.status_code==200
        token=response.json()['token']
        for _ in range(100):
            review=client.get('/api/review/'+token).json()
            if review['status']!='processing':break
            time.sleep(.01)
        assert review['status']=='review',review
        assert review['model']=='test-gemini' and review['provider']=='gemini'
        assert len(review['entities'])==3
        assert not (main.DATA/'entities.sqlite3').exists()
        review['entities'][0]['person']['имя']=None
        assert client.post('/api/review/'+token+'/confirm',json={'entities':review['entities']}).status_code==200
    assert len(calls)==4
    assert all(url=='https://generativelanguage.googleapis.com/v1beta/models/test-gemini:generateContent' for url,_ in calls)
    assert len({body['systemInstruction']['parts'][0]['text'] for _,body in calls})==4
    assert calls[0][1]['generationConfig']['responseSchema']['type']=='ARRAY'
    assert calls[1][1]['generationConfig']['responseSchema']['type']=='OBJECT'
    assert all(body['contents'][0]['parts'][0]['text']==TEXT for _,body in calls)
    assert 'fake-test-key' not in json.dumps(calls)
    with sqlite3.connect(main.DATA/'entities.sqlite3') as db:
        assert db.execute('SELECT provider,model FROM documents').fetchone()==('gemini','test-gemini')
        assert db.execute('SELECT given_name FROM person_details').fetchone()[0] is None
        assert 'fake-test-key' not in db.execute('SELECT original_result FROM documents').fetchone()[0]

@pytest.mark.parametrize('body,status,message', [
    ({'error':{'message':'private key fake-test-key'}},429,'квота'),
    ({'error':{'message':'private key fake-test-key'}},403,'регионе'),
    ({'promptFeedback':{'blockReason':'SAFETY'}},200,'заблокировал'),
    ({'candidates':[{'finishReason':'MAX_TOKENS'}]},200,'лимит токенов'),
    ({'candidates':[{'finishReason':'SAFETY'}]},200,'ограничениям'),
    ({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'not JSON fake-test-key'}]}}]},200,'невалидный JSON'),
    ({'candidates':[{'finishReason':'STOP','content':{'parts':[]}}]},200,'пустой ответ'),
])
def test_gemini_failures_are_safe_and_do_not_retry(configured,monkeypatch,body,status,message):
    calls=transport(monkeypatch,[body],status)
    with pytest.raises(llm.ExtractionError,match=message) as error:
        asyncio.run(llm.extract_kind(TEXT,'persons'))
    assert 'fake-test-key' not in str(error.value)
    assert len(calls)==1
    assert not (main.DATA/'entities.sqlite3').exists()

def test_missing_api_key_rejected_before_upload_task(configured,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY')
    with TestClient(main.app) as client:
        result=client.post('/api/upload',files={'file':('test.txt',TEXT.encode())})
        assert result.status_code==503
        assert 'GEMINI_API_KEY' in result.json()['detail']
    assert main.JOBS=={}

def test_gemini_schema_supports_nullable_person_fields():
    schema=response_schema(PERSON_SCHEMA)
    assert schema['type']=='ARRAY'
    assert schema['items']['properties']['имя']=={'type':'STRING','nullable':True}
    assert schema['items']['properties']['исходные_фрагменты']['properties']['место_рождения']['nullable'] is True
    assert schema['items']['required']==PERSON_SCHEMA['items']['required']
    assert 'additionalProperties' not in schema['items']

@pytest.mark.parametrize('model',['../other?key=secret','https://example.com',''])
def test_invalid_gemini_model(configured,monkeypatch,model):
    monkeypatch.setenv('GEMINI_MODEL',model)
    with pytest.raises(ValueError):llm.model_name()
