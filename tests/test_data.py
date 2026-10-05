from backend.store import Store
from backend.sources import classify, exchange
import pytest

def row(date='2025-03-31',count=100,scope='普通股',source='test'):
    return dict(code='600000',end_date=date,holders=count,scope=scope,source=source,disclosure_date='2025-04-20')

def test_dedup_revision_and_conflict(tmp_path):
    db=Store(tmp_path/'test.sqlite')
    db.save_holders([row(),row(),row('2025-06-30',80)])
    assert len(db.holders('600000'))==2
    assert db.holders('600000')[1]['change_pct']==-20
    db.save_holders([row(count=110)])
    result=db.holders('600000')
    assert len(result)==3
    assert all(r['conflict'] for r in result if r['end_date']=='2025-03-31')
    assert result[-1]['change_pct'] is None

def test_scopes_not_mixed(tmp_path):
    db=Store(tmp_path/'test.sqlite')
    db.save_holders([row(),row('2025-06-30',80,'A股'),row('2025-09-30',50)])
    result=db.holders('600000')
    assert result[1]['change_pct'] is None
    assert result[2]['change_pct']==-50

def test_failure_preserves_cache(tmp_path):
    db=Store(tmp_path/'test.sqlite');db.save_holders([row()])
    db.set_status('holders:600000',success_at='2025-01-01',error=None)
    db.set_status('holders:600000',error='network failed')
    assert db.status('holders:600000')['success_at']=='2025-01-01'
    assert len(db.holders('600000'))==1

def test_events_use_publication_date_and_dedup(tmp_path):
    db=Store(tmp_path/'test.sqlite')
    e={'id':'a','code':'600000','published_date':'2025-03-20','occurred_date':'2025-01-01'}
    db.save_events([e,e])
    assert len(db.events('600000','2025-03-20','2025-03-20'))==1
    assert db.events('600000','2025-01-01','2025-01-31')==[]

@pytest.mark.parametrize('title,label',[('2025年度报告','业绩'),('关于减持股份的公告','增减持'),('重大合同签订','重大合同'),('重大资产重组','重组并购'),('行政处罚决定','诉讼处罚'),('股份回购进展','回购'),('董事会决议','其他公告')])
def test_classification(title,label): assert classify(title)==label

@pytest.mark.parametrize('code,market',[('600000','SH'),('000001','SZ'),('920047','BJ'),('830799','BJ')])
def test_exchange(code,market): assert exchange(code)==market

@pytest.mark.parametrize('code',['../../xx','999999','00700','600000.SH','0000000'])
def test_invalid(code):
    with pytest.raises(ValueError): exchange(code)
