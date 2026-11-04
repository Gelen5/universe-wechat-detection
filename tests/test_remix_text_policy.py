from server.creator_tools import remix_text_policy


def test_cover_only_and_whole_series_requests():
    assert remix_text_policy('封面不要标题文字') == 'cover_no_text'
    assert remix_text_policy('所有图片不要文字') == 'all_no_text'
    assert remix_text_policy('做一组无字图片') == 'all_no_text'
    assert remix_text_policy('标题用白色文字') == ''
