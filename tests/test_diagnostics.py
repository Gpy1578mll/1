import asyncio
import httpx
import pytest
from app import main, llm

@pytest.mark.parametrize('failure,expected', [
    (httpx.ConnectError('private request details'),'Не удалось подключиться'),
    (httpx.ReadTimeout('private document text'),'не ответила'),
    (httpx.HTTPStatusError('private server response',request=httpx.Request('POST','http://localhost/v1/chat/completions'),
                          response=httpx.Response(400)), 'HTTP 400'),
])
def test_model_failures_are_actionable_and_do_not_expose_details(monkeypatch,failure,expected):
    monkeypatch.setenv('LM_STUDIO_MODEL','test-model')
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):raise failure
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    with pytest.raises(llm.ExtractionError,match=expected) as error:
        asyncio.run(llm.extract_kind('Документ','persons'))
    assert 'private' not in str(error.value)

def test_failure_stage_reaches_review_without_database(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def fail(text):raise llm.ExtractionError('LM Studio вернула HTTP 400.')
    monkeypatch.setattr(main,'persons',fail)
    main.JOBS['diagnostic']={'text':'Иванов','status':'processing','entities':[]}
    asyncio.run(main.process('diagnostic'))
    job=main.JOBS.pop('diagnostic')
    assert job['status']=='error'
    assert job['error']=='Сведения о людях: LM Studio вернула HTTP 400.'
    assert not (tmp_path/'entities.sqlite3').exists()

@pytest.mark.parametrize('body,message', [({},'choices'),({'choices':[{'finish_reason':'stop','message':{'content':None}}]},'message.content'),
    ({'choices':[{'finish_reason':'stop','message':{'content':'not json private'}}]},'невалидный JSON')])
def test_invalid_api_responses(monkeypatch,body,message):
    monkeypatch.setenv('LM_STUDIO_MODEL','test-model')
    class Response:
        def raise_for_status(self):pass
        def json(self):return body
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):return Response()
    monkeypatch.setattr(llm.httpx,'AsyncClient',Client)
    with pytest.raises(llm.ExtractionError,match=message) as error:
        asyncio.run(llm.extract_kind('Документ','persons'))
    assert 'private' not in str(error.value)
