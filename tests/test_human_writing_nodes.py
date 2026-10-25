"""Both execution paths consume the same bounded rules; no provider/detector calls."""
import hashlib
import importlib
import importlib.util
import sys
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from server import skill_article_adapter, skill_runtime, workbench as w

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'vendor/skill-extensions/weChat-autoCreate'


def native_modules():
    # Exercise this checkout's Skill even if an operator configured another install.
    name = 'human_node_test_toolkit'
    if name not in sys.modules:
        root = ROOT / 'vendor/skills/weChat-autoCreate/toolkit'
        spec = importlib.util.spec_from_file_location(name, root/'__init__.py', submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return importlib.import_module(name+'.article_state'), importlib.import_module(name+'.article_workflow')



@pytest.mark.parametrize('node', ['strategy', 'draft', 'review'])
def test_native_host_requests_and_web_share_rule_content_and_hash(node):
    state_module, workflow = native_modules()
    state = workflow.new_article_state('解释普通人如何使用 AI，不编造经历')
    for prior in state_module.ARTICLE_NODES[:state_module.ARTICLE_NODES.index(node)]:
        state.nodes[prior].status = 'passed'
    if node in {'draft','review'}:
        state.outline = [{'content':'解释问题'}]
        state.writing_strategy = {'article_type':'tutorial'}
    if node == 'review':
        state.draft = '# 使用方法\n\n先阅读说明，再按步骤操作。'
    with patch.object(workflow, '_quality_report', return_value={'blocked':False}):
        workflow.run_node(state, node)
    request = state.nodes[node].request
    text, manifest = skill_runtime.node_rules(node)
    assert len(text)<2000  # A short per-node protocol, not the full archived essay.
    assert request['rule_manifest'] == manifest
    assert text in request['rules']
    raw = Path(manifest[0]['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest[0]['sha256']
    assert manifest[0]['path'] in request['read']
    assert '过检承诺' in text or '过检比例' in text or '通过保证' in text


def test_rules_are_node_scoped_and_delivery_does_not_load_them():
    assert skill_runtime.node_rules('delivery') == ('', [])
    assert skill_runtime.node_rules('topic') == ('', [])
    draft, _ = skill_runtime.node_rules('draft')
    assert '策略节点' not in draft and '复核节点' not in draft
    review, _ = w._review_skill_context(w.ANTI_AI_SKILL_DIR)
    assert '全文至少有一个' not in review
    assert '原话' in review and '不能单独作为改稿理由' in review


@pytest.mark.parametrize('article_type,brief', [
    ('story','根据我提供的真实经历写故事'),
    ('opinion','只解释观点，没有人物素材'),
    ('tutorial','给出带编号的操作步骤'),
    ('news','保留资讯来源、数字与限定条件'),
])
def test_strategy_is_carried_into_first_draft_without_extra_calls(article_type,brief):
    captured=[]
    strategy={'article_type':article_type,'expression_mode':'按照材料决定',
              'available_materials':[], 'material_gaps':['没有额外亲历材料'],
              'forbidden_additions':['不得编造数字与对话']}
    def framework(prompt, **kwargs):
        captured.append(prompt)
        return {'name':'问题树','outline':['问题','解释'],'writing_strategy':strategy}
    def draft(prompt, **kwargs):
        captured.append(prompt)
        return '# 使用方法\n\n只使用给定材料。'
    with patch.object(w, '_require_skill'), \
         patch.object(w, '_record_skill'), \
         patch.object(w, '_json_text', side_effect=framework) as framework_call, \
         patch.object(w, '_text', side_effect=draft) as draft_call:
        frame=w._framework('使用方法','普通作者',brief,session={'topic_research':{'sources':[{'url':'https://example.com','title':'原始材料'}]}})
        w._draft('使用方法',frame,'普通作者',brief)
    assert frame['writing_strategy']==strategy
    assert framework_call.call_count==1 and draft_call.call_count==1
    assert '先确定适合这篇文章' in captured[0]
    assert '第一次成稿就具体' in captured[1]
    assert json.dumps(strategy,ensure_ascii=False) in captured[1]
    assert '不故意插入病句' in captured[1]


def test_legacy_framework_drafts_without_an_extra_strategy_request():
    with patch.object(w, '_require_skill'), patch.object(w, '_record_skill'), \
         patch.object(w, '_text', return_value='# 教程\n\n① 安装环境。\n② 运行测试。') as text, \
         patch.object(w, '_json_text') as extra:
        result=w._draft('教程',{'name':'旧任务','outline':['安装','测试']},'普通作者')
    assert '①' in result and text.call_count==1 and extra.call_count==0


def test_older_model_response_does_not_force_an_article_type_or_retry():
    with patch.object(w,'_require_skill'), patch.object(w,'_record_skill'), \
         patch.object(w,'_json_text',return_value={'name':'时间线','outline':['开始','结束']}) as model:
        frame=w._framework('真实故事','作者','根据提供的经历写作',session={'topic_research':{'sources':[{'url':'https://example.com'}]}})
    assert frame['writing_strategy']['article_type']=='unspecified'
    assert frame['writing_strategy']['available_materials']==[]
    assert model.call_count==1


def test_strategy_survives_article_state_resume():
    _, workflow=skill_article_adapter._skill_modules()
    state=workflow.new_article_state('写一篇教程')
    state.outline=[{'content':'操作步骤'}]
    strategy={'article_type':'tutorial','material_gaps':['未提供亲历']}
    state.writing_strategy={'name':'问题树','writing_strategy':strategy}
    session={}
    skill_article_adapter.hydrate_session(session,state.to_dict())
    assert session['framework']['writing_strategy']==strategy


def test_native_upstream_without_extension_keeps_its_original_contract(tmp_path):
    _,workflow=native_modules()
    state=workflow.new_article_state('解释一个概念')
    absent_install=tmp_path/'vendor/skills/weChat-autoCreate/toolkit/article_workflow.py'
    with patch.object(workflow,'__file__',str(absent_install)):
        workflow._host_request(state,'draft','写作',{'draft':'markdown string'})
    assert state.nodes['draft'].request['read']==['references/writing-protocol.md']
    assert 'rule_manifest' not in state.nodes['draft'].request


def test_native_patch_reapplies_after_upstream_sync(tmp_path):
    files=['vendor/skills/weChat-autoCreate/toolkit/article_workflow.py','vendor/skills/weChat-autoCreate/SKILL.md']
    for name in files:
        target=tmp_path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    patchfile=str(EXT/'native-node-rules.patch')
    for args in [['--reverse','--check'],['--reverse'],['--check'],[]]:
        subprocess.run(['git','apply',*args,patchfile],cwd=tmp_path,check=True,capture_output=True)
    for name in files:
        assert (tmp_path/name).read_text(encoding='utf-8')==(ROOT/name).read_text(encoding='utf-8')


def test_original_methodology_is_preserved_verbatim():
    raw = (EXT/'references/anti-ai-methodology.md').read_bytes()
    original = subprocess.check_output(['git','show','8a5ec09:vendor/skill-extensions/weChat-autoCreate/references/anti-ai-methodology.md'],cwd=ROOT)
    assert raw.replace(b'\r\n',b'\n')==original.replace(b'\r\n',b'\n')
