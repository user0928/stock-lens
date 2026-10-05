import asyncio
import json
import httpx
import pytest
from backend.sources import Sources
from backend.market import relevance,check_access,AccessFailure,group_events
from backend.store import Store

@pytest.mark.parametrize('title,excerpt,expected',[
 ('浦发银行发布业绩','增长','direct'),('市场快讯','浦发银行（600000）涨超2%','mention'),
 ('合盛硅业质押公告','本次质押600000股，占总股本0.05%',None),
 ('其他公司新闻','600000',None),('浦发银行（600000）公告','','direct'),
 ('市场快讯','银行中600000.SH有所上涨','mention')])
def test_news_relevance(title,excerpt,expected): assert relevance(title,excerpt,'浦发银行','600000')==expected

@pytest.mark.parametrize('status,body,expected',[(401,'unauthorized','login_required'),(403,'forbidden','restricted'),(200,'请先登录查看','login_required'),(200,'请输入验证码','restricted'),(429,'slow down','restricted')])
def test_reading_states(status,body,expected):
    response=httpx.Response(status,text=body,request=httpx.Request('GET','https://example.com'))
    with pytest.raises(AccessFailure) as e: check_access(response)
    assert e.value.state==expected

def test_504_is_not_login():
    r=httpx.Response(504,text='Gateway timeout',request=httpx.Request('GET','https://example.com'))
    with pytest.raises(httpx.HTTPStatusError): check_access(r)

def test_news_about_sms_codes_is_not_a_captcha_challenge():
    r=httpx.Response(200,json={'result':{'content':'银行提醒用户不要分享验证码'}},request=httpx.Request('GET','https://example.com'))
    check_access(r)

def test_trusted_previous_stock_name_is_retained_as_alias(tmp_path):
    db=Store(tmp_path/'test.sqlite');db.save_stock({'code':'600000','name':'旧名','exchange':'SH'});db.save_stock({'code':'600000','name':'新名','exchange':'SH'})
    assert db.stocks()[0]['aliases']==['旧名']
    assert relevance('旧名发布公告','','新名','600000',['旧名'])=='direct'

def test_media_dedup_sanitization_and_irrelevant_share_count():
    async def scenario():
        src=Sources();await src.client.aclose()
        rows=[{'title':'<em>浦发银行</em>发布业绩','content':'原始摘要','date':'2026-09-30 12:00:00','mediaName':'证券时报','url':'https://finance.eastmoney.com/a/1.html'},
              {'title':'浦发银行发布业绩','content':'另一转载摘要','date':'2026-09-30 13:00:00','mediaName':'其他媒体','url':'https://finance.eastmoney.com/a/2.html'},
              {'title':'其他公司质押','content':'质押600000股','date':'2026-09-30 10:00:00','mediaName':'媒体','url':'https://finance.eastmoney.com/a/3.html'}]
        def handler(request):return httpx.Response(200,text='stocklens('+json.dumps({'result':{'cmsArticleWebOld':rows}})+')')
        src.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        items,meta=await src.news_history('600000','浦发银行')
        assert len(items)==1 and items[0]['title']=='浦发银行发布业绩'
        assert len(items[0]['sources'])==2
        assert meta['fetched_candidates']<=100
        await src.close()
    asyncio.run(scenario())

def test_primary_failure_fallback_and_cooldown():
    async def scenario():
        src=Sources();calls=[]
        async def fail(*args): calls.append('primary');raise TimeoutError()
        async def backup(*args): return [{'id':'a'}]
        src.announcements=fail;src.announcements_backup=backup
        for _ in range(2):
            rows,status=await src.events_with_fallback('600000','2026-01-01','2026-03-31')
            assert rows and status['state']=='fallback' and status['primary_issue']['state']=='unavailable'
        assert calls==['primary']
        await src.close()
    asyncio.run(scenario())

def test_both_sources_fail():
    async def scenario():
        src=Sources()
        async def fail(*args):raise TimeoutError()
        src.announcements=fail;src.announcements_backup=fail
        with pytest.raises(AccessFailure) as err:await src.events_with_fallback('600000','2026-01-01','2026-03-31')
        assert err.value.state=='unavailable'
        await src.close()
    asyncio.run(scenario())

def test_event_dedup_keeps_revisions_and_sources():
    rows=[{'id':'1','title':'公司2025年年度报告','published_date':'2026-03-31','source':'巨潮资讯','source_url':'https://a'},
          {'id':'2','title':'浦发银行:公司2025年年度报告','published_date':'2026-03-31','source':'东方财富（公告转载）','source_url':'https://b'},
          {'id':'3','title':'公司2025年年度报告（更正）','published_date':'2026-03-31','source':'巨潮资讯','source_url':'https://c'}]
    grouped=group_events(rows)
    assert len(grouped)==2
    assert len(next(r for r in grouped if r['id']=='1')['sources'])==2

def test_volume_and_no_adjusted_quotes(tmp_path):
    row=Sources.price_row('600000','2026-03-31',10.01,10.18,10.28,9.95,965806,'test','https://source',979340996)
    assert row['volume']==96580600 and row['volume_unit']=='股'
    db=Store(tmp_path/'test.sqlite');db.save_prices([row]);db.save_prices([row])
    assert len(db.prices('600000','2026-01-01','2026-12-31'))==1
    with pytest.raises(ValueError): db.save_prices([row|{'adjustment':'qfq'}])

def test_price_conflict_and_missing_days(tmp_path):
    db=Store(tmp_path/'test.sqlite')
    r=Sources.price_row('600000','2026-03-31',10,10.18,11,9,100,'东方财富','https://a')
    db.save_prices([r,r|{'source':'腾讯证券','close':10.20}])
    assert db.prices('600000','2026-03-31','2026-03-31')[0]['conflict']
    assert db.prices('600000','2026-04-01','2026-04-01')==[]

def test_news_period_and_latest_do_not_mix(tmp_path):
    db=Store(tmp_path/'test.sqlite')
    db.save_news([{'id':'one','code':'600000','published_at':'2026-09-30 10:00:00','published_date':'2026-09-30'}])
    assert db.news('600000','2026-01-01','2026-03-31')==[]
    assert len(db.news('600000'))==1

def test_bse_search_neeq_classification_is_supported():
    async def scenario():
        src=Sources()
        async def request(*a,**k):return {'QuotationCodeTable':{'Data':[{'Code':'920047','Name':'诺思兰德','Classify':'NEEQ','SecurityTypeName':'京A'},{'Code':'830000','Name':'普通新三板','Classify':'NEEQ','SecurityTypeName':'三板'}]}}
        src.request=request
        assert [r['code'] for r in await src.search('920047')]==['920047']
        await src.close()
    asyncio.run(scenario())

def test_tencent_fallback_rejects_adjusted_series():
    async def scenario():
        src=Sources()
        async def request(method,url,**kwargs):
            if 'eastmoney' in url:raise TimeoutError()
            return {'data':{'sh600000':{'qfqday':[['2026-03-31','9','9','9','9','100']]}}}
        src.request=request
        with pytest.raises(AccessFailure):await src.price_history('600000','SH','2026-03-30','2026-03-31')
        await src.close()
    asyncio.run(scenario())
