import asyncio
import pytest
from datetime import date
from backend import app as module
from backend.store import Store
from backend.sources import Sources
from fastapi import HTTPException

def test_actual_refresh_failure_preserves_old_data(tmp_path,monkeypatch):
    db=Store(tmp_path/'test.sqlite');monkeypatch.setattr(module,'store',db)
    db.save_holders([dict(code='600000',end_date='2025-01-01',holders=123,scope='普通股',source='test')])
    db.set_status('holders:600000',success_at='2025-01-02T00:00:00+08:00')
    async def fail(code): raise TimeoutError('test source unavailable')
    monkeypatch.setattr(module.sources,'holders',fail)
    asyncio.run(module.refresh_holders('600000'))
    assert db.holders('600000')[0]['holders']==123
    assert 'TimeoutError' in db.status('holders:600000')['error']
    assert db.status('holders:600000')['success_at']=='2025-01-02T00:00:00+08:00'

def test_empty_refresh_is_explicit(tmp_path,monkeypatch):
    db=Store(tmp_path/'test.sqlite');monkeypatch.setattr(module,'store',db)
    async def empty(code): return []
    monkeypatch.setattr(module.sources,'holders',empty)
    asyncio.run(module.refresh_holders('600000'))
    assert db.holders('600000')==[]
    assert db.status('holders:600000')['count']==0

def test_event_range_validation():
    with pytest.raises(HTTPException): asyncio.run(module.events('600000',date(2026,1,2),date(2026,1,1)))
    with pytest.raises(HTTPException): asyncio.run(module.events('600000',date(2000,1,1),date(2026,1,1)))

def test_bse_uses_verified_column_and_leaves_occurrence_unknown():
    async def scenario():
        src=Sources()
        async def company(code): return {'orgId':'9900006121'}
        src.company=company
        async def request(method,url,**kwargs):
            assert kwargs['data']['column']==''
            return {'announcements':[{'secCode':'920047','announcementId':'123','announcementTitle':'2026年半年度报告','announcementTime':1787673600000,'adjunctUrl':'finalpage/2026-08-26/123.PDF'}],'hasMore':False}
        src.request=request
        rows=await src.announcements('920047','2026-08-01','2026-08-31')
        assert rows[0]['published_date']=='2026-08-26'
        assert rows[0]['occurred_date'] is None
        await src.close()
    asyncio.run(scenario())

def test_search_excludes_non_a_shares():
    async def scenario():
        src=Sources()
        async def request(*args,**kwargs):
            return {'QuotationCodeTable':{'Data':[{'Code':'600000','Name':'浦发银行','Classify':'AStock'},{'Code':'00700','Name':'腾讯','Classify':'HK'},{'Code':'000001','Name':'指数','Classify':'Index'}]}}
        src.request=request
        assert [r['code'] for r in await src.search('test')]==['600000']
        await src.close()
    asyncio.run(scenario())

def test_company_identity_cache_survives_restart(tmp_path):
    async def scenario():
        path=tmp_path/'companies.json'
        src=Sources(path)
        async def request(*args,**kwargs):
            return [{'code':'600000','orgId':'gssh0600000','category':'A股'}]
        src.request=request
        assert (await src.company('600000'))['orgId']=='gssh0600000'
        await src.close()
        again=Sources(path)
        async def unexpected(*args,**kwargs): raise AssertionError('cached identity must not request network')
        again.request=unexpected
        assert (await again.company('600000'))['orgId']=='gssh0600000'
        await again.close()
    asyncio.run(scenario())
