import asyncio
import io
import sqlite3
import pytest
from fastapi.testclient import TestClient
from docx import Document
from app import main, llm

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('LM_STUDIO_MODEL', 'test-model')
    monkeypatch.setattr(main, 'DATA', tmp_path)
    main.JOBS.clear()
    with TestClient(main.app) as c:
        yield c

def job():
    main.JOBS['test'] = {'filename':'a.txt','text':'Иванова Анну','uploaded_at':main.time.time(),
                        'status':'review','entities':[], 'model':'local'}

def entity():
    return {'kind':'persons','start':0,'end':12,'normalized_value':'Иванова Анна','note':'',
            'person':{'фамилия':'Иванова','имя':'Анна','отчество':None,'дата_рождения':None,'место_рождения':None},
            'source_spans':{'фио':{'start':0,'end':12},'дата_рождения':None,'место_рождения':None}}

def test_confirmation_and_idempotency(client):
    job()
    assert not (main.DATA/'entities.sqlite3').exists()
    result = client.post('/api/review/test/confirm', json={'entities':[entity()]})
    assert result.status_code == 200
    repeated = client.post('/api/review/test/confirm', json={'entities':[entity()]})
    assert repeated.json()['already_saved'] is True
    with sqlite3.connect(main.DATA/'entities.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM documents').fetchone()[0] == 1
        assert db.execute('SELECT normalized_value FROM entities').fetchone()[0] == 'Иванова Анна'
        assert db.execute('SELECT original_text FROM mentions').fetchone()[0] == 'Иванова Анну'

@pytest.mark.parametrize('change', [{'start':-1},{'end':100},{'normalized_value':''},{'kind':'unknown'}])
def test_invalid_edits_do_not_save(client, change):
    job(); e=entity(); e.update(change)
    assert client.post('/api/review/test/confirm',json={'entities':[e]}).status_code == 400
    assert not (main.DATA/'entities.sqlite3').exists()

def test_cancel_does_not_save(client):
    job()
    assert client.delete('/api/review/test').status_code == 200
    assert client.get('/api/review/test').status_code == 404
    assert not (main.DATA/'entities.sqlite3').exists()

def test_docx_and_txt():
    doc=Document();doc.add_paragraph('ООО Ромашка');buf=io.BytesIO();doc.save(buf)
    assert main.read_text('a.docx',buf.getvalue()) == 'ООО Ромашка'
    assert main.read_text('a.txt','Иванов'.encode('cp1251')) == 'Иванов'

async def fake(text):
    return [entity() | {'original_text':'Иванова Анну'}]

def test_upload_review_without_database(client,monkeypatch):
    for name in ('persons','organizations','entrepreneurs','communications'):
        monkeypatch.setattr(main,name,fake)
    result=client.post('/api/upload',files={'file':('a.txt','Иванова Анну'.encode())})
    assert result.status_code == 200
    import time
    for _ in range(100):
        review=client.get('/api/review/'+result.json()['token']).json()
        if review['status'] != 'processing': break
        time.sleep(.01)
    assert review['status'] == 'review'
    assert len(review['entities']) == 1
    assert not (main.DATA/'entities.sqlite3').exists()

def test_llm_validates_exact_source(monkeypatch):
    monkeypatch.setenv('LM_STUDIO_MODEL', 'test-model')
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'finish_reason':'stop','message':{'content':'{"entities":[{"original_text":"Несуществующий","normalized_value":"Имя"}]}'}}]}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return Response()
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    with pytest.raises(llm.ExtractionError,match='отсутствует'):
        asyncio.run(llm.extract_kind('Иванов', 'organizations'))

@pytest.mark.parametrize('finish_reason', ['stop','length'])
def test_lm_studio_request_and_response(monkeypatch, finish_reason):
    import json
    monkeypatch.setenv('LM_STUDIO_MODEL','test-model')
    monkeypatch.setenv('LM_STUDIO_URL','http://localhost:1234/v1/')
    monkeypatch.setenv('LM_STUDIO_API_KEY','test-key')
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'finish_reason':finish_reason,'message':{'content':json.dumps([{'фамилия':'Иванов','имя':None,'отчество':None,'дата_рождения':None,'место_рождения':None,
                'исходные_фрагменты':{'фио':'Иванову','дата_рождения':None,'место_рождения':None}}])}}]}
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['headers']['Authorization'] == 'Bearer test-key'
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,json):
            assert url == 'http://localhost:1234/v1/chat/completions'
            assert json['model'] == 'test-model'
            assert json['response_format']['type'] == 'json_schema'
            assert json['response_format']['json_schema']['schema']['type'] == 'array'
            assert 'фамильно-именные' in json['messages'][0]['content']
            return Response()
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    if finish_reason == 'length':
        with pytest.raises(llm.ExtractionError,match='не завершён'):
            asyncio.run(llm.extract_kind('Иванову','persons'))
    else:
        result=asyncio.run(llm.extract_kind('Иванову','persons'))
        assert result[0]['normalized_value']=='Иванов'
        assert result[0]['start']==0 and result[0]['end']==7

def test_missing_model_does_not_create_review(client,monkeypatch):
    monkeypatch.delenv('LM_STUDIO_MODEL',raising=False)
    response=client.post('/api/upload',files={'file':('a.txt','Иванов'.encode())})
    assert response.status_code==503
    assert main.JOBS=={}
    assert not (main.DATA/'entities.sqlite3').exists()
