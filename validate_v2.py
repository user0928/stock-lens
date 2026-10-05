"""Bounded live v2 audit, using public sources and preserving raw evidence."""
import asyncio,json
from pathlib import Path
from datetime import date,timedelta
from backend.sources import Sources,exchange,now
from backend.store import Store

ROOT=Path(__file__).resolve().parent
async def main():
    sources=Sources(ROOT/'data/company-cache.json');store=Store(ROOT/'data/stock-lens.sqlite')
    audits=json.loads((ROOT/'validation/audit.json').read_text(encoding='utf-8'))
    semaphore=asyncio.Semaphore(2)
    async def check(code):
        selected=[r for r in audits if r['code']==code]
        targets=sorted({r[k] for r in selected for k in ('end_date','disclosure_date')})
        start=(date.fromisoformat(targets[0])-timedelta(days=14)).isoformat();end=targets[-1]
        result={'code':code,'checked_at':now(),'dates':targets}
        try:
            async with semaphore: rows,status=await sources.price_history(code,exchange(code),start,end)
            store.save_prices(rows);rows=sorted(rows,key=lambda r:r['date'])
            result.update(status=status,rows=len(rows),evidence=[])
            for day in targets:
                exact=next((r for r in rows if r['date']==day),None)
                previous=next((r for r in reversed(rows) if r['date']<day),None)
                result['evidence'].append({'requested_date':day,'exact':exact,'previous_if_missing':previous if exact is None else None})
        except Exception as e: result.update(status={'state':'unavailable','error':str(e)},rows=0)
        print(code,result['rows'],result['status']['state'],flush=True)
        return result
    prices=await asyncio.gather(*(check(c) for c in ['600000','600519','000001','000858','920047','920982']))
    report={'checked_at':now(),'prices':prices}
    for code,name in [('600000','浦发银行'),('920047','诺思兰德')]:
        try:
            rows,status=await sources.news_history(code,name);store.save_news(rows)
            store.set_status('news:'+code,success_at=now(),attempt_at=now(),count=len(rows),error=None,**status)
            report['news_'+code]={'count':len(rows),'status':status,'samples':rows[:8]}
            print('news',code,len(rows),flush=True)
        except Exception as e: report['news_'+code]={'error':str(e)}
    try:
        rows,status=await sources.events_with_fallback('600000','2026-04-01','2026-06-30');store.save_events(rows)
        store.set_status('events:v3:600000:2026-04-01:2026-06-30',success_at=now(),attempt_at=now(),error=None,count=len(rows),**status)
        report['announcements']={'count':len(rows),'status':status,'samples':rows[:3]}
    except Exception as e:report['announcements']={'error':str(e)}
    (ROOT/'validation/live-v2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    await sources.close()
if __name__=='__main__':asyncio.run(main())
