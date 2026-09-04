"""Render a copy of a test session without calling models or publishing."""
import json
import sqlite3
import sys
from server import workbench

session_id = sys.argv[1]
with sqlite3.connect('file:data/creator_accounts.db?mode=ro', uri=True) as db:
    row = db.execute('SELECT payload_json FROM workbench_sessions WHERE id=?', (session_id,)).fetchone()
session = json.loads(row[0])
session['id'] = 'qa-typeset-20260904'
session['images'] = []
workbench._typeset(session)
output = workbench.OUTPUT_DIR / session['id'] / 'typeset-preview.html'
output.write_text(session['preview_document'], encoding='utf-8')
print(output)
print(session['typeset_source'])
