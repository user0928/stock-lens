"""Additional public adapters. Quotes are always unadjusted; news is never evaluated as code."""
import asyncio
import hashlib
import html
import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
import httpx

def stamp(): return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
def plain(text): return html.unescape(re.sub(r'<[^>]*>', '', text or '')).strip()

class AccessFailure(Exception):
    def __init__(self,state,message,url):
        super().__init__(message); self.state=state; self.url=url

def check_access(response):
    text=response.text[:4000]
    # Inspect response-level messages, not news excerpts that may discuss login/SMS codes.
    try:
        candidate=re.sub(r'^\s*[A-Za-z_][\w]*\(', '',response.text).rstrip().removesuffix(';').removesuffix(')')
        payload=json.loads(candidate)
        if isinstance(payload,dict): text=str(payload.get('message') or payload.get('msg') or payload.get('error') or payload.get('bizMsg') or '')
    except (ValueError,TypeError): pass
    if re.search(r'captcha|验证码|人机验证',text,re.I):
        raise AccessFailure('restricted','来源要求验证码，请在原站查看',str(response.url))
    if response.status_code==401 or re.search(r'请先登录|登录后(?:查看|访问|阅读)|login required',text,re.I):
        raise AccessFailure('login_required','来源要求登录，请在原站登录阅读',str(response.url))
    if response.status_code in (403,429):
        raise AccessFailure('restricted','来源访问受限或请求过于频繁',str(response.url))
    response.raise_for_status()

def issue(exc,url):
    state=getattr(exc,'state','unavailable')
    message=str(exc) if isinstance(exc,AccessFailure) else ('来源暂时超时' if isinstance(exc,(TimeoutError,httpx.TimeoutException)) else '来源暂不可用')
    return {'state':state,'message':message,'reading_url':url}

def relevance(title,excerpt,name,code,aliases=()):
    # A naked six-digit number may be a share count, not a security identifier.
    names=[n for n in dict.fromkeys([name,*aliases]) if n and n!=code]
    tag=rf'(?:[（(](?:SH|SZ|BJ)?{re.escape(code)}[）)]|(?<![A-Za-z0-9]){re.escape(code)}\.(?:SH|SZ|BJ)(?![A-Za-z0-9]))'
    if any(n in title for n in names) or re.search(tag,title,re.I): return 'direct'
    if any(n in excerpt for n in names) or re.search(tag,excerpt,re.I): return 'mention'
    return None

def group_events(rows):
    groups={}
    for row in rows:
        title=row['title']
        if row.get('source','').startswith('东方财富'): title=re.sub(r'^[^:：]{1,15}[:：]','',title)
        key=(row['published_date'],re.sub(r'\s+','',title))
        old=groups.get(key)
        if old is None: groups[key]=dict(row,sources=[{'source':row['source'],'url':row['source_url']}])
        else:
            refs=old['sources']
            ref={'source':row['source'],'url':row['source_url']}
            if ref not in refs: refs.append(ref)
            if row['source']=='巨潮资讯': groups[key]=dict(row,sources=refs)
    return sorted(groups.values(),key=lambda r:r['published_date'],reverse=True)

class MarketSources:
    async def announcements_backup(self,code,start,end):
        from .sources import classify
        result=[]
        for page in range(1,101):
            raw=await self.request('GET','https://np-anotice-stock.eastmoney.com/api/security/ann',
                params={'sr':-1,'page_size':50,'page_index':page,'ann_type':'A','stock_list':code,'begin_time':start,'end_time':end},timeout=10)
            if not raw.get('success'): raise ValueError('备用公告接口无有效响应')
            data=raw.get('data') or {}; rows=data.get('list') or []
            for r in rows:
                if not any(x.get('stock_code')==code for x in r.get('codes',[])): continue
                published=(r.get('notice_date') or '')[:10]
                if not start<=published<=end: continue
                art=r.get('art_code','')
                if not re.fullmatch(r'AN\d+',art): continue
                title=plain(r['title'])
                result.append({'id':'em:'+art,'code':code,'title':title,'published_date':published,
                    'occurred_date':None,'category':classify(title),'kind':'正式公告','source':'东方财富（公告转载）',
                    'source_role':'mirror','source_url':f'https://data.eastmoney.com/notices/detail/{code}/{art}.html',
                    'excerpt':title,'excerpt_type':'公告标题摘录','fetched_at':stamp()})
            if page*50>=int(data.get('total_hits',0)): break
            if not rows: raise ValueError('备用公告分页提前结束')
            await asyncio.sleep(.2)
        else: raise ValueError('公告超过分页上限，请缩小范围')
        return result

    async def events_with_fallback(self,code,start,end):
        primary_issue=None
        if time.monotonic()<getattr(self,'_cninfo_until',0):
            primary_issue=getattr(self,'_cninfo_issue',{'state':'unavailable','message':'主来源冷却中','reading_url':'https://www.cninfo.com.cn/'})
        else:
            try:
                rows=await asyncio.wait_for(self.announcements(code,start,end),12)
                return rows,{'state':'live' if rows else 'empty','source':'巨潮资讯','primary_issue':None,'reading_url':'https://www.cninfo.com.cn/'}
            except Exception as e:
                primary_issue=issue(e,'https://www.cninfo.com.cn/')
                self._cninfo_issue=primary_issue;self._cninfo_until=time.monotonic()+180
        try:
            rows=await self.announcements_backup(code,start,end)
            return rows,{'state':'fallback','source':'东方财富（公告转载）','primary_issue':primary_issue,'reading_url':f'https://data.eastmoney.com/notices/stock/{code}.html'}
        except Exception as e:
            failure=AccessFailure(getattr(e,'state','unavailable'),'主来源与备用来源均未取得本次数据','https://www.cninfo.com.cn/')
            failure.primary_issue=primary_issue
            raise failure from e

    async def price_history(self,code,market,start,end):
        warnings=[]
        try:
            raw=await self.request('GET','https://push2his.eastmoney.com/api/qt/stock/kline/get',
                params={'secid':('1.' if market=='SH' else '0.')+code,'klt':101,'fqt':0,'beg':start.replace('-',''),'end':end.replace('-',''),
                        'lmt':10000,'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'},
                headers={'Referer':'https://quote.eastmoney.com/'},timeout=8,retries=0)
            data=raw.get('data') or {}
            if data.get('code')!=code: raise ValueError('行情代码不匹配或无数据')
            rows=[]
            for line in data.get('klines') or []:
                v=line.split(',')
                if len(v)<7 or not start<=v[0]<=end: continue
                rows.append(self.price_row(code,v[0],v[1],v[2],v[3],v[4],v[5],'东方财富',f'https://quote.eastmoney.com/{market.lower()}{code}.html',v[6]))
            if rows: return rows,{'state':'live','source':'东方财富','adjustment':'none','warnings':[]}
            warnings.append('东方财富未返回该区间行情')
        except Exception as e: warnings.append('东方财富行情暂未取得：'+issue(e,'')['message'])
        rows=[]; missing_segments=[];cursor=date.fromisoformat(start);finish=date.fromisoformat(end)
        symbol=market.lower()+code
        try:
            while cursor<=finish:
                stop=min(cursor+timedelta(days=700),finish)
                raw=await self.request('GET','https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                    params={'param':f'{symbol},day,{cursor.isoformat()},{stop.isoformat()},640,'},timeout=10,retries=0)
                series=(raw.get('data') or {}).get(symbol) or {}
                accepted=0
                # Never accept qfqday here: the trailing empty adjustment requests actual historical prices.
                for v in series.get('day') or []:
                    if len(v)<6 or not cursor.isoformat()<=v[0]<=stop.isoformat(): continue
                    rows.append(self.price_row(code,*v[:6],'腾讯证券',f'https://gu.qq.com/{symbol}'))
                    accepted+=1
                if not accepted: missing_segments.append([cursor.isoformat(),stop.isoformat()])
                cursor=stop+timedelta(days=1)
            if rows:
                rows=list({r['date']:r for r in rows}.values())
                sparse=len(rows)<3 and (finish-date.fromisoformat(start)).days>14
                if missing_segments or sparse: warnings.append(f'仅取得{len(rows)}个交易日；部分日期区间未返回行情，不代表完整历史')
                return rows,{'state':'partial' if missing_segments or sparse else 'fallback','source':'腾讯证券','adjustment':'none','warnings':warnings,'missing_segments':missing_segments}
        except Exception as e:
            warnings.append('腾讯行情暂未取得：'+issue(e,'')['message'])
            if rows: return rows,{'state':'partial','source':'腾讯证券','adjustment':'none','warnings':warnings+['部分日期区间未完成采集']}
        raise AccessFailure('unavailable','；'.join(warnings+['该区间未取得日行情，不补零。']),f'https://quote.eastmoney.com/{market.lower()}{code}.html')

    @staticmethod
    def price_row(code,day,opening,close,high,low,volume,source,url,amount=None):
        nums=list(map(float,[opening,close,high,low,volume]))
        if not all(math.isfinite(n) for n in nums) or min(nums[:4])<=0 or nums[4]<0: raise ValueError('无效行情数值')
        return {'code':code,'date':day,'open':nums[0],'close':nums[1],'high':nums[2],'low':nums[3],
                'volume':round(nums[4]*100),'volume_unit':'股','raw_volume':nums[4],'raw_volume_unit':'手',
                'amount':float(amount) if amount else None,'adjustment':'none','source':source,'source_url':url,'fetched_at':stamp()}

    async def news_history(self,code,name,aliases=()):
        rows=[];issues=[];fetched_count=0
        names=list(dict.fromkeys([name,*aliases]))[:3]
        queries=[(n,20*(3//len(names)+(1 if i<3%len(names) else 0))) for i,n in enumerate(names)]+[(code,40)]
        # At most 100 returned candidates across both searches. Filtering may leave fewer.
        for query,budget in queries:
            for page in range(1,budget//20+1):
                payload={'uid':'','keyword':query,'type':['cmsArticleWebOld'],'client':'web','clientType':'web','clientVersion':'curr',
                    'param':{'cmsArticleWebOld':{'searchScope':'default','sort':'time','pageIndex':page,'pageSize':20,'preTag':'','postTag':''}}}
                try:
                    response=await self.client.get('https://search-api-web.eastmoney.com/search/jsonp',
                        params={'cb':'stocklens','param':json.dumps(payload,ensure_ascii=False),'_':int(time.time()*1000)},
                        headers={'Referer':'https://so.eastmoney.com/'},timeout=12)
                    check_access(response)
                    match=re.fullmatch(r'\s*stocklens\((.*)\);?\s*',response.text,re.S)
                    if not match: raise ValueError('新闻响应格式变化')
                    raw=json.loads(match.group(1));data=(raw.get('result') or {}).get('cmsArticleWebOld')
                    if not isinstance(data,list): raise ValueError('新闻响应缺少列表')
                    data=data[:20]
                    fetched_count+=len(data)
                    for r in data:
                        title=plain(r.get('title'));excerpt=plain(r.get('content'))
                        relation=relevance(title,excerpt,name,code,aliases)
                        if relation is None: continue
                        url=r.get('url','');host=urlparse(url).hostname or ''
                        if urlparse(url).scheme not in ('http','https') or not (host=='eastmoney.com' or host.endswith('.eastmoney.com')): continue
                        published=r.get('date','')
                        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?',published): continue
                        key=hashlib.sha256((code+re.sub(r'\s+','',title)+published[:10]).encode()).hexdigest()[:24]
                        rows.append({'id':'news:'+key,'code':code,'title':title,'excerpt':excerpt,'published_at':published,
                            'published_date':published[:10],'occurred_date':None,'kind':'媒体报道','relation':relation,
                            'media':plain(r.get('mediaName')) or '来源未注明','source':'东方财富新闻检索','source_role':'reprint',
                            'source_url':url,'fetched_at':stamp()})
                    if len(data)<20: break
                    await asyncio.sleep(.2)
                except Exception as e:
                    issues.append(issue(e,f'https://so.eastmoney.com/news/s?keyword={code}'));break
        grouped={}
        for r in sorted(rows,key=lambda r:r['published_at'],reverse=True):
            ref={'media':r['media'],'url':r['source_url'],'published_at':r['published_at']}
            if r['id'] not in grouped: grouped[r['id']]=dict(r,sources=[ref])
            elif ref not in grouped[r['id']]['sources']: grouped[r['id']]['sources'].append(ref)
        if not grouped and issues: raise AccessFailure(issues[0]['state'],issues[0]['message'],issues[0]['reading_url'])
        items=list(grouped.values())[:100]
        return items,{'state':'partial' if issues else ('live' if items else 'empty'),'source':'东方财富新闻检索',
            'warnings':[i['message'] for i in issues],'fetched_candidates':fetched_count,'limit':100,
            'coverage_start':min((r['published_date'] for r in items),default=None),'coverage_end':max((r['published_date'] for r in items),default=None),
            'reading_url':f'https://so.eastmoney.com/news/s?keyword={code}'}
