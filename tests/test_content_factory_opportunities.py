from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server import content_factory_opportunities as opportunities
from server.models import HotspotSnapshot, ImageBoardItem, LowfansArticle


def test_candidates_dedupe_and_reject_missing_evidence():
    engine = create_engine('sqlite:///:memory:')
    LowfansArticle.__table__.create(engine)
    with Session(engine) as session:
        for date in ('2026-11-05', '2026-11-06'):
            session.add(LowfansArticle(stat_date=date, range_type='7d', art_id='a', title='夫妻如何沟通',
                art_url='https://example.com/a', account_read_base=100, boost_ratio=20, read_num=100001))
        session.add(LowfansArticle(stat_date='2026-11-06', range_type='7d', art_id='b', title='没有基线',
            art_url='https://example.com/b', account_read_base=0, boost_ratio=20, read_num=100001))
        session.commit()
        result = opportunities.build_candidates(session, as_of=datetime(2026, 11, 7, tzinfo=timezone.utc))
    assert len(result) == 1
    assert result[0]['source']['observed_at'] == '2026-11-06'
    assert result[0]['source']['read_display'] == '10万+'
    assert result[0]['score_components']['verified_100k'] == 25


def test_history_match_does_not_create_reach_evidence(monkeypatch):
    monkeypatch.setattr(opportunities, 'collection', lambda: ([
        {'title': '成年子女与父母沟通', 'track': '情感', 'category': '家庭'},
        {'title': '如何维修汽车', 'track': '汽车', 'category': '生活'}], {}))
    matches = opportunities.match_topics('成年子女和父母沟通', '情感')
    assert len(matches) == 1
    assert matches[0]['id'] == 0
    assert '阅读量' not in matches[0]


def test_image_evidence_and_expired_hotspot_are_not_misclassified():
    engine = create_engine('sqlite:///:memory:')
    for table in (LowfansArticle.__table__, ImageBoardItem.__table__, HotspotSnapshot.__table__):
        table.create(engine)
    with Session(engine) as session:
        session.add(ImageBoardItem(stat_date='2026-11-06', sn='image', title='示例',
            art_url='https://example.com', image_num=1, word_num=20, video_num=0, read_num=100000))
        session.add(HotspotSnapshot(platform='a', title='示例', rank=1,
            captured_at=datetime(2026, 11, 1, tzinfo=timezone.utc)))
        session.commit()
        images = opportunities.classify_image_evidence(session)
        assert images[0]['classification'] == 'ordinary_image'
        assert opportunities.find_hotspots(session, '示例', as_of=datetime(2026, 11, 7, tzinfo=timezone.utc)) == []


def test_verified_image_is_not_hidden_behind_a_page_of_ordinary_rows():
    engine = create_engine('sqlite:///:memory:')
    for table in (LowfansArticle.__table__, ImageBoardItem.__table__):
        table.create(engine)
    with Session(engine) as session:
        # Older ordinary rows sort first by date/id; the one verified low-fan
        # image must still survive a small result window.
        for index in range(210):
            session.add(ImageBoardItem(stat_date='2026-11-06', sn=f'ordinary-{index:03d}',
                title='普通图文', art_url='https://example.com/o', image_num=1,
                word_num=20, video_num=0, read_num=1000))
        session.add(ImageBoardItem(stat_date='2026-11-05', sn='verified', title='低粉图文',
            art_url='https://example.com/v', image_num=2, word_num=30, video_num=0,
            read_num=100001, wx_type='其他'))
        session.add(LowfansArticle(stat_date='2026-11-06', art_id='verified', wx_type='其他',
            account_read_base=300, boost_ratio=40, read_num=100001))
        session.commit()
        images = opportunities.classify_image_evidence(session, limit=1)
    assert [item['id'] for item in images] == ['verified']
    assert images[0]['classification'] == 'verified_lowfans_image'
