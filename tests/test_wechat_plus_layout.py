from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
import pytest
from server import wechat_plus_layout as layout, wechat_plus_service as service, workbench
from tests import test_wechat_plus_service as plus_tests

LAYOUT_PLAN = {'first_screen': '标题与首段', 'components': ['callout'],
               'decoration_budget': 3, 'emphasis': '',
               'image_evidence': '', 'line_break_risks': ''}

DRAFT = '''# 如何整理会议记录

这里是正文，包含 [参考资料](https://example.com/guide?a=1&b=2) 和图片。

![配图](https://example.com/picture.png)

## 核对任务

保留原话，别猜测。

```python
if x < 2:
    print("a & b")
```'''

def test_native_render_keeps_text_links_images_and_code():
    # The Skill's converter owns the HTML now; the four local THEMES no longer
    # produce four different designs (the Skill's themes/ dir is empty), so the
    # contract is fidelity + a real native render, not colour variation.
    with patch.object(workbench, 'SKILL_DIR', Path(__file__).resolve().parents[1] / 'vendor/skills/weChat-autoCreate'):
        trace = {}
        html = layout.render(DRAFT, dict(layout.THEMES['clean'], id='clean'), trace=trace)
    assert trace['mode'] == 'skill-native-dsl'
    assert trace['renderer'] == 'toolkit.converter.MarkdownConverter'
    assert trace['gates']['layout']['returncode'] == 0
    # CDN images are an accepted finding, not a hard failure; the raw return
    # code stays visible and layout.check still warns the user.
    assert trace['gates']['compliance']['passed'] is True
    assert 'image_host_not_wechat' in trace['gates']['compliance']['accepted']
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.find('a')['href'] == 'https://example.com/guide?a=1&b=2'
    assert soup.find('img')['src'] == 'https://example.com/picture.png'
    assert '    print("a & b")' in soup.find('pre').get_text()
    assert '这里是正文' in soup.get_text()
    # The faithful converter keeps the link inline instead of appending footnotes.
    assert '参考链接' not in soup.get_text()

def test_auto_never_repeats_previous_and_refinements_keep_color():
    previous={'id':'tech','accent_color':'#346fac','heading_align':'center'}
    for _ in range(30):
        assert layout.choose('帮我选', previous)['id'] != 'tech'
        assert layout.choose('排版看看', previous)['id'] != 'tech'
        assert layout.choose('帮我选', previous, content='AI技术和工具')['id'] in {'clean','editorial'}
        assert layout.choose('排版', previous, fresh=True)['id'] != 'tech'
    changed = layout.choose('标题醒目，不要底色', previous)
    assert changed['id']=='tech' and changed['accent_color']=='#346fac'
    assert changed['no_heading_background'] and changed['prominent_heading'] and changed['heading_align']=='center'
    assert layout.choose('绿色',previous)['accent_color']=='#39845d'

def test_unsafe_html_is_not_delivered():
    with patch.object(workbench, 'SKILL_DIR', Path(__file__).resolve().parents[1] / 'vendor/skills/weChat-autoCreate'):
        with pytest.raises(ValueError): layout.render('# 标题\n\n<script>alert(1)</script>', layout.THEMES['clean'])

def test_format_preserves_draft_even_if_review_proposes_edits(tmp_path):
    case=plus_tests.NativeConversationTests(methodName='runTest');case.setUp()
    try:
        draft = '''# 整理会议记录

会议结束后，整理会议记录可以先从待办入手。这里举一个假设场景：团队讨论了页面改版，却没有明确谁负责整理反馈。把原始讨论直接压成摘要，可能保留了话题，却丢掉后续行动。

## 先区分讨论与决定

把记录分成已经确认的决定、尚未确定的问题和需要跟进的任务。有人说可以改按钮颜色，这只是建议；只有团队确认采用，才把它列为决定。缺少结论时写明待确认，不用猜测补齐。

## 再核对负责人

让工具输出原始发言、任务内容和负责人。找不到明确负责人，就保留空缺并在会后询问相关同事。整理的作用是暴露遗漏，不能把完整表格当成事实已经齐全。

## 最后回到原始材料

发出纪要前逐条核对讨论原文，删除没有依据的任务和承诺。涉及客户或公司敏感信息时，先按公司的资料处理要求选择工具，再决定是否上传。'''
        state=case.run_turn({}, '请用蓝色科技感排版：\n'+draft, [
            {'action':'format','existing_draft':draft,'layout_request':'蓝色科技感'},
            {'reader_simulation':[{'role':'读者','feedback':'清晰'}], 'revision_plan':[], 'revised_draft':'不应覆盖的内容'},
            LAYOUT_PLAN])
        assert state['article_state']['draft']==draft
        assert state['layout_theme']['id']=='tech'
        assert '换一种排版' in state['reply_options']
        preview=Path(state['article_state']['formatted_output']).read_text(encoding='utf-8')
        assert '不应覆盖的内容' not in preview and '先区分讨论与决定' in preview
        # Follow-up wording is a formatting action even if the planner mistakes it for chat.
        state2=case.run_turn(state, '换成绿色，标题居中，不要改正文', [
            {'action':'answer','reply':'好的','selected_topic_index':999,'explicit_topic':'不应替换的标题'},
            LAYOUT_PLAN])
        assert state2['last_action']=='format' and state2['article_state']['draft']==draft
        assert state2['layout_theme']['id']=='tech'
        assert state2['article_state']['selected_title']==state['article_state']['selected_title']
        assert state2['layout_theme']['accent_color']=='#39845d'
        assert state2['layout_theme']['heading_align']=='center'
        # The Skill owns typography now; Plus records the request but does not
        # inject its own text-align into the Skill-rendered fragment.
        assert state2['layout_capability']['mode'] == 'skill-native-dsl'
        assert '先区分讨论与决定' in Path(state2['article_state']['formatted_output']).read_text(encoding='utf-8')
        state2['last_action']='review'
        state3=case.run_turn(state2, '沉稳编辑', [{'action':'answer','reply':'好的'}, LAYOUT_PLAN])
        assert state3['last_action']=='format' and state3['layout_theme']['id']=='editorial'
        assert state3['article_state']['draft']==draft
    finally: case.tearDown()


def test_external_image_is_kept_and_its_limitation_is_visible():
    with patch.object(workbench, 'SKILL_DIR', Path(__file__).resolve().parents[1] / 'vendor/skills/weChat-autoCreate'):
        html = layout.render(DRAFT, dict(layout.THEMES['clean'],id='clean'))
        warnings = layout.check(html)
    assert 'https://example.com/picture.png' in html
    assert any('外部图片' in warning for warning in warnings)


def test_preexisting_preview_survives_blocked_reformat(tmp_path):
    case=plus_tests.NativeConversationTests(methodName='runTest');case.setUp()
    try:
        article=service.runtime.initialize('原稿')
        article.update(draft='# 太短的原稿\n\n内容。',formatted_output=str(tmp_path / 'old.html'))
        old=article['formatted_output'];Path(old).write_text('old preview',encoding='utf8')
        def blocked(payload, node, generate, **kwargs):
            value=deepcopy(payload)
            value['nodes'][node]['status']='blocked'
            value['nodes'][node]['message']='测试阻塞'
            return value
        with patch.object(service.runtime,'fulfill',side_effect=blocked):
            state=case.run_turn({'article_state':article, 'layout_theme':{'id':'clean'},'last_action':'format'}, '换一种排版', [{'action':'format'}])
        assert state['_blocked'] is True
        assert state['article_state']['formatted_output']==old
        assert Path(old).read_text(encoding='utf8')=='old preview'
    finally: case.tearDown()

def test_worker_settles_format_and_refunds_blocked():
    from unittest.mock import patch
    from server import wechat_plus_tasks as tasks
    turn={'id':'turn','session_id':'session','user_id':'owner','input_version':1,'message':'排版'}
    session={'id':'session','version':1,'state':{'article_state':{'draft':'正文'},'layout_theme':{'id':'clean'}}}
    for blocked in (False, True):
        state={'last_action':'review' if blocked else 'format', '_blocked':blocked}
        with patch.object(tasks.repo,'claim',return_value=turn), patch.object(tasks.repo,'get',return_value=deepcopy(session)), \
             patch.object(tasks.repo,'commit_turn',return_value=True), patch.object(tasks.service,'execute',return_value=state), \
             patch.object(tasks.billing,'usage_for',return_value='usage'), patch.object(tasks.billing,'record') as record, \
             patch.object(tasks.accounts,'refund_usage') as refund, patch.object(tasks.accounts,'settle_usage_with_points') as settle:
            result=tasks.execute_turn.apply(args=['turn'],task_id='worker',throw=True).get()
            assert result['status']=='completed'
            if blocked:
                refund.assert_called_once()
                settle.assert_not_called()
                assert record.call_args.args[1:] == ('blocked',0)
            else:
                refund.assert_not_called()
                assert settle.call_args.args[-1] == tasks.accounts.plus_points_for('format')
                assert record.call_args.args[1:] == ('format',tasks.accounts.plus_points_for('format'))
