"""Protocol race tests run the actual shared JS reducer without browser timing."""
import subprocess
from pathlib import Path


def test_snapshot_event_cancel_and_reconnect_ordering():
    script = r'''
const assert=require('node:assert/strict');
const R=require('./static/run-presentation.js');
let s=R.create('r','writing',1000);
s=R.reduce(s,{kind:'event',id:'r',type:'stage.resolved',eventId:8,
 createdAt:'2026-10-27T00:00:02Z',payload:{stage:'topic'}});
s=R.reduce(s,{kind:'snapshot',run:{id:'r',status:'running',stage:'writing',updated_at:'2026-10-27T00:00:01Z'}});
assert.equal(s.stage,'topic','older poll must not undo the resolved stage');
s=R.reduce(s,{kind:'connection.lost'});
assert.equal(s.phase,'reconnecting'); assert.equal(s.status,'running');
s=R.reduce(s,{kind:'cancel.requested'});
s=R.reduce(s,{kind:'snapshot',run:{id:'r',status:'running',updated_at:'2026-10-27T00:00:03Z'}});
assert.equal(s.phase,'cancelling','poll is not confirmation that cancel failed');
s=R.reduce(s,{kind:'cancel.unconfirmed'});
s=R.reduce(s,{kind:'connection.lost'});
s=R.reduce(s,{kind:'connection.open'});
assert.equal(s.cancelRequested,true);
assert.equal(R.title(s,'写作'),'取消结果待确认');
s=R.reduce(s,{kind:'event',type:'run.cancelled',eventId:9,createdAt:'2026-10-27T00:00:04Z'});
assert.equal(s.phase,'cancelled');
assert.equal(R.reduce(s,{kind:'event',type:'run.started',eventId:10}),s,'terminal state is final');
let completed=R.reduce(R.create('r','writing'),{kind:'snapshot',run:{id:'r',status:'completed',stage:'topic'}});
assert.equal(completed.stage,'topic','snapshot must carry stage even if SSE is closed first');
assert.equal(R.reduce(completed,{kind:'event',type:'stage.resolved',payload:{stage:'writing'}}),completed);
let next=R.create('new','outline');
assert.equal(R.reduce(next,{kind:'snapshot',run:{id:'old',status:'failed'}}),next);
let q=R.reduce(R.create('q','writing'),{kind:'snapshot',run:{id:'q',status:'queued',created_at:'2026-10-27T00:00:00Z'}});
assert.equal(q.startedAt,null,'queued is not running');
assert.equal(q.createdAt,Date.parse('2026-10-27T00:00:00Z'));
assert.equal(R.title(q,'写作'),'任务已排队');
let waiting=R.reduce(R.create('waiting','topic'),{kind:'snapshot',run:{id:'waiting',status:'waiting_input'}});
waiting=R.reduce(waiting,{kind:'snapshot',run:{id:'waiting',status:'cancelled'}});
assert.equal(waiting.status,'cancelled','a waiting-input run is still cancellable on the server');
'''
    result = subprocess.run(['node', '-'], input=script, text=True, encoding='utf-8', capture_output=True,
                            cwd=Path(__file__).resolve().parents[1], timeout=10)
    assert result.returncode == 0, result.stderr or result.stdout
