import requests
from server.content_factory_detector import detect


class Reply:
    def __init__(self, result): self.result = result
    def raise_for_status(self): pass
    def json(self): return self.result


def test_zhuque_returns_human_ratio_and_actual_makers_tokens():
    result = detect('正文', key='test', post=lambda *a, **k: Reply({
        'status':'success', 'labels_ratio':{'0':0.84}, 'usage':{'total_tokens':300},
        'makers_models_usage':{'total_tokens':45}}))
    assert result['human_ratio'] == .84 and result['makers_tokens'] == 45


def test_zhuque_fails_closed_for_unknown_and_errors():
    assert detect('正文', key='')['status'] == 'unavailable'
    assert detect('正文', key='test', post=lambda *a, **k: Reply({'status':'success'}))['status'] == 'failed'
    assert detect('正文', key='test', post=lambda *a, **k: Reply({'status':'success','labels_ratio':{'0':'nan'}}))['status'] == 'failed'
    def unavailable(*args, **kwargs): raise requests.Timeout()
    assert detect('正文', key='test', post=unavailable)['status'] == 'failed'
