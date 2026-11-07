import pytest

from server.content_factory_titles import prompt_for, validate_titles


def test_platform_contracts_are_distinct():
    args = dict(topic='家庭沟通', track='情感', audience='成年人', angle='具体表达')
    assert '三条' in prompt_for('article', **args)
    assert 'image_text' in prompt_for('image', **args)
    assert prompt_for('article', **args) != prompt_for('image', **args)


def test_article_requires_three_distinct_original_titles():
    data = {'main_title': '家庭沟通从听懂开始', 'alternative_titles': ['说清楚需求才更容易商量',
            '给亲密关系留一点空间', '吵架之后如何继续对话'], 'strategy': '问题解决', 'reason': '围绕沟通'}
    assert len(validate_titles('article', data)['alternative_titles']) == 3
    with pytest.raises(ValueError):
        validate_titles('article', {**data, 'alternative_titles': ['家庭沟通从听懂开始'] * 3})
    with pytest.raises(ValueError):
        validate_titles('article', data, source_titles=['家庭沟通从听懂开始'])


def test_image_requires_caption_and_tags():
    data = {'main_title': '好好说话让关系更近', 'alternative_titles': ['认真听完对方的话', '争执之后如何和好'],
            'image_text': '慢一点说', 'caption': '留出说话的空间。', 'tags': ['家庭', '沟通', '生活'],
            'strategy': '家庭情感', 'reason': '围绕对话'}
    assert validate_titles('image', data)['image_text'] == '慢一点说'
    with pytest.raises(ValueError):
        validate_titles('image', {**data, 'tags': []})
