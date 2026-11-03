import os
import subprocess
import sys


def test_insights_sync_once_at_11_beijing():
    env = os.environ.copy()
    env['IMAGE_BOARD_SYNC_ENABLED'] = '1'
    env['IMAGE_BOARD_SYNC_HOURS_UTC'] = '2,6'
    code = '''
from server.celery_app import celery_app as app
assert str(app.timezone) == 'UTC'
for name in ('lowfans-sync-daily', 'image-board-sync-daily'):
    schedule = app.conf.beat_schedule[name]['schedule']
    assert schedule.hour == {3} and schedule.minute == {0}, (name, schedule)
'''
    subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
