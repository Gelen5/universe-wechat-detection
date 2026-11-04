from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

from server import wechat_plus_service as service
from server import wechat_plus_runtime as runtime
from server import workbench


ROOT = Path(__file__).resolve().parents[1]


class NativeConversationTests(unittest.TestCase):
    def setUp(self):
        self.skill = patch.object(workbench, 'SKILL_DIR', ROOT / 'vendor/skills/weChat-autoCreate')
        self.skill.start()
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()
        self.skill.stop()

    def run_turn(self, state, message, replies):
        responses = iter(replies)
        return service.execute(state, message, lambda prompt: next(responses), output_dir=self.output,
            search=lambda *args, **kwargs: {'status':'unavailable', 'sources':[], 'fetched':[], 'queries':[]})

    def test_native_topic_selection_and_preferences_survive_turns(self):
        state = self.run_turn({}, '给上班族写AI文章，口语一些', [
            {'action':'topics','audience':'上班族','goal':'实用建议','style':'口语'},
            {'topic':'AI工作效率','angle':'整理工作信息', 'title_candidates':[
                {'title':'整理会议记录','angle':'从原始材料到待办'},
                {'title':'处理工作邮件','focus':'筛出需要行动的信息'}]}])
        self.assertEqual(len(state['choices']), 2)
        self.assertEqual(state['article_state']['nodes']['topic']['status'], 'passed')
        state = self.run_turn(state, '选第二个，先不写', [
            {'action':'answer','selected_topic_index':1,'reply':'已选第二个。'}])
        self.assertEqual(state['article_state']['selected_title'], '处理工作邮件')
        self.assertEqual(state['article_state']['angle'], '筛出需要行动的信息')
        self.assertEqual(state['preferences']['style'], '口语')
        self.assertEqual(state['choices'], [])

    def test_stale_index_keeps_confirmed_topic_only_when_title_matches(self):
        state = self.run_turn({}, '给普通人推荐 AI 选题', [
            {'action':'topics','audience':'普通人','goal':'实用建议'},
            {'topic':'AI 办公','angle':'整理资料','title_candidates':[
                {'title':'整理材料','angle':'归类'}, {'title':'整理记录','angle':'核对'}]},
        ])
        state = self.run_turn(state, '选第二个', [
            {'action':'answer','selected_topic_index':1,'reply':'已选。'}])
        result = self.run_turn(state, '继续', [
            {'action':'answer','selected_topic_index':1,'explicit_topic':'整理记录','reply':'继续。'}])
        self.assertEqual(result['selected_topic']['title'], '整理记录')
        with self.assertRaisesRegex(ValueError, '所选选题不存在'):
            self.run_turn(state, '继续', [
                {'action':'answer','selected_topic_index':1,'explicit_topic':'其他题目','reply':'继续。'}])

    def test_missing_intent_fields_are_repaired_before_recommending_topics(self):
        message = '我想写一篇关于普通人使用 AI 提高工作效率的公众号文章，先帮我推荐几个选题。'
        state = self.run_turn({}, message, [
            {'action':'topics'},
            {'intent':{'goal':'介绍 AI 工作效率'}, 'audience':{}},
            {'intent':{}, 'audience':'普通人'},
            {'topic':'AI 工作效率', 'angle':'日常工作方法', 'title_candidates':[
                {'title':'先从整理信息开始','angle':'任务梳理'},
                {'title':'让会议记录更有用','angle':'会后行动'}]},
        ])
        self.assertEqual(state['last_action'], 'topics')
        self.assertEqual(len(state['choices']), 2)
        self.assertEqual(state['article_state']['intent']['goal'], '介绍 AI 工作效率')
        self.assertEqual(state['article_state']['audience']['description'], '普通人')
        self.assertNotIn('intent.search_intent', state['messages'][-1]['content'])
        self.assertNotIn('_blocked', state)

    def test_repeated_missing_intent_uses_explicit_unspecified_fields(self):
        message = '我想写一篇关于普通人使用 AI 提高工作效率的公众号文章，先帮我推荐几个选题。'
        state = self.run_turn({}, message, [
            {'action':'topics'}, {'intent':None, 'audience':None}, {'intent':{}, 'audience':{}},
            {'topic':'AI 工作效率', 'angle':'工作方法', 'title_candidates':[
                {'title':'让任务更清晰','angle':'梳理任务'}, {'title':'整理会议记录','angle':'提炼待办'}]},
        ])
        article = state['article_state']
        self.assertEqual(article['nodes']['intent']['status'], 'passed')
        self.assertEqual(article['audience']['status'], 'unspecified')
        self.assertIn(message, article['user_request'])
        self.assertTrue(any(item['node']=='intent' for item in article['degradations']))
        self.assertEqual(len(state['choices']), 2)
        self.assertNotIn('intent.search_intent', state['messages'][-1]['content'])

    def test_intent_repair_does_not_overwrite_user_preferences(self):
        state = self.run_turn({}, '给普通人推荐 AI 选题', [
            {'action':'topics','audience':'普通人','goal':'提供实用建议'},
            {'topic':'AI 办公','angle':'整理资料','title_candidates':[
                {'title':'整理材料','angle':'归类'}, {'title':'整理记录','angle':'核对'}]},
        ])
        self.assertEqual(state['article_state']['audience']['description'], '普通人')
        self.assertEqual(state['article_state']['intent']['goal'], '提供实用建议')

    def test_intent_normalizer_keeps_existing_goal_and_reader(self):
        previous = {'intent': {'goal':'原有目标'}, 'audience': {'description':'普通人','status':'user_provided'}}
        result = runtime.normalize_intent_result({'intent': {'goal':'不同目标', 'search_intent':'invalid'},
                                                  'audience':'企业老板'}, previous)
        self.assertEqual(result['intent']['goal'], '原有目标')
        self.assertNotIn('search_intent', result['intent'])
        self.assertEqual(result['audience'], previous['audience'])

    def test_incomplete_topic_result_does_not_expose_internal_prompt(self):
        with self.assertRaisesRegex(ValueError, '生成结果未完整返回') as error:
            self.run_turn({}, '给普通人推荐 AI 选题', [
                {'action':'topics','audience':'普通人','goal':'实用建议'},
                {'topic':'AI 办公','title_candidates':[]},
            ])
        self.assertNotIn('intent.search_intent', str(error.exception))

    def test_clarification_does_not_run_article_generation(self):
        state = self.run_turn({}, '想写AI', [
            {'action':'clarify','reply':'想写给谁看？','options':['上班族','开发者']}])
        self.assertEqual(state['reply_options'], ['上班族','开发者'])
        self.assertEqual(state['article_state']['nodes']['draft']['status'], 'pending')
        self.assertEqual(state['article_state']['draft'], '')

    def test_unselected_topic_cannot_silently_generate_a_draft(self):
        state = self.run_turn({}, 'AI', [
            {'action':'write','audience':'上班族','goal':'了解AI'},
            {'topic':'AI','angle':'工作方法','title_candidates':[
                {'title':'整理材料','angle':'材料'}, {'title':'会议记录','angle':'记录'}]}])
        self.assertEqual(state['last_action'], 'topics')
        self.assertEqual(state['article_state']['draft'], '')

    def test_research_drops_model_invented_source_without_failing(self):
        article = runtime.initialize('写给上班族的邮件处理建议')
        article = runtime.resume(article, 'intent', {
            'intent':{'goal':'实用建议'}, 'audience':{'description':'上班族'},'topic':'处理邮件'})
        article = runtime.resume(article, 'topic', {'topic':'处理邮件','angle':'待办分类'})
        article = runtime.fulfill(article, 'research', lambda prompt:{'evidence_pack':{
            'sources':{'records':[{'source_id':'fake','kind':'web','title':'虚构来源',
                'url':'https://invented.example/source'}]},
            'claims':[{'claim_id':'claim-fake','text':'虚构主张','source_ids':['fake']}],
            'research_status':'complete', 'limitations':[]}}, evidence={'sources':[], 'fetched':[]})
        pack = article['evidence_pack']
        self.assertEqual(pack['sources']['records'], [])
        self.assertEqual(pack['claims'], [])
        self.assertTrue(any('不在本次检索范围内' in item for item in pack['limitations']))
        self.assertEqual(article['nodes']['research']['status'], 'passed')

    def test_observed_research_aliases_preserve_unverified_status_and_limits(self):
        result = runtime.normalize_research({
            'sources':[{'id':'src_001','title':'参考资料','url':'https://example.com/source',
                'verification':'fetched_excerpt','notes':'仅作旁证'},
                {'id':'excluded','type':'public_web','title':'只有标题的结果','use_in_article':False,'exclusion_reason':'未取得正文'}],
            'claims':[{'id':'claim_001','claim':'这是一个方法建议','type':'opinion',
                'source_ids':['src_001'],'status':'illustrative','notes':'不能写成作者亲历','usage':'不得作为效果结论'}],
            'research_status':{'status':'partial','assessment':'未核验直接证据','conditions':['不写效果数字']},
            'limitations':['材料不完整']})
        pack = result['evidence_pack']
        article = runtime.initialize('写一篇方法建议')
        article['evidence_pack'] = pack
        states, _ = runtime.skill_article_adapter._skill_modules()
        native = states.ArticleState.from_dict(article)
        self.assertEqual(native.evidence_pack.sources.records[0].status, 'unverified')
        self.assertEqual(native.evidence_pack.claims[0].kind, 'opinion')
        self.assertEqual(native.evidence_pack.research_status, 'partial')
        self.assertIn('不写效果数字', native.evidence_pack.limitations)
        self.assertIn('claim_001: 不能写成作者亲历', native.evidence_pack.limitations)
        self.assertIn('claim_001: 不得作为效果结论', native.evidence_pack.limitations)
        self.assertEqual(len(native.evidence_pack.sources.records), 1)

    def test_cancellation_interrupts_before_model_call(self):
        def cancelled():
            raise service.Cancelled('cancelled')
        with self.assertRaises(service.Cancelled):
            service.execute({}, '写文章', lambda _: self.fail('should not call model'),
                output_dir=self.output, check_cancelled=cancelled)

    def test_imported_article_goes_directly_to_native_review_and_delivery(self):
        draft = '''# 整理会议记录

会议结束后，整理会议记录可以先从待办入手。这里举一个假设场景：团队讨论了页面改版，却没有明确谁负责整理反馈。把原始讨论直接压成摘要，可能保留了话题，却丢掉后续行动。

## 先区分讨论与决定

把记录分成已经确认的决定、尚未确定的问题和需要跟进的任务。有人说可以改按钮颜色，这只是建议；只有团队确认采用，才把它列为决定。缺少结论时写明待确认，不用猜测补齐。

## 再核对负责人

让工具输出原始发言、任务内容和负责人。找不到明确负责人，就保留空缺并在会后询问相关同事。整理的作用是暴露遗漏，不能把完整表格当成事实已经齐全。

## 最后回到原始材料

发出纪要前逐条核对讨论原文，删除没有依据的任务和承诺。涉及客户或公司敏感信息时，先按公司的资料处理要求选择工具，再决定是否上传。'''
        state = self.run_turn({}, '请直接排版下面的原稿：\n' + draft, [
            {'action':'format','existing_draft':draft},
            {'reader_simulation':[{'role':'目标读者','feedback':'步骤可以执行'}], 'revision_plan':[]}])
        article = state['article_state']
        self.assertEqual(article['nodes']['delivery']['status'], 'passed')
        self.assertTrue(Path(article['formatted_output']).is_file())
        self.assertEqual(article['draft'], draft)
        self.assertEqual(article['evidence_pack']['sources']['records'][0]['kind'], 'user')

    def test_review_block_preserves_original_article_and_report(self):
        state = self.run_turn({}, '排版这篇原稿：\n# 简短文章\n太短了。', [
            {'action':'format','existing_draft':'# 简短文章\n太短了。'}])
        article = state['article_state']
        self.assertEqual(article['nodes']['review']['status'], 'blocked')
        self.assertEqual(article['draft'], '# 简短文章\n太短了。')
        self.assertTrue(article['quality_report']['hard_gate']['blocked'])
        self.assertFalse(article['formatted_output'])

    def test_layout_preview_for_missing_information_anchor_keeps_review_warning(self):
        draft = ('# 关于陪伴的思考\n\n' + ('陪伴需要尊重每个人的想法，也需要认真倾听。每个人都有自己的选择，关心应当从理解开始。\n\n' * 20)).strip()
        state = self.run_turn({}, '请用温暖故事风格排版：\n' + draft, [
            {'action':'format','existing_draft':draft}])
        article = state['article_state']
        self.assertEqual(article['draft'], draft)
        self.assertEqual(article['nodes']['review']['status'], 'blocked')
        self.assertNotEqual(article['nodes']['delivery']['status'], 'passed')
        self.assertTrue(article['quality_report']['hard_gate']['blocked'])
        self.assertTrue(Path(article['formatted_output']).is_file())
        self.assertTrue(any('正文复核' in warning for warning in state['layout_warnings']))

    def test_requesting_alternative_topics_does_not_mutate_existing_article(self):
        article = runtime.initialize('给上班族写邮件处理建议')
        article = runtime.resume(article, 'intent', {'intent':{'goal':'实用建议'},
            'audience':{'description':'上班族'},'topic':'处理邮件'})
        article = runtime.resume(article, 'topic', {'topic':'处理邮件','angle':'行动分类'})
        article['draft'] = '需要保留的原稿'
        article['evidence_pack']['research_status'] = 'partial'
        state = self.run_turn({'article_state':article,'selected_topic':{'title':'处理邮件'}}, '另外推荐几个新选题，原稿先保留', [
            {'action':'topics'},
            {'topic':'会议记录','angle':'会后执行','title_candidates':[
                {'title':'整理待办','angle':'任务'}, {'title':'核对结论','angle':'结论'}]}])
        self.assertEqual(state['article_state']['draft'], '需要保留的原稿')
        self.assertEqual(state['article_state']['topic'], '处理邮件')
        self.assertEqual(len(state['choices']), 2)

    def test_planner_echo_of_current_draft_is_not_a_new_import(self):
        article = runtime.initialize('写给上班族的邮件处理建议')
        article['draft'] = '已经保存的正文'
        article['evidence_pack']['limitations'] = ['保留原有证据限制']
        state = self.run_turn({'article_state':article}, '先保留正文，不需要重新导入', [
            {'action':'answer','existing_draft':'已经保存的正文','reply':'保留当前正文。'}])
        self.assertEqual(state['article_state']['draft'], '已经保存的正文')
        self.assertEqual(state['article_state']['evidence_pack']['limitations'], ['保留原有证据限制'])
        self.assertNotIn('imported', state)

    def test_importing_a_different_article_replaces_stale_title_and_preserves_old_draft(self):
        article = runtime.initialize('之前的选题')
        article.update(selected_title='之前的标题', topic='之前的选题', draft='之前保存的正文')
        imported = '# 新稿标题\n\n这是用户新贴入的正文。'
        state = self.run_turn({'article_state':article}, '保存下面的新稿，暂时不用处理：\n'+imported, [
            {'action':'answer','existing_draft':imported,'reply':'已保存新稿。'}])
        self.assertEqual(state['article_state']['selected_title'], '新稿标题')
        self.assertEqual(state['article_state']['topic'], '新稿标题')
        self.assertEqual([version['draft'] for version in state['versions']], ['之前保存的正文', imported])

    def test_provider_failure_uses_sol_fallback(self):
        observed = []
        def generate(prompt, *, model=None, base_url=None):
            observed.append((model, workbench._setting('WECHAT_TEXT_MODEL')))
            if len(observed) == 1:
                raise workbench.ProviderError('unavailable')
            return {'ok': True}
        with patch.dict(os.environ, {'WECHAT_PLUS_TEXT_MODEL':'gpt-6.1-terra',
                                    'WECHAT_PLUS_FALLBACK_MODEL':'gpt-6.1-sol'}), \
             patch.object(workbench.accounts, 'provider_settings', return_value={}), \
             patch.object(workbench, '_json_text', side_effect=generate):
            self.assertEqual(service.generate_json('test'), {'ok': True})
        self.assertEqual(observed, [('gpt-6.1-terra','gpt-6.1-terra'),
                                    ('gpt-6.1-sol','gpt-6.1-sol')])

    def test_plus_model_override_does_not_change_legacy_request_settings(self):
        observed = []
        def generate(prompt, *, model=None, base_url=None):
            observed.append((model, workbench._setting('WECHAT_TEXT_MODEL')))
            return {'ok':True}
        with patch.dict(os.environ, {'WECHAT_PLUS_TEXT_MODEL':'claude-sonnet-5-5'}), \
             patch.object(workbench.accounts, 'provider_settings', return_value={'text_model':'legacy-writer'}), \
             patch.object(workbench, '_json_text', side_effect=generate):
            with workbench.provider_overrides(text_model='legacy-writer'):
                self.assertEqual(service.generate_json('test'), {'ok':True})
                self.assertEqual(workbench._setting('WECHAT_TEXT_MODEL'), 'legacy-writer')
        self.assertEqual(observed, [('claude-sonnet-5-5','claude-sonnet-5-5')])


if __name__ == '__main__':
    unittest.main()


def test_plus_api_worker_recovers_missing_intent_and_settles_topics(tmp_path):
    from tests import test_wechat_plus_api as api_tests
    from server import wechat_plus_tasks as tasks, accounts
    case = api_tests.PlusAPITests(methodName='runTest')
    case.setUp()
    try:
        row = case.client.post('/api/wechat-plus/sessions', json={'title':'AI 工作效率'}, headers=case.headers).json()['session']
        message = '我想写一篇关于普通人使用 AI 提高工作效率的公众号文章，先帮我推荐几个选题。'
        sent = case.client.post('/api/wechat-plus/sessions/'+row['id']+'/messages', headers=case.headers,
            json={'message':message,'version':1,'idempotency_key':'intent-repair-test-1'})
        assert sent.status_code == 202
        turn_id = sent.json()['turn']['id']
        responses = iter([
            {'action':'topics'},
            {'intent':{'goal':'介绍 AI 工作效率'}, 'audience':{}},
            {'intent':{}, 'audience':'普通人'},
            {'topic':'AI 工作效率','angle':'工作方法','title_candidates':[
                {'title':'先整理任务','angle':'工作优先级'}, {'title':'核对会议记录','angle':'会后行动'}]},
        ])
        with patch.object(workbench, 'SKILL_DIR', ROOT/'vendor/skills/weChat-autoCreate'), \
             patch.object(workbench, 'OUTPUT_DIR', tmp_path), \
             patch.object(tasks.service, 'generate_json', side_effect=lambda prompt: next(responses)):
            result = tasks.execute_turn.apply(args=[turn_id], task_id='test-worker', throw=True).get()
        assert result['status'] == 'completed'
        loaded = case.client.get('/api/wechat-plus/sessions/'+row['id'],headers=case.headers).json()['session']
        assert len(loaded['state']['choices']) == 2
        assert loaded['state']['article_state']['audience']['description'] == '普通人'
        assert loaded['state']['last_action'] == 'topics'
        assert accounts.wallet_summary('owner')['balance'] == 98
        assert loaded['turns'][0]['status'] == 'completed'
    finally:
        case.tearDown()


def test_plus_api_worker_refunds_incomplete_topic_without_internal_prompt(tmp_path):
    from tests import test_wechat_plus_api as api_tests
    from server import wechat_plus_tasks as tasks, accounts
    case = api_tests.PlusAPITests(methodName='runTest')
    case.setUp()
    try:
        row = case.client.post('/api/wechat-plus/sessions', json={'title':'AI 选题'}, headers=case.headers).json()['session']
        sent = case.client.post('/api/wechat-plus/sessions/'+row['id']+'/messages', headers=case.headers,
            json={'message':'给普通人推荐 AI 选题','version':1,'idempotency_key':'intent-failure-test-1'})
        assert sent.status_code == 202
        turn_id = sent.json()['turn']['id']
        responses = iter([{'action':'topics','audience':'普通人','goal':'实用建议'},
                          {'topic':'AI 办公','title_candidates':[]}])
        with patch.object(workbench, 'SKILL_DIR', ROOT/'vendor/skills/weChat-autoCreate'), \
             patch.object(workbench, 'OUTPUT_DIR', tmp_path), \
             patch.object(tasks.service, 'generate_json', side_effect=lambda prompt: next(responses)):
            result = tasks.execute_turn.apply(args=[turn_id], task_id='test-worker', throw=True).get()
        assert result['status'] == 'failed'
        loaded = case.client.get('/api/wechat-plus/sessions/'+row['id'],headers=case.headers).json()['session']
        assert loaded['turns'][0]['status'] == 'failed'
        assert 'intent.search_intent' not in loaded['turns'][0]['error']
        assert '未完整返回' in loaded['turns'][0]['error']
        assert accounts.wallet_summary('owner')['balance'] == 100
    finally:
        case.tearDown()
