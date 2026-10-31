from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
                {'title':'处理工作邮件','angle':'筛出需要行动的信息'}]}])
        self.assertEqual(len(state['choices']), 2)
        self.assertEqual(state['article_state']['nodes']['topic']['status'], 'passed')
        state = self.run_turn(state, '选第二个，先不写', [
            {'action':'answer','selected_topic_index':1,'reply':'已选第二个。'}])
        self.assertEqual(state['article_state']['selected_title'], '处理工作邮件')
        self.assertEqual(state['preferences']['style'], '口语')
        self.assertEqual(state['choices'], [])

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

    def test_research_rejects_model_invented_source(self):
        article = runtime.initialize('写给上班族的邮件处理建议')
        article = runtime.resume(article, 'intent', {
            'intent':{'goal':'实用建议'}, 'audience':{'description':'上班族'},'topic':'处理邮件'})
        article = runtime.resume(article, 'topic', {'topic':'处理邮件','angle':'待办分类'})
        with self.assertRaisesRegex(ValueError, '未检索到'):
            runtime.fulfill(article, 'research', lambda prompt:{'evidence_pack':{
                'sources':{'records':[{'source_id':'fake','kind':'web','url':'https://invented.example/source'}]},
                'claims':[], 'research_status':'complete', 'limitations':[]}}, evidence={'sources':[], 'fetched':[]})

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


if __name__ == '__main__':
    unittest.main()
