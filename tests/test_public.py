"""Public-edition regression checks, without upstream network calls."""
import asyncio
from datetime import datetime, timedelta
import httpx
from backend import app as module
from backend.sources import now
from backend.store import Store


def test_browser_watchlists_cannot_overwrite_other_visitors(tmp_path,monkeypatch):
    db=Store(tmp_path/'public.sqlite')
    monkeypatch.setattr(module,'store',db)
    monkeypatch.setattr(module,'launch',lambda key,coro:coro.close())
    async def scenario():
        transport=httpx.ASGITransport(app=module.app)
        async with httpx.AsyncClient(transport=transport,base_url='http://test') as a, httpx.AsyncClient(transport=transport,base_url='http://test') as b:
            first=await a.put('/api/watchlist',json={'codes':['600000']})
            assert first.status_code==200
            assert 'HttpOnly' in first.headers['set-cookie'] and 'SameSite=lax' in first.headers['set-cookie']
            await b.put('/api/watchlist',json={'codes':['000001']})
            assert set(db.watched())=={'600000','000001'}
            await a.put('/api/watchlist',json={'codes':[]})
            assert db.watched()==['000001']
            await b.put('/api/watchlist',json={'codes':[]})
            assert db.watched()==[]
    asyncio.run(scenario())


def test_subscription_expiry_and_legacy_preservation(tmp_path):
    db=Store(tmp_path/'watch.sqlite')
    expired=(datetime.fromisoformat(now())-timedelta(days=1)).isoformat()
    future=(datetime.fromisoformat(now())+timedelta(days=1)).isoformat()
    db.watch(['600519'])
    db.watch(['600000'],'expired',expired)
    db.watch(['000001'],'active',future)
    assert set(db.watched())=={'600519','000001'}


def test_security_headers_and_cross_origin_rejection():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app),base_url='http://test') as client:
            health=await client.get('/api/health')
            assert health.status_code==200 and health.headers['x-content-type-options']=='nosniff'
            forbidden=await client.put('/api/watchlist',headers={'origin':'https://other.example'},json={'codes':[]})
            assert forbidden.status_code==403
    asyncio.run(scenario())


def test_background_queue_is_bounded(monkeypatch):
    monkeypatch.setattr(module,'tasks',{str(i):None for i in range(module.MAX_TASKS)})
    reached=[]
    async def extra(): reached.append(True)
    async def scenario():
        module.launch('overflow',extra())
        await asyncio.sleep(0)
        assert 'overflow' not in module.tasks and not reached
    asyncio.run(scenario())


def test_api_request_budget_returns_retry_after(monkeypatch):
    from collections import OrderedDict
    monkeypatch.setattr(module,'request_windows',OrderedDict())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app),base_url='http://test') as client:
            for _ in range(180): assert (await client.get('/api/search')).status_code==200
            limited=await client.get('/api/search')
            assert limited.status_code==429 and limited.headers['retry-after']=='60'
            assert (await client.get('/api/health')).status_code==200
    asyncio.run(scenario())


def test_search_cache_avoids_repeated_upstream_reads(tmp_path,monkeypatch):
    from collections import OrderedDict
    monkeypatch.setattr(module,'store',Store(tmp_path/'search.sqlite'))
    monkeypatch.setattr(module,'search_cache',OrderedDict())
    calls=[]
    async def fake(query):
        calls.append(query)
        return [{'code':'600000','name':'浦发银行','exchange':'SH'}]
    monkeypatch.setattr(module.sources,'search',fake)
    async def scenario():
        assert (await module.search('浦发银行'))['items']
        assert (await module.search('浦发银行'))['items']
        assert calls==['浦发银行']
    asyncio.run(scenario())
