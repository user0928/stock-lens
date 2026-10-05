import asyncio
import json
import os
import hashlib
import secrets
import re
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from datetime import date, timedelta, datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from .sources import Sources, exchange, now, today
from .store import Store
from .market import group_events, issue

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('STOCK_LENS_DATA_DIR',str(ROOT/'data')))
store=Store(os.getenv('STOCK_LENS_DB',str(DATA/'stock-lens.sqlite')))
sources=Sources(DATA/'company-cache.json')
tasks={}
limiter=asyncio.Semaphore(3)
search_cache=OrderedDict()
request_windows=OrderedDict()
MAX_TASKS=48
SAMPLES=[{'code':c,'name':n,'exchange':exchange(c)} for c,n in [('600000','浦发银行'),('600519','贵州茅台'),('000001','平安银行'),('000858','五粮液'),('920047','诺思兰德'),('920982','锦波生物')]]
for sample in SAMPLES: store.save_stock(sample)

def validate(code):
    try: exchange(code)
    except ValueError as e: raise HTTPException(400,str(e))

def fresh(status,hours=24):
    stamp=status.get('success_at')
    return bool(stamp and (datetime.fromisoformat(now())-datetime.fromisoformat(stamp)).total_seconds()<hours*3600)

async def refresh_holders(code):
    key='holders:'+code
    store.set_status(key,attempt_at=now(),error=None)
    try:
        async with limiter: rows=await sources.holders(code)
        store.save_holders(rows)
        if rows: store.save_stock({k:rows[0][k] for k in ('code','name','exchange')})
        store.set_status(key,success_at=now(),error=None,count=len(rows))
    except Exception as e: store.set_status(key,error=f'更新失败：{type(e).__name__} · {str(e)[:180]}')

async def refresh_events(code,start,end):
    key=f'events:v3:{code}:{start}:{end}'
    store.set_status(key,attempt_at=now(),error=None)
    try:
        async with limiter: rows,meta=await sources.events_with_fallback(code,start,end)
        store.save_events(rows)
        store.set_status(key,success_at=now(),error=None,count=len(rows),coverage_start=start,coverage_end=end,**({'warnings':[],'message':None}|meta))
    except Exception as e:
        meta=issue(e,'https://www.cninfo.com.cn/')
        store.set_status(key,error=meta['message'],**meta)

async def refresh_prices(code,start,end):
    key=f'prices:{code}:{start}:{end}'
    store.set_status(key,attempt_at=now(),error=None)
    try:
        async with limiter: rows,meta=await sources.price_history(code,exchange(code),start,end)
        store.save_prices(rows)
        store.set_status(key,success_at=now(),error=None,count=len(rows),coverage_start=min((r['date'] for r in rows),default=None),coverage_end=max((r['date'] for r in rows),default=None),**({'missing_segments':[],'reading_url':None,'message':None}|meta))
    except Exception as e:
        meta=issue(e,f'https://quote.eastmoney.com/{exchange(code).lower()}{code}.html')
        store.set_status(key,error=str(e)[:240],**meta)

async def refresh_news(code):
    key='news:'+code
    store.set_status(key,attempt_at=now(),error=None)
    try:
        company=next((r for r in store.stocks() if r['code']==code),{'name':code})
        async with limiter: rows,meta=await sources.news_history(code,company['name'],company.get('aliases',[]))
        store.save_news(rows)
        store.set_status(key,success_at=now(),error=None,count=len(rows),**({'message':None}|meta))
    except Exception as e:
        meta=issue(e,f'https://so.eastmoney.com/news/s?keyword={code}')
        store.set_status(key,error=meta['message'],**meta)

def recent(status,seconds=300):
    return bool(status.get('attempt_at') and (datetime.fromisoformat(now())-datetime.fromisoformat(status['attempt_at'])).total_seconds()<seconds)

def response_status(key,status,rows):
    cached=max((r.get('fetched_at','') for r in rows),default=None)
    return status|{'refreshing':key in tasks,'cached_at':cached,'has_cache':bool(rows),'busy':len(tasks)>=MAX_TASKS}

def launch(key,coroutine):
    if key in tasks and not tasks[key].done():
        coroutine.close()
        return
    if len(tasks)>=MAX_TASKS:
        coroutine.close()
        return
    task=asyncio.create_task(coroutine)
    tasks[key]=task
    task.add_done_callback(lambda t: tasks.pop(key,None) if tasks.get(key) is t else None)

async def daily():
    while True:
        for code in store.watched():
            if not fresh(store.status('holders:'+code)):
                launch('holders:'+code,refresh_holders(code))
            end=today(); start=(date.fromisoformat(end)-timedelta(days=7)).isoformat()
            key=f'events:v3:{code}:{start}:{end}'
            if not fresh(store.status(key)): launch(key,refresh_events(code,start,end))
            if not fresh(store.status('news:'+code),6): launch('news:'+code,refresh_news(code))
            pkey=f'prices:{code}:{start}:{end}'
            if not fresh(store.status(pkey)): launch(pkey,refresh_prices(code,start,end))
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app):
    worker=asyncio.create_task(daily())
    yield
    worker.cancel()
    pending=list(tasks.values())
    for task in pending: task.cancel()
    await asyncio.gather(worker,*pending,return_exceptions=True)
    await sources.close()

app=FastAPI(title='股东观察 Stock Lens',lifespan=lifespan)
app.add_middleware(GZipMiddleware,minimum_size=1000)

@app.middleware('http')
async def same_origin(request:Request,call_next):
    from fastapi.responses import JSONResponse
    if request.url.path.startswith('/api/') and request.url.path!='/api/health':
        client=request.client.host if request.client else 'unknown'
        tick=time.monotonic()
        window=request_windows.setdefault(client,deque())
        while window and window[0]<tick-60: window.popleft()
        request_windows.move_to_end(client)
        if len(request_windows)>4096: request_windows.popitem(last=False)
        if len(window)>=180:
            return JSONResponse({'detail':'请求过于频繁，请稍后重试'},status_code=429,headers={'Retry-After':'60'})
        window.append(tick)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'仅允许同源操作'},status_code=403)
    if request.method in ('POST','PUT') and request.url.path.startswith('/api/') and len(tasks)>=MAX_TASKS:
        return JSONResponse({'detail':'采集队列繁忙，请稍后重试'},status_code=503,headers={'Retry-After':'30'})
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    if request.url.path in ('/','/index.html','/sw.js'): response.headers['Cache-Control']='no-cache'
    return response

@app.get('/api/health')
async def health(): return {'ok':True,'time':now()}

@app.get('/api/search')
async def search(q:str=Query('',max_length=40)):
    q=q.strip()
    if not q: return {'items':SAMPLES,'warning':None}
    cached=search_cache.get(q)
    if cached and time.monotonic()-cached[0]<300:
        return {'items':cached[1],'warning':None}
    try:
        async with limiter: rows=await sources.search(q)
        for r in rows: store.save_stock(r)
        search_cache[q]=(time.monotonic(),rows)
        search_cache.move_to_end(q)
        if len(search_cache)>128: search_cache.popitem(last=False)
        return {'items':rows,'warning':None}
    except Exception:
        return {'items':[r for r in store.stocks() if q.lower() in (r['name']+r['code']).lower()],
                'warning':'在线搜索暂不可用，仅显示已缓存公司'}

@app.get('/api/stocks/{code}')
async def stock(code:str):
    validate(code)
    key='holders:'+code
    status=store.status(key)
    # Throttle repeated failures to one attempt per hour.
    recent=status.get('attempt_at') and (datetime.fromisoformat(now())-datetime.fromisoformat(status['attempt_at'])).total_seconds()<3600
    if not fresh(status) and not recent: launch(key,refresh_holders(code))
    rows=store.holders(code)
    audit_file=ROOT/'validation/audit.json'
    if audit_file.exists():
        try:
            checks=json.loads(audit_file.read_text(encoding='utf-8'))
            checked={(r['code'],r['end_date'],r['holders']):r for r in checks if r.get('status')=='verified'}
            for r in rows:
                a=checked.get((code,r['end_date'],r['holders']))
                if a and a['disclosure_date']==r['disclosure_date']:
                    r.update(verified=True,original_url=a['original_url'],verified_scope=a.get('scope'),evidence=a.get('evidence'))
        except (ValueError,KeyError): pass
    return {'stock':next((s for s in store.stocks() if s['code']==code),{'code':code,'name':code,'exchange':exchange(code)}),
            'holders':rows,'status':status|{'refreshing':key in tasks},
            'coverage':'仅展示来源已返回的披露记录，不代表完整历史；未核实口径的变化率仅供对照。'}

@app.post('/api/stocks/{code}/refresh')
async def manual_refresh(code:str):
    validate(code)
    key='holders:'+code
    status=store.status(key)
    if status.get('attempt_at') and (datetime.fromisoformat(now())-datetime.fromisoformat(status['attempt_at'])).total_seconds()<30:
        return {'queued':False,'message':'请在30秒后重试'}
    launch(key,refresh_holders(code))
    return {'queued':True}

@app.get('/api/stocks/{code}/events')
async def events(code:str,start:date,end:date):
    validate(code)
    if start>end or (end-start).days>3660: raise HTTPException(400,'日期范围须为0至3660天')
    s,e=start.isoformat(),end.isoformat()
    key=f'events:v3:{code}:{s}:{e}'
    status=store.status(key)
    recent=status.get('attempt_at') and (datetime.fromisoformat(now())-datetime.fromisoformat(status['attempt_at'])).total_seconds()<3600
    if not fresh(status) and not recent: launch(key,refresh_events(code,s,e))
    rows=group_events(store.events(code,s,e))
    return {'items':rows,'status':response_status(key,status,rows),
            'note':'按正式披露日期筛选；事件发生日期未提取。备用来源为公告转载，保留所有来源入口。'}

@app.get('/api/stocks/{code}/prices')
async def prices(code:str,start:date,end:date):
    validate(code)
    if start>end or (end-start).days>20000: raise HTTPException(400,'行情日期范围不合法')
    s,e=start.isoformat(),end.isoformat();key=f'prices:{code}:{s}:{e}'
    status=store.status(key)
    if not fresh(status) and not recent(status): launch(key,refresh_prices(code,s,e))
    rows=store.prices(code,s,e)
    return {'items':rows,'status':response_status(key,status,rows),'adjustment':'none','volume_unit':'股',
            'note':'不复权日行情。缺失日期不补值，未保证完整交易日覆盖。'}

@app.get('/api/stocks/{code}/news')
async def news(code:str,mode:str=Query('period',pattern='^(period|latest)$'),start:date|None=None,end:date|None=None):
    validate(code)
    if mode=='period' and (start is None or end is None or start>end): raise HTTPException(400,'同期新闻需要有效起止日期')
    key='news:'+code;status=store.status(key)
    if not fresh(status,6) and not recent(status): launch(key,refresh_news(code))
    rows=store.news(code,start.isoformat() if mode=='period' else None,end.isoformat() if mode=='period' else None)
    return {'items':rows,'status':response_status(key,status,rows),'mode':mode,
            'note':'按平台标注的发布时间筛选，每次最多采集100条候选报道；未检索到不等于当时没有新闻。'}

@app.post('/api/stocks/{code}/news/refresh')
async def manual_news_refresh(code:str):
    validate(code);key='news:'+code
    if recent(store.status(key),30): return {'queued':False,'message':'请在30秒后重试新闻'}
    launch(key,refresh_news(code));return {'queued':True}

@app.post('/api/stocks/{code}/prices/refresh')
async def manual_prices_refresh(code:str,start:date,end:date):
    validate(code)
    if start>end or (end-start).days>20000: raise HTTPException(400,'行情日期范围不合法')
    s,e=start.isoformat(),end.isoformat();key=f'prices:{code}:{s}:{e}'
    if recent(store.status(key),30): return {'queued':False,'message':'请在30秒后重试行情'}
    launch(key,refresh_prices(code,s,e));return {'queued':True}

class Watchlist(BaseModel):
    codes:list[str]=Field(max_length=100)

@app.post('/api/stocks/{code}/events/refresh')
async def manual_events_refresh(code:str,start:date,end:date):
    validate(code)
    if start>end or (end-start).days>3660: raise HTTPException(400,'日期范围须为0至3660天')
    s,e=start.isoformat(),end.isoformat()
    key=f'events:v3:{code}:{s}:{e}'
    status=store.status(key)
    if status.get('attempt_at') and (datetime.fromisoformat(now())-datetime.fromisoformat(status['attempt_at'])).total_seconds()<30:
        return {'queued':False,'message':'公告正在更新或刚刚更新，请在30秒后重试'}
    launch(key,refresh_events(code,s,e))
    return {'queued':True}

@app.put('/api/watchlist')
async def watchlist(body:Watchlist,request:Request,response:Response):
    for c in body.codes: validate(c)
    token=request.cookies.get('stock_lens_client','')
    if not re.fullmatch(r'[0-9a-f]{64}',token): token=secrets.token_hex(32)
    owner=hashlib.sha256(token.encode()).hexdigest()
    expires=(datetime.fromisoformat(now())+timedelta(days=30)).isoformat(timespec='seconds')
    store.watch(body.codes,owner,expires)
    response.set_cookie('stock_lens_client',token,max_age=30*86400,httponly=True,secure=request.url.scheme=='https',samesite='lax')
    for c in body.codes:
        if not fresh(store.status('holders:'+c)): launch('holders:'+c,refresh_holders(c))
    return {'ok':True,'count':len(set(body.codes))}

if (ROOT/'dist').exists(): app.mount('/',StaticFiles(directory=ROOT/'dist',html=True),name='web')
