"""Leased, recoverable Celery execution for the independent Plus workspace."""
from pathlib import Path
from threading import Event, Thread
import hashlib
import json
import time
import re

from .celery_app import celery_app
from . import accounts
from . import wechat_plus_billing as billing
from . import wechat_plus_repository as repo
from . import wechat_plus_service as service
from . import workbench, workbench_research

# worker 进程不经过 server.main，计费表得在这里自己建一次（create_all 幂等）。
try:
    billing.init_schema()
except Exception:  # noqa: BLE001 - 建表失败不该让 worker 起不来
    import logging
    logging.getLogger(__name__).warning('wechat_plus charges table not ready at import')


def dispatch(turn_id):
    return execute_turn.apply_async(args=[turn_id], queue='chat').id


@celery_app.task(bind=True, name='wechat_plus.run', acks_late=True,
                 reject_on_worker_lost=True, soft_time_limit=1200, time_limit=1260)
def execute_turn(self, turn_id):
    turn = repo.claim(turn_id, self.request.id)
    if not turn:
        return {'status': 'ignored'}
    stop = Event()
    execution_started = time.monotonic()

    def renew():
        while not stop.wait(20):
            try:
                if not repo.heartbeat(turn_id, self.request.id):
                    return
            except Exception:
                # A lost lease is checked again before publication.
                continue

    thread = Thread(target=renew, daemon=True)
    thread.start()
    cache = dict(turn.get('cache') or {})

    def check():
        if not repo.is_running(turn_id, self.request.id):
            raise service.Cancelled('任务已取消或由其他进程恢复')

    def generate(prompt):
        check()
        key = hashlib.sha256((service.configured_model() + '\n' + prompt).encode()).hexdigest()
        if key in cache:
            return cache[key]
        result = service.generate_json(prompt)
        check()
        if not repo.cache_result(turn_id, self.request.id, key, result):
            raise service.Cancelled('任务已取消')
        cache[key] = result
        return result

    def search(query, **kwargs):
        check()
        key = 'search:' + hashlib.sha256(json.dumps([query, kwargs], sort_keys=True).encode()).hexdigest()
        if key in cache:
            return cache[key]
        result = workbench_research.search(query, **kwargs)
        if not repo.cache_result(turn_id, self.request.id, key, result):
            raise service.Cancelled('任务已取消')
        cache[key] = result
        return result

    started = time.monotonic()

    def settle_completed(action, points):
        """正常跑完：按实际动作结算。

        注意 0 分也要走 settle_usage_with_points，而不是 refund——后台的「失败任务」
        统计把 status='refunded' 一律算作失败，如果闲聊也退款，管理员会看到一片
        「失败」。0 分结算 = 差额全额退回 + 状态 completed。
        """
        usage_id = billing.usage_for(turn_id)
        if not usage_id:
            return
        elapsed = int((time.monotonic() - started) * 1000)
        accounts.settle_usage_with_points(usage_id, 200, elapsed, points)
        billing.record(turn_id, action, points)

    def refund(action):
        """没跑成：全额退回，状态留 refunded（后台会把它算进失败/退分）。"""
        usage_id = billing.usage_for(turn_id)
        if not usage_id:
            return
        elapsed = int((time.monotonic() - started) * 1000)
        accounts.refund_usage(usage_id, 200, elapsed)
        billing.record(turn_id, action, 0)

    try:
        session = repo.get(turn['session_id'], turn['user_id'])
        if session['version'] != turn['input_version']:
            raise repo.Conflict('文章已经更新，恢复的操作未覆盖新内容')
        # Every claim gets a private directory. A late cancelled worker cannot
        # overwrite a preview produced by a later task.
        directory = workbench.OUTPUT_DIR / 'wechat-plus' / session['id'] / turn_id / self.request.id
        prior_state = session['state']
        if not prior_state.get('layout_theme') and 'layout_previous_theme' not in prior_state:
            prior_state['layout_previous_theme'] = repo.recent_layout_theme(turn['user_id'], session['id'])
        state = service.execute(prior_state, turn['message'], generate,
            output_dir=directory, check_cancelled=check,
            progress=lambda text: repo.heartbeat(turn_id, self.request.id, text), search=search)
        committed = repo.commit_turn(turn_id, self.request.id, session['version'], state)
        if committed:
            action = str(state.get('billing_action') or state.get('last_action') or '')
            if state.get('_blocked'):
                refund('blocked')
            else:
                # Step mode charges the node it actually advanced; the legacy
                # action path keeps using the action price table unchanged.
                points = state.get('billing_points')
                settle_completed(action, accounts.plus_points_for(action)
                                 if points is None else int(points))
        else:
            refund('cancelled')
        return {'status': 'completed' if committed else 'cancelled'}
    except service.Cancelled:
        refund('cancelled')
        return {'status': 'cancelled'}
    except Exception as exc:
        # Provider exceptions may contain upstream bodies. Keep private details
        # in server logs and expose a bounded actionable failure to the client.
        import logging
        logging.getLogger(__name__).exception('Plus turn failed: %s', turn_id)
        # Store bounded diagnostics in the database, never in public artifacts.
        # Follow causes because ProviderError deliberately hides upstream errors.
        try:
            chain, current, seen = [], exc, set()
            while current is not None and id(current) not in seen and len(chain) < 6:
                seen.add(id(current))
                message = str(current)
                message = re.sub(r'(?:sk-|re_)[A-Za-z0-9_-]+', '[REDACTED]', message)
                message = re.sub(r'(?i)(authorization|api[_-]?key|token)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', message)
                chain.append({'type': type(current).__name__, 'message': message[:3000],
                              'status_code': getattr(current, 'status_code', None),
                              'code': getattr(current, 'code', None)})
                current = current.__cause__ or current.__context__
            repo.record_failure(turn_id, {'task_id': self.request.id,
                'user_id': turn['user_id'], 'session_id': turn['session_id'],
                'model': service.configured_model(),
                'elapsed_ms': round((time.monotonic() - execution_started) * 1000),
                'exceptions': chain})
        except Exception:
            logging.getLogger(__name__).warning('Could not persist Plus diagnostics for %s', turn_id)
        safe = str(exc) if isinstance(exc, (ValueError, repo.Conflict)) else '本次处理未完成，原有内容已保留。请稍后重试。'
        if isinstance(exc, workbench.ProviderError):
            safe = '模型服务暂时不可用，文章已保留。稍后可以继续上次未完成的处理。'
        refund('failed')
        repo.finish(turn_id, self.request.id, 'failed', safe)
        return {'status': 'failed'}
    finally:
        stop.set()
        thread.join(timeout=1)


@celery_app.task(name='wechat_plus.recover')
def recover_turns():
    for turn_id in repo.recover():
        dispatch(turn_id)
