"""Read-only network validation; saves evidence, never invents a verification result."""
import asyncio
import io
import json
import re
from pathlib import Path
from pypdf import PdfReader
from backend.sources import Sources, now
from backend.store import Store

ROOT=Path(__file__).resolve().parent
SAMPLES=['600000','600519','000001','000858','920047','920982']

async def main():
    source=Sources(ROOT/'data/company-cache.json'); store=Store(ROOT/'data/stock-lens.sqlite')
    audit=[]; coverage=[]
    for code in SAMPLES:
        try:
            rows=await source.holders(code)
            store.save_holders(rows)
            if rows: store.save_stock({k:rows[0][k] for k in ['code','name','exchange']})
            store.set_status('holders:'+code,success_at=now(),attempt_at=now(),error=None,count=len(rows))
            repeated=await source.holders(code)
            coverage.append({'code':code,'count':len(rows),'first':min(r['end_date'] for r in rows),
                'last':max(r['end_date'] for r in rows),'repeat_consistent':[(r['end_date'],r['holders']) for r in rows]==[(r['end_date'],r['holders']) for r in repeated],
                'checked_at':now()})
            selected=[]; seen=set()
            for r in rows:
                if r['end_date'][5:] not in ('03-31','06-30','09-30','12-31') or r['end_date'] in seen: continue
                selected.append(r);seen.add(r['end_date'])
                if len(selected)==3: break
            for row in selected:
                entry={k:row[k] for k in ['code','name','end_date','holders','disclosure_date','source_url']}
                entry.update(status='gap',reason='尚未找到并核对对应原文',checked_at=now())
                try:
                    notices=await source.announcements(code,row['disclosure_date'],row['disclosure_date'])
                    store.save_events(notices)
                    expected_year=row['end_date'][:4]
                    candidates=[a for a in notices if re.search(r'(?:年度|半年度|季度)报告(?:[（(].*[）)])?$',a['title']) and expected_year in a['title'] and not any(s in a['title'] for s in ['摘要','审计','鉴证','责任','评估','自查','募集','核查'])]
                    entry['candidate_urls']=[a['source_url'] for a in candidates]
                    matches=[]
                    for a in candidates[:5]:
                        pdf=await source.client.get(a['source_url'])
                        pdf.raise_for_status()
                        reader=PdfReader(io.BytesIO(pdf.content))
                        for index,page in enumerate(reader.pages):
                            text=page.extract_text() or ''
                            if not re.search(r'股东.{0,8}(总数|户数|人数)',text): continue
                            flattened=re.sub(r'\s+','',text).replace(',','').replace('，','')
                            for hit in re.finditer(r'股东.{0,8}(?:总数|户数|人数)',flattened):
                                snippet=flattened[max(0,hit.start()-100):hit.end()+250]
                                if re.search(r'(?<!\d)'+str(row['holders'])+r'(?!\d)',snippet):
                                    matches.append({'url':a['source_url'],'title':a['title'],'page':index+1,'snippet':snippet})
                        if matches: break
                    if matches:
                        entry.update(status='candidate_match',reason='数值在股东段落命中，待审阅统计日期与口径',evidence=matches,
                                     original_url=matches[0]['url'])
                    elif not candidates: entry['reason']='该披露日未找到对应定期报告；可能来自互动答复或其他披露'
                    else: entry['reason']='已读取候选报告，未自动匹配股东段落；不能判定一致'
                except Exception as exc: entry['reason']=type(exc).__name__+': '+str(exc)[:250]
                audit.append(entry)
                (ROOT/'validation/audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
                print(code,row['end_date'],entry['status'],flush=True)
        except Exception as exc: coverage.append({'code':code,'error':str(exc),'checked_at':now()})
        (ROOT/'validation/coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf-8')
    await source.close()

if __name__=='__main__': asyncio.run(main())
