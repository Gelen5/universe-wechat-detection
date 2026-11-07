"""Durable settings and audit records for disabled-by-default V3 automation."""
from __future__ import annotations

import json
import hashlib
import math
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urlparse
from sqlalchemy import (Boolean, CheckConstraint, Column, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, false, func, insert, select, true, update)
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
settings = Table('content_factory_v3_settings', metadata,
    Column('id', Integer, primary_key=True),
    Column('automatic_selection', Boolean, nullable=False, server_default=false()),
    Column('scheduled_selection', Boolean, nullable=False, server_default=false()),
    Column('automatic_articles', Boolean, nullable=False, server_default=false()),
    Column('automatic_images', Boolean, nullable=False, server_default=false()),
    Column('automatic_article_publish', Boolean, nullable=False, server_default=false()),
    Column('automatic_image_publish', Boolean, nullable=False, server_default=false()),
    Column('emergency_stop', Boolean, nullable=False, server_default=true()),
    Column('daily_budget_micros', Integer, nullable=False, server_default='0'),
    Column('title_call_bound_micros', Integer, nullable=False, server_default='0'),
    Column('article_call_bound_micros', Integer, nullable=False, server_default='0'),
    Column('image_call_bound_micros', Integer, nullable=False, server_default='0'),
    Column('vision_call_bound_micros', Integer, nullable=False, server_default='0'),
    Column('detector_call_bound_micros', Integer, nullable=False, server_default='0'),
    Column('cost_bound_verified', Boolean, nullable=False, server_default=false()),
    Column('article_limit', Integer, nullable=False, server_default='0'),
    Column('image_limit', Integer, nullable=False, server_default='0'),
    Column('minimum_score', Integer, nullable=False, server_default='70'),
    Column('tracks_json', Text, nullable=False, server_default='[]'),
    Column('updated_at', Text, nullable=False),
    CheckConstraint('id = 1', name='ck_factory_v3_settings_singleton'),
    CheckConstraint('daily_budget_micros >= 0 AND title_call_bound_micros >= 0 AND article_call_bound_micros >= 0 AND image_call_bound_micros >= 0 AND vision_call_bound_micros >= 0 AND detector_call_bound_micros >= 0 AND article_limit >= 0 AND image_limit >= 0 AND minimum_score BETWEEN 0 AND 100', name='ck_factory_v3_nonnegative'))

runs = Table('content_factory_v3_runs', metadata,
    Column('id', String(64), primary_key=True),
    Column('idempotency_key', String(64), nullable=False, unique=True),
    Column('product_id', String(64)),
    Column('production_day', String(10)),
    Column('selection_day', String(10), nullable=False),
    Column('source_id', String(128), nullable=False),
    Column('product_type', String(16), nullable=False),
    Column('track', String(80), nullable=False),
    Column('angle', Text, nullable=False),
    Column('status', String(24), nullable=False),
    Column('attempt', Integer, nullable=False, server_default='0'),
    Column('evidence_json', Text, nullable=False),
    Column('titles_json', Text),
    Column('quality_json', Text),
    Column('error', Text),
    Column('created_at', Text, nullable=False),
    Column('updated_at', Text, nullable=False),
    CheckConstraint("product_type IN ('article','image')", name='ck_factory_v3_run_type'))

detections = Table('content_factory_v3_detections', metadata,
    Column('id', String(64), primary_key=True),
    Column('run_id', String(64), nullable=False),
    Column('content_hash', String(64), nullable=False),
    Column('provider', String(80), nullable=False),
    Column('status', String(24), nullable=False),
    Column('human_ratio', String(32)),
    Column('usage_tokens', Integer),
    Column('error', Text),
    Column('created_at', Text, nullable=False))

budget_reservations = Table('content_factory_v3_budget_reservations', metadata,
    Column('idempotency_key', String(64), primary_key=True),
    Column('day', String(10), nullable=False, index=True),
    Column('bound_micros', Integer, nullable=False),
    Column('amount_micros', Integer, nullable=False),
    Column('actual_micros', Integer),
    Column('status', String(24), nullable=False),
    Column('created_at', Text, nullable=False),
    CheckConstraint('bound_micros > 0 AND amount_micros >= bound_micros', name='ck_factory_v3_reservation_positive'),
    CheckConstraint('actual_micros IS NULL OR actual_micros >= 0', name='ck_factory_v3_actual_nonnegative'))

product_details = Table('content_factory_v3_product_details', metadata,
    Column('product_id', String(64), primary_key=True),
    Column('run_id', String(64), nullable=False, unique=True),
    Column('details_json', Text, nullable=False),
    Column('created_at', Text, nullable=False))

quality_reports = Table('content_factory_v3_quality_reports', metadata,
    Column('id', String(64), primary_key=True),
    Column('run_id', String(64), nullable=False),
    Column('product_id', String(64), nullable=False),
    Column('attempt', Integer, nullable=False),
    Column('status', String(24), nullable=False),
    Column('report_json', Text, nullable=False),
    Column('created_at', Text, nullable=False),
    UniqueConstraint('run_id', 'attempt', name='uq_factory_v3_quality_attempt'))

provider_calls = Table('content_factory_v3_provider_calls', metadata,
    Column('id', String(64), primary_key=True),
    Column('run_id', String(64), nullable=False, index=True),
    Column('attempt', Integer, nullable=False, server_default='0'),
    Column('step', String(24), nullable=False),
    Column('provider', String(80), nullable=False),
    Column('model', String(160), nullable=False),
    Column('input_tokens', Integer, nullable=False, server_default='0'),
    Column('output_tokens', Integer, nullable=False, server_default='0'),
    Column('image_count', Integer, nullable=False, server_default='0'),
    Column('latency_ms', Integer),
    Column('created_at', Text, nullable=False),
    CheckConstraint('input_tokens >= 0 AND output_tokens >= 0 AND image_count >= 0',
                    name='ck_factory_v3_usage_nonnegative'))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_settings(connection):
    row = connection.execute(select(settings).where(settings.c.id == 1)).mappings().first()
    if row:
        value = dict(row)
        value['tracks'] = json.loads(value.pop('tracks_json'))
        return value
    return {'id': 1, 'automatic_selection': False, 'scheduled_selection': False, 'automatic_articles': False,
            'automatic_images': False, 'automatic_article_publish': False,
            'automatic_image_publish': False, 'emergency_stop': True,
            'daily_budget_micros': 0, 'title_call_bound_micros': 0, 'article_call_bound_micros': 0,
            'image_call_bound_micros': 0, 'vision_call_bound_micros': 0,
            'detector_call_bound_micros': 0, 'cost_bound_verified': False,
            'article_limit': 0, 'image_limit': 0, 'minimum_score': 70, 'tracks': [], 'updated_at': None}


def ensure_settings(connection):
    if connection.execute(select(settings.c.id).where(settings.c.id == 1)).first():
        return
    try:
        with connection.begin_nested():
            connection.execute(insert(settings).values(id=1, updated_at=utc_now()))
    except IntegrityError:
        pass


def emergency_stop_all(connection):
    """Stop new automatic work; existing jobs remain auditable."""
    ensure_settings(connection)
    connection.execute(update(settings).where(settings.c.id == 1).values(
        emergency_stop=True, automatic_selection=False, scheduled_selection=False, automatic_articles=False,
        automatic_images=False, automatic_article_publish=False, automatic_image_publish=False,
        updated_at=utc_now()))


def stage_candidate(connection, *, day, product_type, candidate, angle):
    """Persist an auditable candidate; staging never calls a model or publishes."""
    if product_type not in ('article', 'image') or not isinstance(angle, str) or not angle.strip():
        raise ValueError('invalid candidate request')
    source = candidate.get('source') or {}
    if not source.get('id') or not source.get('url') or not source.get('observed_at'):
        raise ValueError('incomplete evidence')
    # Track and normalized angle distinguish genuinely different plans while
    # repeated delivery of the same request resolves to the original run.
    fields = [day, product_type, source['id'], candidate.get('track') or '', ' '.join(angle.split())]
    key = hashlib.sha256(json.dumps(fields, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    prior = connection.execute(select(runs.c.id).where(runs.c.idempotency_key == key)).scalar_one_or_none()
    if prior:
        return {'id': prior, 'existing': True}
    ident, stamp = uuid.uuid4().hex, utc_now()
    try:
        with connection.begin_nested():
            connection.execute(insert(runs).values(id=ident, idempotency_key=key,
                source_id=source['id'], product_type=product_type, track=candidate.get('track') or '',
                angle=fields[-1], status='candidate', evidence_json=json.dumps(candidate, ensure_ascii=False),
                selection_day=day, created_at=stamp, updated_at=stamp))
    except IntegrityError:
        prior = connection.execute(select(runs.c.id).where(runs.c.idempotency_key == key)).scalar_one_or_none()
        if not prior:
            raise
        return {'id': prior, 'existing': True}
    return {'id': ident, 'existing': False}


def budget_keys(run_id, attempt):
    attempt = int(attempt or 0)
    suffix = ':' + str(attempt)
    return {
        'title': hashlib.sha256(('title-v2:' + run_id + suffix).encode()).hexdigest(),
        'production': hashlib.sha256(('production-v2:' + run_id + suffix).encode()).hexdigest(),
        'detector': hashlib.sha256(('detector-v2:' + run_id + suffix).encode()).hexdigest(),
        'vision': hashlib.sha256(('vision-v1:' + run_id + suffix).encode()).hexdigest(),
    }


def record_detection(connection, *, run_id, content, result):
    """Store one attempt without retaining the article text or credentials."""
    if not isinstance(content, str) or not content.strip() or not isinstance(result, dict):
        raise ValueError('invalid detection record')
    if not connection.execute(select(runs.c.id).where(runs.c.id == run_id)).first():
        raise ValueError('run does not exist')
    state = result.get('status')
    if state not in ('success', 'failed', 'unavailable'):
        raise ValueError('unknown detection status')
    if state == 'success':
        try:
            ratio = float(result['human_ratio'])
            if not math.isfinite(ratio) or not 0 <= ratio <= 1:
                raise ValueError('invalid ratio')
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('invalid ratio') from exc
    ident = uuid.uuid4().hex
    connection.execute(insert(detections).values(id=ident, run_id=run_id,
        content_hash=hashlib.sha256(content.encode('utf-8')).hexdigest(),
        provider='@makers/zhuque-text', status=state,
        human_ratio=str(result['human_ratio']) if state == 'success' else None,
        usage_tokens=result.get('makers_tokens') if state == 'success' else None,
        error=result.get('error') if state != 'success' else None, created_at=utc_now()))
    return ident


def record_provider_usage(connection, *, run_id, step, attempt=0, provider, model,
                          input_tokens=0, output_tokens=0, image_count=0,
                          latency_ms=None):
    """Persist measured provider usage; cost settlement stays explicitly unpaid.

    V3 never fabricates a price: ``estimated_cost`` is not stored here, so the
    budget reservation remains the only numeric cost until a verified supplier
    bill is reconciled.
    """
    if not isinstance(run_id, str) or not run_id:
        raise ValueError('run required')
    if step not in ('title', 'article', 'image', 'vision'):
        raise ValueError('unknown step')
    values = (input_tokens, output_tokens, image_count)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise ValueError('invalid usage')
    connection.execute(insert(provider_calls).values(
        id=uuid.uuid4().hex, run_id=run_id, attempt=int(attempt or 0), step=step,
        provider=str(provider)[:80], model=str(model)[:160],
        input_tokens=input_tokens, output_tokens=output_tokens, image_count=image_count,
        latency_ms=None if latency_ms is None else max(0, int(latency_ms)),
        created_at=utc_now()))


def reserve_budget(connection, *, day, idempotency_key, maximum_micros):
    """Reserve a verified upper bound; unknown provider costs must not call this.

    Failed or interrupted calls retain their reservation until actual cost is
    known. The settings row serializes reservations across PostgreSQL workers.
    """
    if not isinstance(maximum_micros, int) or isinstance(maximum_micros, bool) or maximum_micros <= 0:
        raise ValueError('verified positive upper bound required')
    ensure_settings(connection)
    control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
    prior = connection.execute(select(budget_reservations).where(
        budget_reservations.c.idempotency_key == idempotency_key)).mappings().first()
    if prior:
        if prior['day'] != day or prior['bound_micros'] != maximum_micros:
            raise ValueError('reservation key reused with different parameters')
        return {'existing': True, 'status': prior['status']}
    if control['emergency_stop'] or not control['automatic_selection'] or not control['cost_bound_verified']:
        raise ValueError('automation is stopped')
    spent = connection.execute(select(func.coalesce(func.sum(budget_reservations.c.amount_micros), 0))
        .where(budget_reservations.c.day == day)).scalar_one()
    if spent + maximum_micros > control['daily_budget_micros']:
        raise ValueError('daily budget exceeded')
    connection.execute(insert(budget_reservations).values(idempotency_key=idempotency_key,
        day=day, bound_micros=maximum_micros, amount_micros=maximum_micros, status='reserved', created_at=utc_now()))
    return {'existing': False, 'status': 'reserved'}


def settle_budget(connection, *, idempotency_key, actual_micros):
    """Never release an unknown charge; stop automation if a bound was wrong."""
    if not isinstance(actual_micros, int) or isinstance(actual_micros, bool) or actual_micros < 0:
        raise ValueError('actual cost required')
    ensure_settings(connection)
    connection.execute(select(settings.c.id).where(settings.c.id == 1).with_for_update()).one()
    row = connection.execute(select(budget_reservations).where(
        budget_reservations.c.idempotency_key == idempotency_key).with_for_update()).mappings().first()
    if not row:
        raise ValueError('reservation missing')
    if row['status'] == 'settled':
        if row['actual_micros'] != actual_micros:
            raise ValueError('settlement differs from recorded amount')
        return
    connection.execute(update(budget_reservations).where(
        budget_reservations.c.idempotency_key == idempotency_key).values(
            # Keep the larger amount reserved, so actual overruns are visible.
            amount_micros=max(row['amount_micros'], actual_micros),
            actual_micros=actual_micros, status='settled'))
    if actual_micros > row['amount_micros']:
        emergency_stop_all(connection)


def queue_title_plan(connection, *, run_id, day):
    """Queue one bounded title call; transaction also records reservation."""
    ensure_settings(connection)
    control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
    run = connection.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if not run:
        raise ValueError('run not found')
    if run['status'] in ('title_queued', 'title_running', 'title_ready'):
        return {'existing': True, 'status': run['status'], 'attempt': run['attempt']}
    if run['status'] != 'candidate':
        raise ValueError('run state does not allow title generation')
    _require_recent_source(run, day)
    bound = control['title_call_bound_micros']
    key = budget_keys(run_id, run['attempt'])['title']
    reserve_budget(connection, day=day, idempotency_key=key, maximum_micros=bound)
    connection.execute(update(runs).where(runs.c.id == run_id, runs.c.status == 'candidate').values(
        status='title_queued', updated_at=utc_now()))
    return {'existing': False, 'status': 'title_queued', 'attempt': run['attempt']}


def queue_production(connection, *, run_id, day):
    """Reserve budget and a daily slot before dispatch; never charges users."""
    ensure_settings(connection)
    control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
    run = connection.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if not run:
        raise ValueError('run not found')
    if run['status'] in ('production_queued', 'production_running', 'quality_checking', 'held', 'published'):
        return {'existing': True, 'status': run['status'], 'attempt': run['attempt']}
    if run['status'] != 'title_ready' or not run['titles_json']:
        raise ValueError('titles are not ready')
    _require_recent_source(run, day)
    kind = run['product_type']
    if not control['automatic_articles' if kind == 'article' else 'automatic_images']:
        raise ValueError('production disabled')
    if run['track'] not in json.loads(control['tracks_json']):
        raise ValueError('track disabled')
    # A retry of the same run does not consume another daily product slot.
    count = connection.execute(select(func.count()).select_from(runs).where(
        runs.c.production_day == day, runs.c.product_type == kind,
        runs.c.id != run_id)).scalar_one()
    if count >= control['article_limit' if kind == 'article' else 'image_limit']:
        raise ValueError('daily quantity exceeded')
    bound = control['article_call_bound_micros' if kind == 'article' else 'image_call_bound_micros']
    keys = budget_keys(run_id, run['attempt'])
    key = keys['production']
    extra = control['detector_call_bound_micros'] if kind == 'article' else control['vision_call_bound_micros']
    title_reservation = connection.execute(select(budget_reservations.c.amount_micros).where(
        budget_reservations.c.idempotency_key == keys['title'])).scalar_one_or_none()
    spent = connection.execute(select(func.coalesce(func.sum(budget_reservations.c.amount_micros), 0))
                               .where(budget_reservations.c.day == day,
                                      budget_reservations.c.idempotency_key.not_in([key, keys['title']]))).scalar_one()
    if spent + bound + extra + int(title_reservation or 0) > control['daily_budget_micros']:
        raise ValueError('daily budget exceeded for complete flow')
    reserve_budget(connection, day=day, idempotency_key=key, maximum_micros=bound)
    if kind == 'article':
        reserve_budget(connection, day=day, idempotency_key=keys['detector'],
                       maximum_micros=control['detector_call_bound_micros'])
    else:
        reserve_budget(connection, day=day, idempotency_key=keys['vision'],
                       maximum_micros=control['vision_call_bound_micros'])
    connection.execute(update(runs).where(runs.c.id == run_id, runs.c.status == 'title_ready').values(
        status='production_queued', production_day=day, updated_at=utc_now()))
    return {'existing': False, 'status': 'production_queued', 'attempt': run['attempt']}


def retry_run(connection, *, run_id):
    """Reset a failed/held run for one explicitly authorized retry."""
    ensure_settings(connection)
    connection.execute(select(settings.c.id).where(settings.c.id == 1).with_for_update()).one()
    run = connection.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if not run:
        raise ValueError('run not found')
    if run['status'] not in ('held', 'failed'):
        raise ValueError('run is not retryable')
    if run['attempt'] >= 2:
        raise ValueError('retry limit reached')
    status = 'title_ready' if run['titles_json'] else 'candidate'
    connection.execute(update(runs).where(runs.c.id == run_id).values(
        attempt=run['attempt'] + 1, status=status, error=None, quality_json=None,
        updated_at=utc_now()))
    return {'id': run_id, 'status': status, 'attempt': run['attempt'] + 1}


def claim_production(connection, *, run_id):
    """Claim a queued production once; running work is never auto-reclaimed."""
    run = connection.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if not run or run['status'] != 'production_queued':
        return None
    changed = connection.execute(update(runs).where(
        runs.c.id == run_id, runs.c.status == 'production_queued'
    ).values(status='production_running', updated_at=utc_now()))
    if not changed.rowcount:
        return None
    return dict(connection.execute(select(runs).where(runs.c.id == run_id)).mappings().one())


def mark_stale_run(connection, *, run_id, now=None):
    """Move an overdue running task to the exception pool for explicit retry.

    A timeout cannot prove that a remote paid call did not finish. Automatic
    reclaim would therefore risk a second charge. This transition only makes
    the ambiguity visible; it never starts another provider call.
    """
    run = connection.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if not run:
        raise ValueError('run not found')
    thresholds = {'title_running': 900, 'production_running': 1800}
    threshold = thresholds.get(run['status'])
    if threshold is None:
        raise ValueError('run is not running')
    try:
        updated = datetime.fromisoformat(run['updated_at'])
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        age = (current - updated).total_seconds()
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid run timestamp') from exc
    if age < threshold:
        raise ValueError('run has not reached the stale threshold')
    previous = run['status']
    connection.execute(update(runs).where(
        runs.c.id == run_id, runs.c.status == previous
    ).values(status='held', error='execution_state_unknown', updated_at=utc_now()))
    return {'status': 'held', 'previous_status': previous,
            'threshold_seconds': threshold, 'age_seconds': int(age)}


def _require_recent_source(run, day):
    try:
        evidence = json.loads(run['evidence_json'])
        source = evidence['source']
        observed = date.fromisoformat(source['observed_at'][:10])
        age = (date.fromisoformat(day) - observed).days
        url = urlparse(source.get('url') or '')
        if not source.get('id') or url.scheme not in ('http', 'https') or not url.hostname or not 0 <= age <= 7:
            raise ValueError('source missing or stale')
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('source missing or stale') from exc
