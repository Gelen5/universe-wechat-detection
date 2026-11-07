from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, update
import pytest

from server.content_factory_v3_store import (metadata, settings, runs, detections,
    budget_reservations,
    get_settings, ensure_settings, emergency_stop_all, stage_candidate,
    record_detection, reserve_budget, settle_budget, queue_title_plan,
    queue_production, claim_production, mark_stale_run)


def test_default_is_stopped_and_emergency_stop_clears_all_switches():
    engine = create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as connection:
        assert get_settings(connection)['emergency_stop'] is True
        ensure_settings(connection)
        assert get_settings(connection)['automatic_selection'] is False
        assert get_settings(connection)['emergency_stop'] is True
        connection.execute(update(settings).values(automatic_selection=True, automatic_articles=True,
            automatic_images=True, automatic_article_publish=True, automatic_image_publish=True, emergency_stop=False))
        emergency_stop_all(connection)
        result = get_settings(connection)
        assert result['emergency_stop'] is True
        assert not any(result[name] for name in ('automatic_selection', 'automatic_articles', 'automatic_images',
                       'automatic_article_publish', 'automatic_image_publish'))


def test_candidate_staging_is_idempotent_and_records_evidence():
    engine = create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    candidate = {'track': '情感', 'source': {'id': 'one', 'url': 'https://example.com/a', 'observed_at': '2026-11-07'}}
    with engine.begin() as connection:
        a = stage_candidate(connection, day='2026-11-07', product_type='article', candidate=candidate, angle='家庭 沟通')
        b = stage_candidate(connection, day='2026-11-07', product_type='article', candidate=candidate, angle='家庭  沟通')
        assert a['id'] == b['id'] and b['existing']
        row = connection.execute(runs.select()).mappings().one()
        assert row['status'] == 'candidate' and 'example.com' in row['evidence_json']
        record_detection(connection, run_id=a['id'], content='私有正文', result={'status':'failed', 'error':'timeout'})
        record_detection(connection, run_id=a['id'], content='私有正文', result={'status':'success', 'human_ratio':0.9, 'makers_tokens':45})
        records = connection.execute(detections.select()).mappings().all()
        assert len(records) == 2 and all('私有正文' not in str(record) for record in records)
        assert records[1]['usage_tokens'] == 45


def test_budget_stops_on_missing_or_exceeded_limit_and_preserves_unknown_spend():
    engine = create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as connection:
        with pytest.raises(ValueError):
            reserve_budget(connection, day='2026-11-07', idempotency_key='a', maximum_micros=100)
        connection.execute(update(settings).values(emergency_stop=False, automatic_selection=True, cost_bound_verified=True, daily_budget_micros=150))
        assert not reserve_budget(connection, day='2026-11-07', idempotency_key='a', maximum_micros=100)['existing']
        assert reserve_budget(connection, day='2026-11-07', idempotency_key='a', maximum_micros=100)['existing']
        with pytest.raises(ValueError):
            reserve_budget(connection, day='2026-11-07', idempotency_key='b', maximum_micros=51)
        settle_budget(connection, idempotency_key='a', actual_micros=110)
        assert get_settings(connection)['emergency_stop'] is True
        assert reserve_budget(connection, day='2026-11-07', idempotency_key='a', maximum_micros=100)['existing']


def test_production_queue_reserves_the_complete_flow_once():
    engine = create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    day = '2026-11-07'
    candidate = {'track': '情感', 'source': {
        'id': 'one', 'title': '来源标题', 'url': 'https://example.com/a',
        'observed_at': day}}
    with engine.begin() as connection:
        ensure_settings(connection)
        connection.execute(update(settings).where(settings.c.id == 1).values(
            emergency_stop=False, automatic_selection=True, automatic_articles=True,
            cost_bound_verified=True, daily_budget_micros=400,
            title_call_bound_micros=100, article_call_bound_micros=300,
            detector_call_bound_micros=50, article_limit=1, image_limit=0,
            tracks_json='["情感"]'))
        run = stage_candidate(connection, day=day, product_type='article',
                              candidate=candidate, angle='沟通')
        queue_title_plan(connection, run_id=run['id'], day=day)
        connection.execute(runs.update().where(runs.c.id == run['id']).values(
            status='title_ready', titles_json='{"main_title":"家庭沟通从听懂开始"}'))

        with pytest.raises(ValueError, match='complete flow'):
            queue_production(connection, run_id=run['id'], day=day)
        state = connection.execute(runs.select().where(runs.c.id == run['id'])).mappings().one()
        assert state['status'] == 'title_ready'
        assert len(connection.execute(budget_reservations.select()).all()) == 1

    with engine.begin() as connection:
        connection.execute(update(settings).where(settings.c.id == 1).values(
            daily_budget_micros=450))
        first = queue_production(connection, run_id=run['id'], day=day)
        second = queue_production(connection, run_id=run['id'], day=day)
        assert first['existing'] is False and second['existing'] is True
        reservations = connection.execute(budget_reservations.select()).mappings().all()
    assert len(reservations) == 3
    assert sum(row['amount_micros'] for row in reservations) == 450


def test_running_work_is_not_reclaimed_and_stale_moves_to_manual_retry():
    engine = create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    day = '2026-11-07'
    candidate = {'track': '情感', 'source': {
        'id': 'claim-one', 'title': '来源标题', 'url': 'https://example.com/a',
        'observed_at': day}}
    with engine.begin() as connection:
        run = stage_candidate(connection, day=day, product_type='article',
                              candidate=candidate, angle='沟通')
        connection.execute(update(runs).where(runs.c.id == run['id']).values(
            status='production_running',
            updated_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()))
        assert claim_production(connection, run_id=run['id']) is None
        marked = mark_stale_run(connection, run_id=run['id'])
        row = connection.execute(runs.select().where(runs.c.id == run['id'])).mappings().one()
        assert marked['previous_status'] == 'production_running'
        assert row['status'] == 'held'
        assert row['error'] == 'execution_state_unknown'
        assert row['attempt'] == 0


def test_fresh_running_work_cannot_be_marked_stale():
    engine = create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    day = '2026-11-07'
    candidate = {'track': '情感', 'source': {
        'id': 'claim-two', 'title': '来源标题', 'url': 'https://example.com/a',
        'observed_at': day}}
    with engine.begin() as connection:
        run = stage_candidate(connection, day=day, product_type='article',
                              candidate=candidate, angle='沟通')
        connection.execute(update(runs).where(runs.c.id == run['id']).values(
            status='production_running', updated_at=datetime.now(timezone.utc).isoformat()))
        with pytest.raises(ValueError, match='stale threshold'):
            mark_stale_run(connection, run_id=run['id'])
