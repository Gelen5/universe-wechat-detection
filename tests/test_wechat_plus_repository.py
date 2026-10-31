import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

from server import database
from server import wechat_plus_repository as repository


class PlusPublicationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.override = patch.object(database, 'ENGINE', self.engine)
        self.override.start()
        repository.init_schema()
        self.session = repository.create('owner')

    def tearDown(self):
        self.override.stop()
        self.engine.dispose()

    def claim(self):
        turn, _ = repository.enqueue(self.session['id'], 'owner', 1, '写一篇文章', 'once')
        repository.claim(turn['id'], 'worker')
        return turn

    def test_cancelled_generation_cannot_publish_late_result(self):
        turn = self.claim()
        self.assertTrue(repository.cancel(turn['id'], 'owner'))
        self.assertFalse(repository.commit_turn(turn['id'], 'worker', 1, {'draft': 'late'}))
        self.assertEqual(repository.get(self.session['id'], 'owner')['version'], 1)

    def test_editor_change_is_not_overwritten_by_generation(self):
        turn = self.claim()
        repository.save(self.session['id'], 'owner', 1, {'draft': '手动修改'})
        with self.assertRaises(repository.Conflict):
            repository.commit_turn(turn['id'], 'worker', 1, {'draft': 'stale'})
        self.assertEqual(repository.get(self.session['id'], 'owner')['state']['draft'], '手动修改')

    def test_publication_is_atomic_and_idempotent(self):
        turn = self.claim()
        self.assertFalse(repository.commit_turn(turn['id'], 'other-worker', 1, {}))
        self.assertTrue(repository.commit_turn(turn['id'], 'worker', 1, {'draft': '成稿'}))
        self.assertFalse(repository.commit_turn(turn['id'], 'worker', 1, {}))
        saved = repository.get(self.session['id'], 'owner')
        self.assertEqual(saved['version'], 2)
        self.assertEqual(saved['turns'][0]['status'], 'completed')
        replay, created = repository.enqueue(self.session['id'], 'owner', 1, '写一篇文章', 'once')
        self.assertFalse(created)
        self.assertEqual(replay['id'], turn['id'])
        with self.assertRaises(KeyError):
            repository.get(self.session['id'], 'another-owner')

    def test_recovered_worker_reuses_saved_results_and_rejects_old_lease(self):
        from sqlalchemy import update
        turn = self.claim()
        self.assertTrue(repository.cache_result(turn['id'], 'worker', 'model-response', {'ok':True}))
        with self.engine.begin() as db:
            db.execute(update(repository.turns).where(repository.turns.c.id == turn['id']).values(updated_at='2000-01-01T00:00:00+00:00'))
        self.assertIn(turn['id'], repository.recover())
        recovered = repository.claim(turn['id'], 'new-worker')
        self.assertEqual(recovered['cache'], {'model-response':{'ok':True}})
        self.assertFalse(repository.cache_result(turn['id'], 'worker', 'late-response', {}))
        self.assertFalse(repository.commit_turn(turn['id'], 'worker', 1, {}))
        self.assertNotIn('cache', repository.get(self.session['id'], 'owner')['turns'][0])

    def test_retry_reuses_results_but_cannot_replay_over_new_edits(self):
        turn = self.claim()
        repository.cache_result(turn['id'], 'worker', 'completed-node', {'draft':'已有结果'})
        repository.finish(turn['id'], 'worker', 'failed', '暂不可用')
        retry = repository.retry(self.session['id'], turn['id'], 'owner')
        self.assertEqual(retry['cache']['completed-node']['draft'], '已有结果')
        repository.claim(turn['id'], 'retry-worker')
        repository.finish(turn['id'], 'retry-worker', 'failed', '仍不可用')
        repository.save(self.session['id'], 'owner', 1, {'draft':'新内容'})
        with self.assertRaises(repository.Conflict):
            repository.retry(self.session['id'], turn['id'], 'owner')


if __name__ == '__main__':
    unittest.main()
