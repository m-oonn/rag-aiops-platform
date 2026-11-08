import json
import sqlite3
from pathlib import Path
from rounddir import round_dir

D = round_dir()
con = sqlite3.connect(f'file:{D}/product/runs.sqlite?mode=ro', uri=True)
cur = con.cursor()
tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
print('tables', tables)
if 'aiops_runs' in tables:
    cur2 = con.execute('select * from aiops_runs order by id desc limit 3')
    cols = [d[0] for d in cur2.description]
    for row in cur2.fetchall():
        d = dict(zip(cols, row))
        print({k: (str(v)[:60] if v is not None else None) for k, v in d.items()
               if k in ('id', 'thread_id', 'status', 'kind', 'created_at', 'updated_at', 'request_id')})
    print('total runs', con.execute('select count(*) from aiops_runs').fetchone()[0])
con.close()
c = json.loads((D / 'product-model/cost.json').read_text(encoding='utf-8'))
print('ledger rows', len(c['requests']), 'reserved', c['reserved_cny'], 'last', c['requests'][-1]['number'])
