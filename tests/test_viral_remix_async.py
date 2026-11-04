"""爆款贴图复刻：异步出图任务的计费。

一张 2 积分，提交时按张数预扣，结束时按实际成功张数结算，余量退回。
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.support  # noqa: F401,E402

from server import accounts  # noqa: E402
from server import viral_remix_jobs as jobs  # noqa: E402


def seed(user_id: str, points: int = 100) -> None:
    with accounts._connect() as conn:
        conn.execute(
            "UPDATE wallets SET balance=?, trial_balance=?, bonus_balance=0, paid_balance=0 WHERE user_id=?",
            (points, points, user_id),
        )


def wallet(user_id: str) -> dict:
    return accounts.wallet_summary(user_id)


@pytest.fixture()
def user_id():
    email = 'remix-async@example.com'
    password = 'testing-pass-123'
    accounts.init_db()
    try:
        accounts.create_user(email, password, '贴图异步', user_id='remix-user')
    except Exception:  # noqa: BLE001 - 用例重跑时用户已存在
        pass
    return 'remix-user'


def idea(cards: int) -> dict:
    return {'id': 'A', 'name': '方案A', 'headline': '测试',
            'visual_contract': {'asset_type': 'poster'},
            'cards': [{'headline': f'第{i}张'} for i in range(1, cards + 1)]}


class TestCardCount:
    def test_planned_pages_determine_reservation(self):
        assert jobs.count_cards({'page_count':3}) == 3
        for count in (0,9,True,'3'):
            with pytest.raises(ValueError): jobs.count_cards({'page_count':count})
    def test_rejects_empty_and_oversized_plans(self):
        with pytest.raises(ValueError):
            jobs.count_cards({'cards': []})
        with pytest.raises(ValueError):
            jobs.count_cards({'cards': [{'headline': str(i)} for i in range(9)]})

    def test_accepts_eight(self):
        assert jobs.count_cards(idea(8)) == 8


class TestReservation:
    def test_submit_reserves_two_points_per_card(self, user_id):
        seed(user_id)
        job = jobs.submit(user_id, 'session-1', idea(4))
        assert job['status'] == 'queued'
        assert wallet(user_id)['balance'] == 92, '4 张要预扣 8 积分'
        public = jobs.public(job)
        assert public['total'] == 4
        assert public['points']['reserved'] == 8
        assert public['points']['per_image'] == 2

    def test_duplicate_submit_does_not_double_charge(self, user_id):
        seed(user_id)
        jobs.submit(user_id, 'session-dup', idea(2))
        assert wallet(user_id)['balance'] == 96
        jobs.submit(user_id, 'session-dup', idea(2))  # 同一创意重复提交
        assert wallet(user_id)['balance'] == 96, '幂等重放不该再扣一次'

    def test_poor_wallet_is_rejected(self, user_id):
        seed(user_id, points=0)
        with pytest.raises(Exception) as exc:
            jobs.submit(user_id, 'session-poor', idea(1))
        assert '积分不足' in str(exc.value)


class TestSettlement:
    def _job_with_usage(self, user_id, cards=3):
        seed(user_id)
        # 每个用例独立 session：同 session + 同创意会被幂等去重。
        job = jobs.submit(user_id, f'session-{uuid.uuid4().hex[:8]}', idea(cards))
        return job

    def test_settles_only_for_generated_images(self, user_id):
        job = self._job_with_usage(user_id, cards=3)   # 预扣 6
        images = [{'index': 1, 'url': '/a.jpg'}, {'index': 2, 'url': '/b.jpg'}]
        jobs.settle(job, images, 90000)
        assert wallet(user_id)['balance'] == 96, '成功 2 张只收 4 积分'
        assert accounts.usage_state(job['usage_id']) == 'completed'

    def test_zero_images_refunds_everything(self, user_id):
        job = self._job_with_usage(user_id, cards=3)
        jobs.settle(job, [], 5000)
        assert wallet(user_id)['balance'] == 100
        assert accounts.usage_state(job['usage_id']) == 'refunded'


class TestPublicShape:
    def test_running_job_reports_progress(self, user_id):
        seed(user_id)
        job = jobs.submit(user_id, 'session-progress', idea(3))
        accounts.claim_job(['image'], job['id'])
        accounts.progress_job(job['id'], done=2, total=3, stage='generating')
        public = jobs.public(accounts.job(job['id'], user_id))
        assert public['status'] == 'running'
        assert public['done'] == 2 and public['total'] == 3
        assert public['stage'] == 'generating'

    def test_finished_job_exposes_images(self, user_id):
        seed(user_id)
        job = jobs.submit(user_id, 'session-done', idea(1))
        accounts.claim_job(['image'], job['id'])
        result = {'images': [{'index': 1, 'url': '/x.jpg'}], 'copy_directions': [], 'tags': {}}
        accounts.finish_job(job['id'], result)
        public = jobs.public(accounts.job(job['id'], user_id))
        assert public['status'] == 'succeeded'
        assert len(public['images']) == 1
        assert public['points']['charged'] == 2

class TestExpandFallback:
    """创意展开那一步是文字模型；它超时不该让整单报废。"""

    def test_text_failure_falls_back_to_the_raw_idea(self, monkeypatch, tmp_path):
        from server import creator_tools

        monkeypatch.setattr(creator_tools, 'OUTPUT_DIR', tmp_path)

        def boom(*args, **kwargs):
            raise RuntimeError('provider transport')

        monkeypatch.setattr(creator_tools.workbench, '_json_text', boom)
        raw = {
            'id': 'C', 'name': '换角度', 'headline': '一起做顿家常饭',
            'image_brief': '暖光厨房餐桌，两双手分别择菜和盛汤',
            'visual_contract': {'asset_type': 'poster'}, 'page_count': 1,
            'choices': {'track': '情感关系'},
        }
        cards, idea, directory = creator_tools.prepare_remix_cards('session-x', raw)
        assert len(cards) == 1
        assert cards[0]['image_brief'] == raw['image_brief']
        assert '创意展开未完成' in idea['fallback_note']
        assert directory.is_dir()

    def test_incomplete_plan_from_the_model_still_raises(self, monkeypatch, tmp_path):
        from server import creator_tools

        monkeypatch.setattr(creator_tools, 'OUTPUT_DIR', tmp_path)
        monkeypatch.setattr(creator_tools.workbench, '_json_text',
                            lambda *a, **k: {'cards': []})
        raw = {'id': 'C', 'name': '换角度', 'choices': {'track': 'x'},
               'visual_contract': {'asset_type': 'poster'}}
        with pytest.raises(creator_tools.workbench.ProviderError):
            creator_tools.prepare_remix_cards('session-y', raw)

class TestProviderOverride:
    """后台「统一 API 设置」写在 provider_settings 表里，workbench._setting 只认
    请求级覆盖和环境变量。任务不进 provider_overrides 就会退回 api.openai.com，
    国内直连不通——这正是出图任务一直失败、生图模型从未被调用到的原因。
    """

    def test_task_resolves_the_configured_relay(self, user_id, monkeypatch, tmp_path):
        from server import creator_tools, viral_remix_tasks, workbench

        sentinel = 'https://relay.example.test/v1'
        with accounts.DB_LOCK, accounts._connect() as conn:
            previous = tuple(conn.execute(
                "SELECT text_base_url, text_model FROM provider_settings WHERE id=1").fetchone())
            conn.execute(
                "UPDATE provider_settings SET text_base_url=?, text_model=? WHERE id=1",
                (sentinel, 'sentinel-model'))
        try:
            seed(user_id)
            job = jobs.submit(user_id, 'session-relay', idea(1))
            seen = {}

            def fake_prepare(session_id, raw):
                seen['base'] = workbench._setting('WECHAT_TEXT_API_BASE_URL')
                seen['model'] = workbench._setting('WECHAT_TEXT_MODEL')
                return [{'headline': 'x'}], raw, tmp_path

            def fake_card(idea, page, index, total, directory):
                return {'index': index, 'url': '/x.jpg', 'width': 1, 'height': 1,
                        'check_passed': True}

            monkeypatch.setattr(creator_tools, 'prepare_remix_cards', fake_prepare)
            monkeypatch.setattr(creator_tools, 'generate_remix_card', fake_card)
            viral_remix_tasks.run.run(job['id'])

            assert seen['base'] == sentinel
            assert seen['model'] == 'sentinel-model'
            assert jobs.public(accounts.job(job['id'], user_id))['status'] == 'succeeded'
        finally:
            with accounts.DB_LOCK, accounts._connect() as conn:
                conn.execute(
                    "UPDATE provider_settings SET text_base_url=?, text_model=? WHERE id=1",
                    previous)
