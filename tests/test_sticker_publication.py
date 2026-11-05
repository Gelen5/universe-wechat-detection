from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from server import creator_tools, main, wechat_plus_service


def test_plus_routes_sticker_without_model_or_chargeable_action(tmp_path):
    generate = Mock(side_effect=AssertionError('must not call model'))
    result = wechat_plus_service.execute({}, '给中年女人写一篇贴图文案', generate, output_dir=tmp_path)
    assert '前往「贴图号」' in result['messages'][-1]['content']
    assert result['last_action'] == 'answer'
    generate.assert_not_called()


def test_sticker_publication_uses_remix_contract(monkeypatch):
    output = {'titles':['标题一','标题二','标题三'], 'body':'正文', 'tags':['话题']}
    response = Mock(); response.json.return_value = {'choices':[{'message':{'content':'{}'}}]}
    monkeypatch.setattr(creator_tools.requests, 'post', lambda *a, **k: response)
    monkeypatch.setattr(creator_tools.workbench, '_salvage_json', lambda _: output)
    assert creator_tools.sticker_publication_copy({'plan':'测试'}) == output


def test_sticker_publication_refunds_on_failure(monkeypatch):
    monkeypatch.setattr(main.accounts, 'require_user', lambda request: {'id':'u'})
    monkeypatch.setattr(main.accounts, 'reserve_points', lambda *args: 'usage')
    refund = Mock(); monkeypatch.setattr(main.accounts, 'refund_usage', refund)
    monkeypatch.setattr(main.creator_tools, 'sticker_publication_copy', Mock(side_effect=RuntimeError('failure')))
    with pytest.raises(HTTPException) as error:
        main.generate_sticker_publication(main.StickerPublicationRequest(context='主题'), object())
    assert error.value.status_code == 502
    assert refund.call_args.args[0] == 'usage'
