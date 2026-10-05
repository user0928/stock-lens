"""Public read-only source adapters. No claims of licensed API availability."""
import asyncio
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
import httpx
from .market import MarketSources, check_access

CN_TZ = timezone(timedelta(hours=8))
def now():
    return datetime.now(CN_TZ).isoformat(timespec='seconds')

def today():
    return datetime.now(CN_TZ).date().isoformat()

def exchange(code):
    if re.fullmatch(r'(600|601|603|605|688|689)\d{3}', code): return 'SH'
    if re.fullmatch(r'(000|001|002|003|300|301)\d{3}', code): return 'SZ'
    if re.fullmatch(r'(920|430|83\d|87\d|88\d)\d{3}', code): return 'BJ'
    raise ValueError('仅支持沪深北 A 股代码')

def classify(title):
    rules = [('诉讼处罚',r'诉讼|仲裁|处罚|立案|监管函|警示函'),
             ('重组并购',r'重组|收购|兼并|合并|重大资产'),
             ('增减持',r'增持|减持'), ('回购',r'回购'),
             ('重大合同',r'重大合同|中标|重大项目|战略合作'),
             ('业绩',r'年度报告|季度报告|半年度报告|业绩|分红|利润分配|权益分派')]
    return next((label for label,pattern in rules if re.search(pattern,title)), '其他公告')

class Sources(MarketSources):
    def __init__(self,company_cache=None):
        self._companies={}
        self.company_cache=Path(company_cache) if company_cache else None
        if self.company_cache and self.company_cache.exists():
            try:
                cache=json.loads(self.company_cache.read_text(encoding='utf-8'))
                self._companies={code:row for code,row in cache.items() if re.fullmatch(r'\d{6}',code) and re.fullmatch(r'[A-Za-z0-9]+',row.get('orgId',''))}
            except (ValueError,AttributeError): pass
        self.client = httpx.AsyncClient(timeout=25, follow_redirects=True,
            headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/'})

    async def close(self): await self.client.aclose()

    async def request(self, method, url, retries=1, **kwargs):
        for attempt in range(retries+1):
            try:
                r = await self.client.request(method,url,**kwargs)
                check_access(r)
                return r.json()
            except (httpx.HTTPError, ValueError):
                if attempt>=retries: raise
                await asyncio.sleep(0.5*(2**attempt))

    async def search(self, query):
        raw = await self.request('GET','https://searchapi.eastmoney.com/api/suggest/get',
            params={'input':query,'type':14,'count':15})
        found=[]
        for row in (raw.get('QuotationCodeTable',{}).get('Data') or []):
            if row.get('Classify') != 'AStock' and row.get('SecurityTypeName')!='京A': continue
            try: market=exchange(row['Code'])
            except ValueError: continue
            found.append({'code':row['Code'],'name':row['Name'],'exchange':market})
        return found

    async def holders(self, code):
        market=exchange(code)
        rows=[]
        for page in range(1,51):
            params={'reportName':'RPT_HOLDERNUM_DET','columns':'ALL',
                'filter':f'(SECURITY_CODE="{code}")','pageSize':500,'pageNumber':page,
                'sortColumns':'END_DATE','sortTypes':'-1'}
            url='https://datacenter-web.eastmoney.com/api/data/v1/get'
            data=await self.request('GET',url,params=params)
            if not data.get('success'):
                raise ValueError('股东户数来源未返回有效结果：'+str(data.get('message','未知错误')))
            result=data.get('result') or {}
            for r in result.get('data') or []:
                n=r.get('HOLDER_NUM')
                if n is None: continue
                if int(n)!=float(n) or int(n)<=0: continue
                end=(r.get('END_DATE') or '')[:10]
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',end): continue
                rows.append({'code':code,'exchange':market,'name':r['SECURITY_NAME_ABBR'],
                    'end_date':end,'disclosure_date':(r.get('HOLD_NOTICE_DATE') or '')[:10] or None,
                    'holders':int(n),'scope':'来源未明确（待原文核对）',
                    'source':'东方财富','source_url':str(httpx.URL(url,params=params)),
                    'page_url':f'https://data.eastmoney.com/gdhs/detail/{code}.html',
                    'fetched_at':now(),'verified':False})
            if page>=result.get('pages',1): break
        else: raise ValueError('股东历史超过分页上限，未作为完整结果保存')
        return rows

    async def company(self, code):
        if code in self._companies: return self._companies[code]
        rows=await self.request('POST','https://www.cninfo.com.cn/new/information/topSearch/query',
            data={'keyWord':code,'maxNum':10})
        company=next((x for x in rows if x.get('code')==code and x.get('category')=='A股'),None)
        if company:
            self._companies[code]=company
            if self.company_cache:
                self.company_cache.parent.mkdir(parents=True,exist_ok=True)
                temp=self.company_cache.with_suffix('.tmp')
                temp.write_text(json.dumps(self._companies,ensure_ascii=False),encoding='utf-8')
                temp.replace(self.company_cache)
        return company

    async def announcements(self, code, start, end):
        company=await self.company(code)
        if not company: raise ValueError('巨潮未找到对应公司；该期间公告未取得')
        rows=[]
        for page in range(1,101):
            raw=await self.request('POST','https://www.cninfo.com.cn/new/hisAnnouncement/query',data={
                'pageNum':page,'pageSize':30,'tabName':'fulltext',
                # CNINFO's BSE records are returned by the unscoped column;
                # column=bse silently returns an empty result (verified live).
                'column':{'SH':'sse','SZ':'szse','BJ':''}[exchange(code)],
                'stock':f"{code},{company['orgId']}",'searchkey':'','secid':'','plate':'',
                'category':'','trade':'','seDate':f'{start}~{end}',
                'sortName':'time','sortType':'desc','isHLtitle':'false'})
            if 'announcements' not in raw: raise ValueError('公告接口结构变化')
            for a in raw.get('announcements') or []:
                title=re.sub('<[^>]+>','',a['announcementTitle'])
                published=datetime.fromtimestamp(a['announcementTime']/1000,CN_TZ).date().isoformat()
                if not start<=published<=end: continue
                if a.get('secCode') != code and a.get('orgId') != company['orgId']: continue
                attachment=a.get('adjunctUrl','')
                if not re.fullmatch(r'finalpage/[\w./-]+',attachment): continue
                rows.append({'id':'cninfo:'+a['announcementId'],'code':code,'title':title,
                    'published_date':published,'occurred_date':None,'category':classify(title),
                    'kind':'正式公告','source':'巨潮资讯','source_url':'https://static.cninfo.com.cn/'+attachment,
                    'excerpt':title,'excerpt_type':'公告标题摘录','original_code':a.get('secCode'),'fetched_at':now()})
            if not raw.get('hasMore'): break
            await asyncio.sleep(0.12)
        else: raise ValueError('公告超过分页上限，请缩小时间范围')
        return list({r['id']:r for r in rows}.values())
