import asyncio
import copy
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import main, llm
from app.persons import parse_person

TEXT = 'Иванову Ивану Ивановичу, дата рождения 15 марта 1990 года, место рождения г. Москва. Петров Петр, родился в 1985 году.'

def person_item():
    return {'фамилия':'Иванов','имя':'Иван','отчество':'Иванович','дата_рождения':'15.03.1990','место_рождения':'г. Москва',
            'исходные_фрагменты':{'фио':'Иванову Ивану Ивановичу','дата_рождения':'15 марта 1990 года','место_рождения':'г. Москва'}}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.JOBS.clear()
    main.JOBS['test']={'filename':'test.txt','text':TEXT,'uploaded_at':main.time.time(),'status':'review',
                       'entities':[parse_person(person_item(),TEXT,0)],'model':'test-model'}
    with TestClient(main.app) as client:
        yield client

def test_corrected_person_and_sources_saved(client):
    entity=copy.deepcopy(main.JOBS['test']['entities'][0])
    entity['person']['имя']='И.'
    entity['person']['отчество']=None
    response=client.post('/api/review/test/confirm',json={'entities':[entity]})
    assert response.status_code==200
    with sqlite3.connect(main.DATA/'entities.sqlite3') as db:
        assert db.execute('SELECT surname,given_name,patronymic,birth_date,birth_place FROM person_details').fetchone()==('Иванов','И.',None,'15.03.1990','г. Москва')
        assert db.execute('SELECT normalized_value FROM entities').fetchone()[0]=='Иванов И.'
        rows=dict(db.execute('SELECT field,original_text FROM mentions'))
        assert rows=={'фио':'Иванову Ивану Ивановичу','дата_рождения':'15 марта 1990 года','место_рождения':'г. Москва'}
        original=json.loads(db.execute('SELECT original_result FROM documents').fetchone()[0])
        assert original[0]['person']['имя']=='Иван'
        assert original[0]['person']['отчество']=='Иванович'

@pytest.mark.parametrize('mutate', [
    lambda e:e['person'].update({'место_рождения':'Москва'}),
    lambda e:e['person'].update({'дата_рождения':'31.02.1990'}),
    lambda e:e['person'].update({'имя':''}),
    lambda e:e['source_spans'].update({'дата_рождения':None}),
    lambda e:e['source_spans']['место_рождения'].update({'end':9999}),
])
def test_bad_person_edits_rejected_before_database(client,mutate):
    entity=copy.deepcopy(main.JOBS['test']['entities'][0]);mutate(entity)
    assert client.post('/api/review/test/confirm',json={'entities':[entity]}).status_code==400
    assert not (main.DATA/'entities.sqlite3').exists()

def test_multiple_people_and_partial_date(client):
    second={'фамилия':'Петров','имя':'Петр','отчество':None,'дата_рождения':'1985','место_рождения':None,
            'исходные_фрагменты':{'фио':'Петров Петр','дата_рождения':'1985','место_рождения':None}}
    entities=[parse_person(person_item(),TEXT,0),parse_person(second,TEXT,0)]
    assert client.post('/api/review/test/confirm',json={'entities':entities}).status_code==200
    with sqlite3.connect(main.DATA/'entities.sqlite3') as db:
        assert db.execute('SELECT surname,birth_date,birth_place FROM person_details ORDER BY entity_id').fetchall()==[
            ('Иванов','15.03.1990','г. Москва'),('Петров','1985',None)]

def test_unknown_initials_and_offset():
    item=person_item();item.update({'фамилия':'Иванов','имя':None,'отчество':None,'дата_рождения':None,'место_рождения':None})
    item['исходные_фрагменты']={'фио':'Иванов И. И.','дата_рождения':None,'место_рождения':None}
    result=parse_person(item,'Иванов И. И.',100)
    assert result['person']['имя'] is None
    assert result['source_spans']['фио']['start']==100
    assert result['normalized_value']=='Иванов'

def test_invented_source_rejected():
    with pytest.raises(ValueError,match='отсутствует'):
        parse_person(person_item(),'Иванов',0)

def test_repeated_source_requires_review():
    result=parse_person(person_item(),TEXT+' '+TEXT,0)
    assert 'несколько раз' in result['note']

def test_old_database_migration_keeps_records(client):
    path=main.DATA/'entities.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE mentions(id INTEGER PRIMARY KEY,entity_id INTEGER NOT NULL,
        original_text TEXT NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,note TEXT);
        INSERT INTO mentions VALUES(1,42,'старый фрагмент',0,14,'');''')
    with main.database() as db:
        assert db.execute('SELECT original_text,field FROM mentions WHERE id=1').fetchone()==('старый фрагмент','entity')
    with main.database() as db:
        assert db.execute('SELECT count(*) FROM mentions').fetchone()[0]==1

@pytest.mark.parametrize('payload', [[],[person_item()]])
def test_person_llm_array_response(monkeypatch,payload):
    monkeypatch.setenv('LM_STUDIO_MODEL','test-model')
    class Response:
        def raise_for_status(self): pass
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):return Response()
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    results=asyncio.run(llm.extract_kind(TEXT,'persons'))
    assert len(results)==len(payload)
