import hashlib
import json
import sqlite3
from pathlib import Path
from .sources import now

class Store:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS holders (id TEXT PRIMARY KEY,code TEXT,end_date TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS stocks (code TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE IF NOT EXISTS status (key TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY,code TEXT,published TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS watched (code TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS watch_subscriptions (owner TEXT,code TEXT,expires_at TEXT,PRIMARY KEY(owner,code));
            CREATE TABLE IF NOT EXISTS prices (code TEXT,trade_date TEXT,source TEXT,body TEXT,PRIMARY KEY(code,trade_date,source));
            CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY,code TEXT,published TEXT,body TEXT);
            CREATE INDEX IF NOT EXISTS h_code ON holders(code,end_date);
            CREATE INDEX IF NOT EXISTS e_code ON events(code,published);
            CREATE INDEX IF NOT EXISTS p_code ON prices(code,trade_date);
            CREATE INDEX IF NOT EXISTS n_code ON news(code,published);
            ''')

    def connect(self): return sqlite3.connect(self.path,timeout=15)
    def save_stock(self,r):
        with self.connect() as db:
            old=db.execute('SELECT body FROM stocks WHERE code=?',(r['code'],)).fetchone()
            previous=json.loads(old[0]) if old else {}
            aliases=list(dict.fromkeys([*previous.get('aliases',[]),previous.get('name'),*r.get('aliases',[])]))
            r=r|{'aliases':[name for name in aliases if name and name!=r['name']]}
            db.execute('INSERT OR REPLACE INTO stocks VALUES (?,?)',(r['code'],json.dumps(r,ensure_ascii=False)))
    def stocks(self):
        with self.connect() as db: return [json.loads(r[0]) for r in db.execute('SELECT body FROM stocks')]
    def status(self,key):
        with self.connect() as db:
            row=db.execute('SELECT body FROM status WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else {}
    def set_status(self,key,**values):
        status=self.status(key)|values
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO status VALUES (?,?)',(key,json.dumps(status)))
    def save_holders(self,rows):
        with self.connect() as db:
            for r in rows:
                # Preserve revisions and conflicts, but repeated fetches are idempotent.
                identity=[r.get(k) for k in ('code','end_date','disclosure_date','holders','scope','source')]
                key=hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
                db.execute('INSERT OR REPLACE INTO holders VALUES (?,?,?,?)',(key,r['code'],r['end_date'],json.dumps(r|{'id':key},ensure_ascii=False)))
    def holders(self,code):
        with self.connect() as db:
            rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM holders WHERE code=? ORDER BY end_date, id',(code,))]
        groups={}
        for r in rows: groups.setdefault((r['end_date'],r['scope']),[]).append(r)
        previous={}
        for (end,scope),group in sorted(groups.items()):
            values={r['holders'] for r in group}
            conflict=len(values)>1
            old=previous.get(scope)
            for r in group:
                r['conflict']=conflict
                r['change_pct']=round((r['holders']/old-1)*100,2) if old and not conflict else None
                r['change_count']=r['holders']-old if old and not conflict else None
            previous[scope]=None if conflict else group[0]['holders']
        return rows
    def save_events(self,rows):
        with self.connect() as db:
            for r in rows: db.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?)',(r['id'],r['code'],r['published_date'],json.dumps(r,ensure_ascii=False)))
    def events(self,code,start,end):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM events WHERE code=? AND published>=? AND published<=? ORDER BY published DESC,id',(code,start,end))]
    def watch(self,codes,owner=None,expires_at=None):
        with self.connect() as db:
            if owner:
                db.execute('DELETE FROM watch_subscriptions WHERE owner=?',(owner,))
                db.executemany('INSERT INTO watch_subscriptions VALUES (?,?,?)',[(owner,c,expires_at) for c in set(codes)])
            else:
                db.execute('DELETE FROM watched')
                db.executemany('INSERT INTO watched VALUES (?)',[(c,) for c in set(codes)])
    def watched(self):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT code FROM watched UNION SELECT code FROM watch_subscriptions WHERE expires_at>?',(now(),))]

    def save_prices(self,rows):
        with self.connect() as db:
            for r in rows:
                if r.get('adjustment')!='none': raise ValueError('Only unadjusted prices may enter this table')
                db.execute('INSERT OR REPLACE INTO prices VALUES (?,?,?,?)',(r['code'],r['date'],r['source'],json.dumps(r,ensure_ascii=False)))
    def prices(self,code,start,end):
        with self.connect() as db: rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM prices WHERE code=? AND trade_date>=? AND trade_date<=? ORDER BY trade_date',(code,start,end))]
        groups={}
        for r in rows: groups.setdefault(r['date'],[]).append(r)
        output=[]
        for day,values in groups.items():
            r=next((r for r in values if r['source']=='东方财富'),values[0])
            r['conflict']=len({round(v['close'],4) for v in values})>1
            r['alternatives']=[{'source':v['source'],'close':v['close']} for v in values] if r['conflict'] else []
            output.append(r)
        return output
    def save_news(self,rows):
        with self.connect() as db:
            for r in rows: db.execute('INSERT OR REPLACE INTO news VALUES (?,?,?,?)',(r['id'],r['code'],r['published_at'],json.dumps(r,ensure_ascii=False)))
    def news(self,code,start=None,end=None):
        with self.connect() as db: rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM news WHERE code=? ORDER BY published DESC',(code,))]
        return [r for r in rows if (not start or r['published_date']>=start) and (not end or r['published_date']<=end)][:100]
