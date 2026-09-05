"""Explicit opt-in live provider smoke, with isolated sessions and billing data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import accounts, creator_conversation as c, workbench as w


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--image', action='store_true')
    parser.add_argument('--diagnose')
    parser.add_argument('--remaining', action='store_true')
    parser.add_argument('--image-only', action='store_true')
    args = parser.parse_args()
    settings = accounts.provider_settings(include_secrets=True)
    for field, env in [('text_api_key','WECHAT_TEXT_API_KEY'), ('image_api_key','WECHAT_IMAGE_API_KEY'),
                       ('text_base_url','WECHAT_TEXT_API_BASE_URL'), ('image_base_url','WECHAT_IMAGE_API_BASE_URL'),
                       ('text_model','WECHAT_TEXT_MODEL'), ('image_model','WECHAT_IMAGE_MODEL')]:
        if settings.get(field): os.environ[env] = settings[field]
    with tempfile.TemporaryDirectory(prefix='conversation-smoke-') as directory:
        accounts.DB_PATH = Path(directory) / 'accounts.db'
        accounts.init_db()
        user = accounts.create_user('smoke@example.com', secrets.token_urlsafe(24), 'smoke', role='admin')
        accounts.recharge(user['id'], user['id'], 1000, 'trial', 'isolated verification')
        w.OUTPUT_DIR = Path(directory) / 'workbench'
        def turn(skill, text, session=None):
            start = time.monotonic()
            result = c.chat(skill, text, user['id'], session['id'] if session else None)
            print(json.dumps({'skill':skill,'seconds':round(time.monotonic()-start,1),
                              'tools':[{'tool':v['tool'], 'error':v.get('error')} for v in result.get('last_tool_results', [])]}, ensure_ascii=False), flush=True)
            return result
        morning = None
        if args.image_only:
            morning = turn('morning', '规划1张花卉早安图，2条文案，不要边框。先只做方案。')
            morning = turn('morning', '确认，请生成这1张图片。', morning)
            assert len(morning['artifacts']['draft']['images']) == 1
            print(json.dumps({'image': morning['artifacts']['draft']['images'][0]}), flush=True)
            return
        if not args.remaining:
            morning = turn('morning', '请生成2条早安祝福文案，纯文案不要图片。主题是周末放松。直接生成。')
            assert morning['artifacts']['draft']['cards'] == []
            assert len(morning['artifacts']['draft']['copies']) == 2
            copies = morning['artifacts']['draft']['copies']
            morning = turn('morning', '仅将输出模式改为贴图模式，原文案完全保留，不重新生成。', morning)
            assert morning['artifacts']['draft']['copies'] == copies
            assert morning['artifacts']['draft']['mode'] == 'sticker'
            xhs = turn('xiaohongshu', '生成一篇小红书纯文字笔记，不要图片。主题是周末整理书桌，约200字，不编造个人经历。直接生成。')
            assert xhs['artifacts']['draft']['cards'] == []
            tie = turn('tie-tu', '只生成一条关于清晨散步的配套文案，不要任何图片。直接生成。')
            assert tie['artifacts']['draft']['cards'] == []
            reviewed = turn('hit-detector', '请复核这段文章，不改稿。标题：周末整理书桌。正文：先把桌面上的物品分成常用和暂时不用两类。常用物品放在手边，暂时不用的放回柜子。整理完先试用一天，再调整位置。不需要为了整齐购买新的收纳用品。')
            assert 'report' in reviewed['artifacts']
        article = '''# 周末整理书桌，先从手边开始

整理书桌不一定要买收纳盒。先看看每天真正使用的东西，再决定哪些物品需要留在桌面上。整理的目的不是拍出一张漂亮照片，而是让下一次坐下来工作时，能够顺手找到需要的东西。

## 先清出一小块空间

可以从键盘旁边开始，把这一小块区域里的纸张、杯子和杂物移开。不要急着清空整张桌子，以免一下子摊开太多东西，最后没有时间收尾。留下一个明确的小目标，比周末反复计划整理整个房间更容易开始。

## 按使用频率决定位置

每天使用的笔和记事本可以放在手边，偶尔才用的工具放进抽屉。暂时无法决定去留的东西，先放在一个单独的位置，过几天再看。不要因为某件东西看起来适合桌面，就忽略了自己实际使用它的频率。

## 试用之后再调整

整理完并不是结束。照常使用这张桌子一天，留意哪些动作仍然不顺手。充电线是不是太远，常用的本子是不是被压在下面，都可以在使用之后慢慢调整。不必为了保持整齐而让日常操作变得麻烦。

先完成一小块，再观察它是否真的好用。留下足够的空间，也给之后的调整留一点余地。'''
        session = {'id': secrets.token_hex(16), 'user_id': user['id'], 'topic': '周末整理书桌，先从手边开始',
                   'article': article, 'framework': {}, 'theme': 'default', 'current_step': 5,
                   'review': None, 'images': [], 'conversation': []}
        accounts.save_workbench_session(user['id'], session)
        start = time.monotonic()
        with w.provider_overrides():
            formatted = w.chat(session['id'], '不要图片，直接排版，正文一个字也不要改。', user_id=user['id'])
            assert formatted['article'] == article and formatted['current_step'] == 6
            assert formatted['image_policy'] == 'none'
            w.preview(session['id'], user_id=user['id'])
        saved = accounts.load_workbench_session(session['id'], user['id'])
        assert '<img' not in saved['typeset_html'] and saved['article'] == article
        assert (w.OUTPUT_DIR / session['id'] / 'preview.html').exists()
        print(json.dumps({'skill':'workbench', 'seconds':round(time.monotonic()-start,1), 'unchanged':True, 'no_images':True}), flush=True)
        if args.diagnose:
            diagnosis = turn('diagnose', f'请诊断公众号“{args.diagnose}”，直接查询真实数据。')
            assert 'report' in diagnosis['artifacts']
        if args.image:
            morning = turn('morning', '现在规划1张花卉早安图，保留2条文案，图片上有早安二字，不要边框，先只出方案。', morning)
            assert len(morning['artifacts']['draft']['cards']) == 1
            morning = turn('morning', '确认当前方案，请生成这1张图片。', morning)
            assert len(morning['artifacts']['draft']['images']) == 1
            print(json.dumps({'image':morning['artifacts']['draft']['images'][0]['url']}), flush=True)
        print('PASS live conversation smoke', flush=True)


if __name__ == '__main__':
    main()
