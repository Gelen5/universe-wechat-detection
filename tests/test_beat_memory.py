import subprocess
import sys

def test_beat_skips_worker_imports_but_keeps_all_schedules():
    code = "from server.celery_app import celery_app as app; app.loader.import_default_modules(); import sys; assert len(app.conf.beat_schedule)==8; assert 'server.agent_tasks' not in sys.modules; assert 'server.wechat_plus_tasks' not in sys.modules"
    subprocess.run([sys.executable, '-c', code, 'beat'], check=True)

def test_worker_still_registers_periodic_and_user_tasks():
    code = "from server.celery_app import celery_app as app; app.loader.import_default_modules(); required={'wechat_plus.recover','article_visual.recover','agent.recover_stale','workflow.recover_stale','hotspot.sync','lowfans.sync','provider.health','wechat_plus.run','viral_remix.run'}; assert required <= set(app.tasks), required-set(app.tasks)"
    subprocess.run([sys.executable, '-c', code, 'worker'], check=True)
