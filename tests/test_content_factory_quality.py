from server.content_factory_quality import publication_decision


def test_article_requires_real_detector_and_all_checks():
    source = {'id': 'a', 'url': 'https://example.com/a', 'observed_at': '2026-11-07'}
    checks = {key: True for key in ('facts', 'copyright', 'safety', 'title_consistency',
                                    'editorial_quality', 'storage')}
    base = dict(product_type='article', title='标题', content='文' * 1000, source=source, checks=checks)
    assert publication_decision(**base)['status'] == 'held'
    assert publication_decision(**base, detector={'status':'success','human_ratio':0.79})['status'] == 'held'
    assert publication_decision(**base, detector={'status':'success','human_ratio':0.8})['status'] == 'eligible'
    assert publication_decision(**{**base, 'content':'短文'}, detector={'status':'success','human_ratio':1})['status'] == 'held'


def test_image_unknown_vision_or_source_never_passes():
    checks = {key: True for key in ('facts', 'copyright', 'safety', 'title_consistency',
                                    'editorial_quality', 'storage', 'image_decode',
                                    'image_dimensions', 'image_text')}
    result = publication_decision('image', title='标题', content='文案', source={}, checks=checks)
    assert result['status'] == 'held'
    assert 'missing_source' in result['reasons']
    assert 'check_not_passed:visual_quality' in result['reasons']
