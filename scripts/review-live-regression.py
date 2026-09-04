"""Run the actual revised Skill adapter on an isolated copy of the prior test article."""
import json
import sqlite3
from server import workbench as w

with sqlite3.connect('file:data/creator_accounts.db?mode=ro',uri=True) as db:
    row=db.execute('SELECT payload_json FROM workbench_sessions WHERE id=?',('2b8c097c13464d40acb271c1f0333960',)).fetchone()
s=json.loads(row[0])
s['id']='qa-review-20260905'
try:
    with w.provider_overrides():
        article, review=w._review(s['article'],s)
    print(json.dumps({'gate':review['gate'],'changed':review['changed'],'rounds':len(review['rounds']),'audit':review['audit']},ensure_ascii=False))
except Exception as e:
    print('BLOCKED:',str(e))
    print('Evidence:',w.OUTPUT_DIR/s['id']/'anti_ai'/'run.json')
    raise SystemExit(2)
