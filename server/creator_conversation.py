"""Owner-scoped conversational adapters for creator Skills."""
import uuid
import time
import json

from . import accounts, creator_tools, skill_runtime, workbench, diagnosis_service
from .conversation_agent import run_turn


SKILLS = {
    'xiaohongshu': 'xiaohongshu_creator',
    'tie-tu': 'wechat_tie_tu',
    'hit-detector': 'wechat_hit_detector',
    'diagnose': 'wechat_account_analyzer',
    'morning': 'morning_blessing',
}


def new_session(skill, user_id):
    if skill not in SKILLS:
        raise ValueError('不支持的创作工具')
    session = {'id': uuid.uuid4().hex, 'conversation_skill': skill,
               'conversation': [], 'artifacts': {}}
    accounts.save_workbench_session(user_id, session)
    return session


def chat(skill, message, user_id, session_id=None, check_cancelled=lambda: None):
    with accounts.conversation_lock(session_id or uuid.uuid4().hex, user_id):
        return _chat(skill, message, user_id, session_id, check_cancelled)


def _chat(skill, message, user_id, session_id, check_cancelled):
    if skill not in SKILLS:
        raise ValueError('不支持的创作工具')
    if session_id:
        session = accounts.load_workbench_session(session_id, user_id)
        if not session or session.get('conversation_skill') != skill:
            raise KeyError('会话不存在')
    else:
        session = {'id': uuid.uuid4().hex, 'conversation_skill': skill,
                   'conversation': [], 'artifacts': {}}
    references = ('references/official-rules-evidence.md', 'references/platform-rules.md',
                  'references/platform-rules-basic.md') if skill == 'hit-detector' else ()
    instructions, manifest = skill_runtime.context(
        creator_tools.ROOT / 'vendor' / 'skills' / SKILLS[skill], references)
    session['skill_manifest'] = manifest

    def diagnose(state, args):
        if set(args) != {'account_name'} or not isinstance(args['account_name'], str) or not 1 <= len(args['account_name'].strip()) <= 80:
            raise ValueError('需要提供明确的公众号名称')
        from .main import _enrich_report
        result = diagnosis_service.run(args['account_name'], _enrich_report)
        state['artifacts']['report'] = result['report']
        state['parameters'] = args
        return result

    def review(state, args):
        if set(args) - {'title', 'body', 'track'}:
            raise ValueError('未知复核参数')
        parameters = {**{'title': '', 'body': '', 'track': 'auto'},
                      **state.get('parameters', {}), **args}
        if not all(isinstance(v, str) for v in parameters.values()) or not parameters['body'].strip():
            raise ValueError('需要提供文章正文')
        report = creator_tools.detect_article(**parameters)
        state['parameters'] = parameters
        state['artifacts']['report'] = report
        return report

    def rewrite(state, args):
        if args or not state.get('parameters') or not state['artifacts'].get('report'):
            raise ValueError('请先复核文章，再要求改稿')
        article = creator_tools.rewrite_article(state['parameters']['title'],
                    state['parameters']['body'], state['artifacts']['report'])
        state['parameters'].update(title=article['title'], body=article['body'])
        state['artifacts']['article'] = article
        state['artifacts'].pop('report', None)
        return article

    def generate(state, args):
        if 'image_count' not in args and 'image_count' not in state.get('parameters', {}):
            raise ValueError('首次生成必须明确image_count：纯文案或不要图片填0；需要图片填用户要求的数量。请补正参数再调用。')
        if skill == 'xiaohongshu':
            defaults = dict(topic='', account='', audience='', goal='', evidence='',
                            content_type='', image_count=6, requirements='')
            function = creator_tools.xiaohongshu_package
        elif skill == 'morning':
            defaults = dict(topic='早安祝福', image_count=4, copy_count=3, style='',
                            mode='article', columns=1, image_at=1, image_position='after',
                            size='768x1024', requirements='')
            function = creator_tools.morning_draft
        else:
            defaults = dict(industry='', topic='', title='', content_type=None,
                            image_count=4, style='', audience='', portrait_mode='', requirements='')
            function = creator_tools.tie_tu_plan
        if set(args) - set(defaults):
            raise ValueError('创作参数包含未知字段')
        parameters = {**defaults, **state.get('parameters', {}), **args}
        if not isinstance(parameters['topic'], str) or not parameters['topic'].strip():
            raise ValueError('需要先确认创作主题')
        for name, value in parameters.items():
            if name not in {'image_count', 'copy_count', 'columns', 'image_at'} and value is not None and not isinstance(value, str):
                raise ValueError('创作文字参数格式错误')
        count = parameters['image_count']
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 12:
            raise ValueError('图片数量需要在0到12之间')
        call_parameters = dict(parameters)
        call_parameters['requirements'] = parameters.get('requirements', '') + '\n' + skill_runtime.brief(state)
        existing = state['artifacts'].get('draft')
        if existing:
            call_parameters['requirements'] += '\n当前草稿（按要求最小修改，未要求重写的文字保留）：\n' + json.dumps(
                {k: v for k, v in existing.items() if k not in {'images', 'session_id', 'conversation_id'}}, ensure_ascii=False)
        result = function(**call_parameters)
        result['conversation_id'] = state['id']
        state['parameters'] = parameters
        state['artifacts']['draft'] = result
        return result

    def images(state, args):
        if set(args) - {'indices'}:
            raise ValueError('未知生图参数')
        draft = state['artifacts'].get('draft') or {}
        cards = draft.get('cards') or []
        if not cards:
            raise ValueError('当前没有图片计划，纯文案不会生成图片')
        indices = args.get('indices', [card['index'] for card in cards])
        if not isinstance(indices, list) or not indices or len(indices) > 12 or any(type(i) is not int for i in indices):
            raise ValueError('图片序号格式错误')
        by_index = {card['index']: card for card in cards}
        if any(i not in by_index for i in indices):
            raise ValueError('图片序号超出当前计划')
        completed = draft.setdefault('images', [])
        for index in dict.fromkeys(indices):
            check_cancelled()
            if any(image['index'] == index for image in completed):
                continue
            rule = accounts.pricing_rule('POST', '/api/creator-tools/image')
            if not rule:
                raise ValueError('图片计费规则未启用')
            usage = accounts.reserve_points(user_id, rule, 'POST', '/api/creator-tools/image')
            started = time.perf_counter()
            try:
                image = creator_tools.generate_card_image(
                    skill, draft['session_id'], by_index[index], state.get('parameters', {}).get('style', ''),
                    size=state.get('parameters', {}).get('size', '768x1024'))
            except Exception:
                accounts.refund_usage(usage, 502, int((time.perf_counter()-started)*1000))
                raise
            accounts.settle_usage(usage, 200, int((time.perf_counter()-started)*1000))
            completed.append(image)
            # Preserve paid, completed images even if a later image fails.
            accounts.save_workbench_session(user_id, state)
        return {'images': completed, 'count': len(completed)}

    def layout(state, args):
        allowed = {'mode': {'article', 'sticker'}, 'image_position': {'before', 'after'}}
        if set(args) - {'mode', 'columns', 'image_at', 'image_position'} or not state['artifacts'].get('draft'):
            raise ValueError('需要先生成文案，排版仅接受模式与图片位置参数')
        for key, value in args.items():
            if key in allowed and value not in allowed[key]:
                raise ValueError('排版选项错误')
            if key in {'columns', 'image_at'} and (type(value) is not int or not 1 <= value <= (4 if key == 'columns' else 8)):
                raise ValueError('排版数字超出范围')
        state['parameters'].update(args)
        state['artifacts']['draft'].update(args)
        return {'changed': args, 'text_preserved': True, 'images_preserved': True}

    fields = ('topic,account,audience,goal,evidence,content_type,image_count,requirements'
              if skill == 'xiaohongshu' else
              'industry,topic,title,content_type,image_count,style,audience,portrait_mode,requirements')
    tools = {
            'generate_draft': {
                'description': '创建或修改草稿，复用省略参数。首次image_count必填，纯文案为0，允许0到12。允许字段：' + fields,
                'execute': generate,
            },
        }
    if skill == 'hit-detector':
        tools = {
            'review_article': {'description': '复核文章，不改正文。字段 title,body,track 均为文字，省略时复用上次文章。', 'execute': review},
            'rewrite_article': {'description': '仅用户明确要求改稿时执行，基于已有复核结果。参数为空对象。', 'execute': rewrite},
        }
    elif skill == 'diagnose':
        tools = {'diagnose_account': {'description': '查询真实公众号数据，字段account_name。必须来自用户明确指定的账号，不能猜测账号。', 'execute': diagnose}}
    else:
        if skill == 'morning':
            tools['generate_draft']['description'] = '生成早安文案和图片计划。字段 topic,image_count(首次必填，0到8),copy_count(1到8),style,mode(article或sticker),columns(1到4),image_at(1到8),image_position(before或after),size(像素字符串，例如768x1024为3:4，720x1280为9:16；只能用半角x，宽高各256到4096且必须为16的倍数),requirements。未指定尺寸时省略size使用默认768x1024。省略字段保留。'
            tools['change_layout'] = {'description': '只调整现有内容排版，不改文案或图片。字段mode(article/sticker),columns(1到4),image_at(1到8),image_position(before/after)。', 'execute': layout}
        tools['generate_images'] = {'description': '仅用户明确要求生成或确认图片时使用已有计划生图。字段indices可选整数数组，省略时完成全部未生成图片。每张单独扣图片积分；已有图片复用。不要在只要文案或讨论时调用。', 'execute': images}
    with workbench.provider_overrides():
        updated = run_turn(session, message, instructions, workbench._json_text, tools,
                           max_calls=3, check_cancelled=check_cancelled)
    accounts.save_workbench_session(user_id, updated)
    return updated
