"""Exercise the browser-independent copy safety predicate with real JS."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_layout_freshness_uses_snapshot_identity_and_handles_old_artifacts():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is unavailable')
    script = Path(__file__).resolve().parents[1] / 'static' / 'publisher-copy.js'
    js = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const stale = sandbox.window.PublisherCopy.isStale;
const original = {id:'v1', updated_at:'2026-10-27T10:00:00Z'};
const revised = {id:'v2', updated_at:'2026-10-27T10:02:00Z'};
const layout = {content_json:{source_article_id:'v1'}, updated_at:'2026-10-27T10:01:00Z'};
assert.equal(stale(layout, original), false);
assert.equal(stale(layout, revised), true);
const oldLayout = {content_json:{}, updated_at:'2026-10-27T10:01:00Z'};
assert.equal(stale(oldLayout, original), false);
assert.equal(stale(oldLayout, revised), true);
assert.equal(stale({content_json:{}}, revised), true);
'''
    result = subprocess.run([node, '-e', js, str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
