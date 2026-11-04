from server.creator_tools import remix_text_policy
from server.creator_tools import remix_requires_dataset


def test_cover_only_and_whole_series_requests():
    assert remix_text_policy('封面不要标题文字') == 'cover_no_text'
    assert remix_text_policy('所有图片不要文字') == 'all_no_text'
    assert remix_text_policy('做一组无字图片') == 'all_no_text'
    assert remix_text_policy('标题用白色文字') == ''


def test_non_data_tutorial_does_not_trigger_statistical_gate():
    assert not remix_requires_dataset({'content_guess':'三步教程','summary':'禁止虚构数值'})
    assert remix_requires_dataset({'content_type':'data'})
    assert remix_requires_dataset({'image_brief':'横向条形图，全部地区与数值'})
