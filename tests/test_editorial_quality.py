from unittest.mock import patch
import pytest
from server import workbench,creator_tools


def test_shared_creation_adds_editorial_rules_without_changing_schema():
    with patch.object(workbench,'_text',return_value='{"titles":["甲","乙","丙"]}') as model:
        result=workbench._json_text('生成标题，返回titles数组')
    assert result['titles']==['甲','乙','丙']
    prompt=model.call_args.args[0]
    assert '三个候选是否真的不同' in prompt
    assert '不能把数量偷换成比例' in prompt


def test_non_creation_request_is_not_modified():
    with patch.object(workbench,'_text',return_value='{"ok":true}') as model:
        workbench._json_text('核实该事实，返回ok')
    assert '标题与配文质量要求' not in model.call_args.args[0]


def test_duplicate_publication_titles_are_rejected():
    with pytest.raises(ValueError,match='重复'):
        creator_tools.validate_remix_publication_copy({'titles':['同一个标题','同一个标题！','第三个标题'],'body':'正文','tags':[]})
