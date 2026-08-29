#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号文章发布前编辑质量复核引擎 v2.4 全行业版
==============================================
编辑复核：L1 内容结构评分 / L2 证据与编辑门槛 / L3 上下文合规 / L4 写作风格风险
支持全行业多赛道：自动识别赛道 + 手动指定赛道 + 风格自适应评分

用法:
    python3 detector.py <标题> <正文文件路径> [--fans 粉丝数] [--open-rate 账号基准打开率%] [--track 赛道名]

示例:
    python3 detector.py "退休第2年，老伴开始嫌弃我了" article.md
    python3 detector.py "OpenAI发布GPT-5，AI编程进入新纪元" article.md --track tech
    python3 detector.py "存款利率又降了，普通人该怎么办" article.md --fans 50000 --open-rate 5.2 --track finance

--track 可选值:
    auto(默认) / tech / finance / workplace / health / education /
    relationship / food / beauty / realestate / senior / general

输出:
    终端 Markdown 报告 + 同目录 report.html（苹果级暗色磨砂玻璃可视化，含按优先级改稿建议）
"""

import re
import sys
import json
import argparse
import datetime
import unicodedata
import os
import tempfile

# ============================================================
# 赛道定义（全行业多赛道词库 v2.0）
# ============================================================
# 每个赛道包含: group(群体词) / pain(痛点词) / benefit(利益词) / keyword(识别关键词)
# 自动赛道识别 = 统计关键词命中数，取最高分赛道；不足阈值归 general

TRACKS = {
    "tech": {
        "name": "科技AI",
        "keywords": ["AI", "人工智能", "大模型", "GPT", "ChatGPT", "算法", "芯片", "算力",
                      "开源", "编程", "代码", "机器人", "自动驾驶", "元宇宙", "科技",
                      "半导体", "英伟达", "OpenAI", "应用", "数字人", "SaaS"],
        "group": ["程序员", "开发者", "工程师", "创业者", "极客", "用户", "打工人"],
        "pain": ["效率低", "加班", "失业", "焦虑", "跟不上", "学不会", "淘汰", "卷",
                 "内卷", "转型难", "不会用", "被替代"],
        "benefit": ["涨薪", "加薪", "升职", "副业", "变现", "赚钱", "降本增效", "免费",
                    "效率提升", "省时", "机会", "红利"],
    },
    "finance": {
        "name": "财经投资",
        "keywords": ["股市", "基金", "存款", "利率", "理财", "投资", "房价", "黄金",
                      "美联储", "通胀", "降息", "加息", "债券", "A股", "港股", "美股",
                      "指数", "板块", "金融", "经济", "资产", "财富", "保险"],
        "group": ["股民", "基民", "投资者", "储户", "中年人", "家庭", "上班族", "散户"],
        "pain": ["亏损", "套牢", "缩水", "贬值", "踩雷", "割肉", "焦虑", "不敢买",
                 "追高", "被套", "跑输", "迷茫"],
        "benefit": ["收益", "回报", "盈利", "分红", "增值", "抄底", "止盈", "省钱",
                    "利率", "补贴", "红利", "机会", "配置", "复利"],
    },
    "workplace": {
        "name": "职场成长",
        "keywords": ["职场", "上班", "工作", "跳槽", "裁员", "升职", "加薪", "老板",
                      "同事", "面试", "简历", "加班", "996", "汇报", "晋升", "offer",
                      "打工", "裸辞", "创业", "领导", "绩效", "失业", "副业", "35岁",
                      "离职", "工资", "薪资", "求职", "中年危机", "职场人", "打工人"],
        "group": ["打工人", "职场人", "毕业生", "新人", "中层", "上班族", "员工", "年轻人"],
        "pain": ["内卷", "加班", "焦虑", "被裁", "35岁", "瓶颈", "迷茫", "累",
                 "委屈", "不公平", "被甩锅", "没前途"],
        "benefit": ["升职", "加薪", "跳槽", "涨薪", "offer", "期权", "年终奖", "副业",
                    "技能", "成长", "机会", "自由"],
    },
    "health": {
        "name": "健康养生",
        "keywords": ["健康", "养生", "中医", "睡眠", "减肥", "健身", "饮食", "营养",
                      "血压", "血糖", "癌症", "肿瘤", "体检", "医生", "医院", "锻炼",
                      "瑜伽", "跑步", "维生素", "蛋白质", "免疫力"],
        "group": ["老年人", "中年人", "上班族", "宝妈", "患者", "家属", "年轻人"],
        "pain": ["失眠", "焦虑", "亚健康", "三高", "肥胖", "脱发", "疲劳", "疼痛",
                 "生病", "恶化", "复发", "风险"],
        "benefit": ["改善", "治愈", "缓解", "预防", "恢复", "增强", "降低", "保护",
                    "健康", "长寿", "效果", "方法"],
    },
    "education": {
        "name": "教育育儿",
        "keywords": ["孩子", "教育", "学习", "考试", "高考", "中考", "成绩", "学校",
                      "老师", "家长", "育儿", "辅导", "培训班", "大学", "专业", "就业",
                      "学区房", "作文", "数学", "英语", "阅读"],
        "group": ["家长", "父母", "学生", "考生", "孩子", "宝妈", "老师", "大学生"],
        "pain": ["焦虑", "成绩差", "厌学", "叛逆", "沉迷", "辅导难", "升学难", "竞争",
                 "内卷", "拖后腿", "跟不上", "择校难"],
        "benefit": ["提分", "逆袭", "录取", "保送", "加分", "上岸", "方法", "技巧",
                    "规划", "免费", "资源", "经验"],
    },
    "relationship": {
        "name": "婚恋情感",
        "keywords": ["恋爱", "婚姻", "结婚", "离婚", "分手", "前任", "相亲", "单身",
                      "夫妻", "爱情", "出轨", "彩礼", "婆媳", "对象", "情感", "挽回"],
        "group": ["单身", "情侣", "夫妻", "女生", "男生", "女人", "男人", "相亲对象"],
        "pain": ["分手", "冷战", "背叛", "出轨", "吵架", "失望", "孤独", "焦虑",
                 "被嫌弃", "没安全感", "消耗", "心累"],
        "benefit": ["挽回", "复合", "脱单", "幸福", "甜蜜", "理解", "方法", "技巧",
                    "稳定", "安全感", "改善"],
    },
    "food": {
        "name": "美食生活",
        "keywords": ["美食", "菜谱", "做法", "厨房", "餐厅", "小吃", "火锅", "烘焙",
                      "家常菜", "探店", "食材", "料理", "外卖", "烧烤", "甜品", "早餐"],
        "group": ["吃货", "家庭主妇", "宝妈", "美食爱好者", "打工人", "学生"],
        "pain": ["不会做", "翻车", "失败", "费时", "踩雷", "难吃", "油腻", "贵",
                 "麻烦", "没人吃"],
        "benefit": ["简单", "快手", "零失败", "省钱", "好吃", "教程", "秘诀", "配方",
                    "营养", "下饭", "技巧"],
    },
    "beauty": {
        "name": "美妆时尚",
        "keywords": ["护肤", "化妆", "美妆", "口红", "面膜", "防晒", "穿搭", "时尚",
                      "发型", "医美", "抗老", "美白", "祛痘", "粉底", "眼影", "香水"],
        "group": ["女生", "姐妹", "宝妈", "学生党", "上班族", "油皮", "干皮", "敏感肌"],
        "pain": ["踩雷", "卡粉", "脱妆", "长痘", "过敏", "暗沉", "显老", "粗大",
                 "出油", "起皮", "无效"],
        "benefit": ["平价", "好用", "效果", "持妆", "遮瑕", "修护", "提亮", "抗老",
                    "种草", "回购", "测评"],
    },
    "realestate": {
        "name": "房产楼市",
        "keywords": ["房价", "买房", "卖房", "楼盘", "房贷", "首付", "租金", "租房",
                      "物业", "学区", "户型", "拆迁", "二手房", "新盘", "房地产", "楼市"],
        "group": ["购房者", "刚需", "业主", "租客", "年轻人", "家庭", "改善型", "投资者"],
        "pain": ["买不起", "还贷难", "烂尾", "维权", "亏了", "降价", "观望", "焦虑",
                 "被坑", "踩雷", "卖不动", "亏本"],
        "benefit": ["降价", "补贴", "利率下调", "首付降低", "政策", "利好", "省钱",
                    "捡漏", "升值", "稳赚", "机会"],
    },
    "senior": {
        "name": "中老年情感",
        "keywords": ["退休", "养老金", "老伴", "养老", "中老年", "老年人", "60岁", "70岁",
                      "黄昏恋", "孙辈", "孙子", "孙女", "医保", "补贴", "长寿", "广场舞",
                      "老同事", "儿女", "老年生活", "退休金"],
        "group": ["退休", "老伴", "中老年", "爸妈", "父母", "母亲", "父亲", "大爷", "大妈",
                  "60岁", "50岁", "70岁", "老年", "养老", "黄昏恋", "子女", "孙辈", "孙子", "孙女",
                  "结婚", "夫妻", "婚姻", "恋爱", "老公", "老婆", "孩子", "家庭", "中年",
                  "已婚", "未婚", "离婚", "家", "女儿", "儿子"],
        "pain": ["越来越少", "没话说", "变淡", "陌生", "沉默", "冷战", "吵架", "渐行渐远",
                 "没意思", "不如从前", "不爱", "变了", "隔阂", "疏远", "累", "孤单"],
        "benefit": ["养老金", "退休金", "补贴", "医保", "涨", "领钱", "补发", "报销", "省钱",
                    "待遇", "福利", "新政", "调整", "通知", "2026", "新规"],
    },
    "general": {
        "name": "通用情感",
        "keywords": [],
        "group": ["大家", "每个人", "普通人", "我们", "身边人", "朋友", "家人", "自己"],
        "pain": ["焦虑", "迷茫", "累", "孤独", "压力", "失望", "无助", "内耗",
                 "纠结", "emo", "心累", "委屈"],
        "benefit": ["方法", "技巧", "经验", "建议", "改变", "成长", "突破", "机会",
                    "收获", "启发", "价值"],
    },
}

# 通用评分词库（所有赛道共用）
EMOTION_CONFLICT = ["嫌弃", "离婚", "藏", "哭", "吵", "逼", "求", "骗", "离开", "背叛",
                    "心寒", "委屈", "寒心", "分房", "争", "闹", "打", "扔", "砸", "跪",
                    "走了", "住院", "手术", "摔", "失踪", "查", "失业", "裁员", "亏损",
                    "分手", "出轨", "崩溃", "确诊", "翻车", "踩雷"]
SUSPENSE_WORDS = ["竟然", "悄悄", "为什么", "终于", "没想到", "藏着", "背后的", "真相",
                  "秘密", "后悔", "一夜之间", "突然", "到底", "究竟是"]
AI_OPENING = ["在当今", "随着", "众所周知", "今天我们来聊聊", "在如今", "随着社会",
              "在现在这个", "首先", "综上所述", "总而言之", "值得注意的是"]
AI_WORDS = ["赋能", "格局", "认知升级", "干货满满", "满满的干货", "优质内容", "深度好文",
            "助力", "打造", "闭环", "底层逻辑", "思维模型", "抓手", "颗粒度", "组合拳",
            "拥抱变化", "破圈", "红利", "赛道", "精细化运营", "此外", "值得注意的是",
            "不可否认", "毋庸置疑", "由此可见"]
EMPTY_MODIFIERS = ["仿佛", "宛如", "仿佛置身", "仿佛让人", "令人心旷神怡", "岁月静好",
                   "微风拂面", "流光溢彩", "熠熠生辉", "如诗如画"]
HEALTH_RISK = ["偏方", "秘方", "治百病", "根治", "包治", "排毒", "抗癌", "降三高立竿见影",
               "食疗治", "药到病除", "养生神方"]
CLICKBAIT = ["震惊", "速看", "删前速看", "惊天", "吓人", "千万别", "转疯了", "必转",
             "不转不是", "马上删", "疯了", "重磅", "紧急通知"]
SUPERSTITION = ["属相", "风水", "算命", "大师", "开运", "转运", "犯太岁", "推背图",
                "前世", "因果报应", "附体"]
INDUCE = ["转发后领取", "分享截图", "关注后领取", "扫码关注", "不转不是", "转发一生平安",
          "点赞抽奖", "集赞", "邀请好友", "助力"]
TRIPLE_PATTERN = re.compile(r"[^，。；\n]*[，、][^，。；\n]*[，、][^，。；\n]*")
# 分节/小标题正则（供结构、视觉维度复用）
SUBHEADING_RE = re.compile(
    r"^(?:\*{0,2})?(#{1,3}\s|[①②③④⑤⑥⑦⑧⑨⑩]|一、|二、|三、|第[一二三四五六七八九十\d]+[、.。，]|[0-9]+(?:[、.。，]|\s+)|【|（[0-9]+）|\([0-9]+\))")
# 广告绝对化表述必须结合语境判断。这里仅保留具有明确宣传承诺语义的组合，
# 不把“退休第一年”“第一次”等普通叙述误判为广告违规。
BANNED_ABSOLUTE = ["国家级", "万能", "100%有效", "绝对有效", "全网最低", "史上最低",
                   "世界级品质", "销量第一", "行业第一", "零风险", "永久有效"]
BANNED_SUPERLATIVE_RE = re.compile(
    r"最(?:佳|好用|有效|专业|安全|便宜|低价|权威|值得买|值得推荐|先进|强大)"
)
BANNED_MEDICAL = ["治疗", "治愈", "抗癌", "消炎", "杀菌", "瘦身", "燃脂", "排毒", "药到病除", "降三高", "治百病"]
BANNED_INDUCE = ["私信", "加微信", "免费领", "扫码", "限时", "抢购", "秒杀", "下单", "领券", "优惠券", "抽奖"]
BANNED_FALSE = ["保证有效", "百分百有效", "无效退款", "稳赚不赔", "一定有效", " guaranteed"]
URL_RE = re.compile(r"https?://|www\.", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|0\d{2,3}[- ]?\d{7,8})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LONG_ID_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")
CONTACT_TERMS = ["加微信", "微信号", "vx", "v信", "私信我", "私信领取", "扫码", "二维码", "联系我", "主页联系", "评论区留"]
COMMERCE_TERMS = ["下单", "购买", "报价", "咨询", "接单", "招聘", "招人", "课程", "服务", "优惠", "限时", "秒杀", "返利", "佣金", "代理"]
QUALIFICATION_TERMS = ["资质", "许可证", "备案", "授权", "官方入口", "营业执照", "医师", "执业", "牌照", "编号"]
FINANCE_TERMS = ["股票", "基金", "理财", "投资", "收益", "回报", "本金", "贷款", "保险", "币", "荐股"]
PROMISE_TERMS = ["保证", "稳赚", "必赚", "躺赚", "翻倍", "无风险", "包过", "包成功", "一定能", "立刻见效"]
PRIVACY_TERMS = ["身份证", "手机号", "住址", "车牌", "订单号", "快递单", "聊天记录", "定位", "银行卡"]
PLATFORM_SURFACE_TERMS = ["闲鱼", "淘宝", "拼多多", "抖音", "小红书", "快手", "微博", "知乎", "群聊"]
# 绝对化对比词（反AI量化用）：模板腔信号
ABSOLUTE_CLAIM = ["一定", "必须", "绝对", "毫无疑问", "毋庸置疑", "所有人都", "每个人都应该",
                  "无一例外", "百分之百", "100%", "必然", "统统", "全都"]
LEVELS = {"S": (85, "结构信号较完整"), "A": (70, "结构信号基本完整"),
          "B": (55, "存在多项结构短板"), "C": (0, "结构信号明显不足")}

# L1 八维权重（合计 100）：在 v2.1 六维基础上新增「结构节奏」「视觉呈现」
DIM_FULL = {
    "title": 18, "opening": 16, "content": 18, "structure": 14,
    "topic": 12, "readability": 7, "visual": 8, "interaction": 7,
}
DIM_NAMES = {
    "title": "标题钩子力", "opening": "开头钩子力", "content": "内容价值度",
    "structure": "结构节奏", "topic": "选题势能", "readability": "阅读体验",
    "visual": "视觉呈现", "interaction": "互动引导",
}

# 赛道识别阈值：关键词命中 >= 3 才算命中该赛道
TRACK_MATCH_THRESHOLD = 3


def normalize_text(text):
    """Normalize user text without changing its visible meaning.

    NFKC handles full-width punctuation/digits and the compact form lets the
    checker catch spacing variants such as ``转 发 后 领 取``.  Matching is
    still advisory: every hit is returned for human review, never as proof of
    a platform decision.
    """
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u200b", "").replace("\ufeff", "")
    return value


def compact_text(text):
    return re.sub(r"\s+", "", normalize_text(text))


NEGATION_WORDS = ("不", "无", "没有", "未", "并非", "不是", "不能", "无法",
                  "尚无", "尚未", "避免", "禁止", "反对", "否认")


def _is_negated(text, start, end, window=24):
    context = text[max(0, start - window):end + 8]
    return any(w in context[:window + len(w)] for w in NEGATION_WORDS)


def find_hits(text, terms, *, ignore_negated=True):
    """Return unique term hits after normalization and light negation review."""
    value = compact_text(text)
    found = []
    for term in terms:
        needle = compact_text(term)
        if not needle:
            continue
        start = value.find(needle)
        if start < 0:
            continue
        if ignore_negated and _is_negated(value, start, start + len(needle)):
            continue
        found.append(term)
    return found


def find_superlative_hits(text):
    value = compact_text(text)
    return list(dict.fromkeys(m.group(0) for m in BANNED_SUPERLATIVE_RE.finditer(value)))


def find_absolute_claim_hits(text):
    """Find promotional absolute claims without matching ordinary ordinals."""
    value = compact_text(text)
    hits = find_hits(value, BANNED_ABSOLUTE)
    hits.extend(find_superlative_hits(value))
    contextual_patterns = (
        r"(?:销量|排名|行业|全国|全网|市场|品牌|效果|性价比).{0,4}第一",
        r"第一.{0,4}(?:品牌|产品|选择|效果|销量|排名)",
        r"唯一.{0,4}(?:选择|方法|答案|品牌|产品|机会)",
        r"永久.{0,4}(?:有效|保用|免费|不变)",
    )
    for pattern in contextual_patterns:
        for match in re.finditer(pattern, value):
            if not _is_negated(value, match.start(), match.end()):
                hits.append(match.group(0))
    return list(dict.fromkeys(hits))


def _has_source(text):
    value = normalize_text(text)
    return bool(re.search(
        r"https?://|(?:来源|出处|数据来自)[:：]?\s*.{2,30}|"
        r"据.{2,20}(?:报道|公告|通知|统计|数据显示|发布|通报)|"
        r"(?:国务院|国家网信办|市场监管总局|国家卫健委|中国政府网).{0,16}(?:发布|公告|通知|通报)|"
        r"《[^》]{2,40}》",
        value,
    ))


def _has_time_anchor(text):
    value = normalize_text(text)
    return bool(re.search(r"截至|生效|发布日期|发布于|更新于|\d{4}年|\d{1,2}月\d{1,2}日|今天|昨日|本周|今年", value))


def _title_body_overlap(title, body):
    title_value = compact_text(title)
    body_value = compact_text(body)
    bigrams = {title_value[i:i + 2] for i in range(max(0, len(title_value) - 1))
               if re.search(r"[\u4e00-\u9fff]", title_value[i:i + 2])}
    if not bigrams:
        return 1.0
    return sum(1 for x in bigrams if x in body_value) / len(bigrams)


TITLE_NUMBER_RE = re.compile(
    r"(?<!第)\d+(?:\.\d+)?(?:岁|元|块钱?|分钟|小时|天|年|个|座|条|种|样|件|%|折|倍)"
)
AUTHORITY_TERMS = ("联合国", "国务院", "卫健委", "市场监管总局", "研究表明",
                   "报告显示", "数据显示", "统计显示", "专家表示", "权威机构")
VOLATILE_TERMS = ("免票", "票价", "价格", "人均", "高铁", "车程", "分钟", "小时", "元", "块钱",
                  "补贴", "利率", "医保", "养老金", "酒店", "民宿")
FIRST_PERSON_EVIDENCE_RE = re.compile(
    r"(?:我|我们|我家|我朋友|我同事|我老姐妹|我身边).{0,18}(?:亲历|经历|去过|住过|吃过|花了|发现|中过|踩过|采访|见过)"
)


def _sentence_units(text):
    units = []
    for paragraph in normalize_text(text).splitlines():
        for sentence in re.split(r"(?<=[。！？!?；;])", paragraph):
            value = sentence.strip()
            if value:
                units.append(value)
    return units


def _numeric_claim_supported(token, body):
    if compact_text(token) in compact_text(body):
        return True
    number_match = re.match(r"(\d+)(.*)", token)
    if number_match:
        number = int(number_match.group(1))
        digits = "零一二三四五六七八九"
        chinese_number = None
        if 0 <= number <= 9:
            chinese_number = digits[number]
        elif 10 <= number <= 99:
            tens, ones = divmod(number, 10)
            chinese_number = ("" if tens == 1 else digits[tens]) + "十" + (digits[ones] if ones else "")
        if chinese_number and compact_text(chinese_number + number_match.group(2)) in compact_text(body):
            return True
    match = re.fullmatch(r"(\d+)(个|座|条|种|样|件)", token)
    if not match:
        return False
    promised = int(match.group(1))
    list_items = sum(1 for line in body.splitlines() if SUBHEADING_RE.match(line.strip()))
    return list_items >= promised


def build_source_ledger(title, body, track, style):
    """Build a claim ledger; source markers are not treated as verified facts."""
    text = normalize_text(title + "\n" + body)
    ledger = []
    seen = set()
    for sentence in _sentence_units(text):
        claim_type = None
        severity = "review"
        action = "核对事实，并在对应句附近补充来源、日期或适用条件。"
        if any(term in sentence for term in AUTHORITY_TERMS) or re.search(
                r"官方.{0,8}(?:发布|通报|公告|认证|评定|数据显示)", sentence):
            claim_type = "authority"
            severity = "block"
            action = "补充可核验的机构、报告或公告名称和日期；无法核实时删除权威背书。"
        elif any(term in sentence for term in ("政策", "新规", "法规", "通知", "规定")) or re.search(
                r"《[^》]{2,30}办法》", sentence):
            claim_type = "policy"
            severity = "block"
            action = "补充现行文件名称、发布机构、生效日期和来源链接。"
        elif re.search(r"(?:最早的|首个|首款|首创).{1,18}", sentence):
            claim_type = "historical_first"
            severity = "block"
            action = "这是历史首创/最早定义性断言；补充权威史料，无法证明时改成不带首创结论的描述。"
        elif track in {"health", "finance"} and (
                TITLE_NUMBER_RE.search(sentence) or any(term in sentence for term in PROMISE_TERMS + BANNED_MEDICAL)):
            claim_type = "professional"
            severity = "block"
            action = "补充专业来源、适用范围和必要限定，不能用个人经验替代证据。"
        elif TITLE_NUMBER_RE.search(sentence) and any(term in sentence for term in VOLATILE_TERMS):
            claim_type = "volatile"
            action = "核对价格、交通、优惠或开放信息，并注明查询日期；发布前再次确认。"
        elif FIRST_PERSON_EVIDENCE_RE.search(sentence):
            claim_type = "experience"
            severity = "confirm"
            action = "由作者确认确为本人或已获授权的真实经历；不能为了增强代入感虚构。"
        if not claim_type:
            continue
        key = (claim_type, compact_text(sentence)[:80])
        if key in seen:
            continue
        seen.add(key)
        if claim_type == "experience":
            status = "needs_author_confirmation"
        elif _has_source(sentence):
            status = "source_marker_present_unverified"
            severity = "confirm"
            action = "已发现来源提示，但仍需打开原始来源核对原文、日期和适用范围。"
        else:
            status = "missing_source"
        ledger.append({
            "claim": sentence[:140],
            "claim_type": claim_type,
            "status": status,
            "severity": severity,
            "action": action,
        })
        if len(ledger) >= 10:
            break
    return ledger


def _title_promise_issues(title, body):
    issues = []
    unsupported_numbers = [token for token in TITLE_NUMBER_RE.findall(title) if not _numeric_claim_supported(token, body)]
    if unsupported_numbers:
        issues.append({
            "type": "title_claim",
            "severity": "block",
            "title": "标题数字承诺未被正文承接",
            "detail": "正文没有明确解释：" + "、".join(unsupported_numbers) + "。补齐依据或删除标题承诺。",
        })
    if re.search(r"第[一二三四五六七八九十\d]+个.{0,12}(?:后悔|没想到|才知道|中招)", title):
        suspense_terms = [w for w in ("后悔", "没想到", "才知道", "中招") if w in title]
        if suspense_terms and not any(w in body for w in suspense_terms):
            issues.append({
                "type": "title_claim",
                "severity": "block",
                "title": "标题悬念在正文中没有兑现",
                "detail": "标题使用“" + "、".join(suspense_terms) + "”制造缺口，但正文没有对应事实或经历。",
            })
    return issues


def evidence_review(title, body, track, style):
    """Surface source, freshness and title/body risks without pretending to fact-check."""
    text = normalize_text(title + "\n" + body)
    issues = []
    source_sensitive = track in {"finance", "health", "realestate", "senior"} or style == "news"
    policy_terms = ("政策", "新规", "通知", "公告", "养老金", "医保", "补贴", "利率", "法规", "规定")
    if source_sensitive and (any(w in text for w in policy_terms) or style == "news") and not _has_source(text):
        issues.append({"type": "source", "severity": "block",
                       "title": "缺少可核验来源",
                       "detail": "资讯、健康、财经或政策类内容建议补充来源链接/机构/报告名称。"})
    if any(w in text for w in policy_terms) and not _has_time_anchor(text):
        issues.append({"type": "freshness", "severity": "review",
                       "title": "缺少时效锚点",
                       "detail": "政策、利率、医保、养老金等内容应注明截至日期、生效时间或版本。"})
    if len(compact_text(title)) >= 8 and _title_body_overlap(title, body) < 0.22:
        issues.append({"type": "alignment", "severity": "review",
                       "title": "标题正文关联偏弱",
                       "detail": "标题中的核心对象或承诺在正文中未得到足够展开，需人工核对是否标题党。"})
    issues.extend(_title_promise_issues(title, body))
    ledger = build_source_ledger(title, body, track, style)
    missing_authority = [item for item in ledger if item["claim_type"] in
                         {"authority", "policy", "professional", "historical_first"}
                         and item["status"] == "missing_source"]
    if missing_authority and not any(item["type"] == "source" for item in issues):
        issues.append({"type": "claim_source", "severity": "block",
                       "title": "关键事实缺少逐项来源",
                       "detail": missing_authority[0]["claim"] + " ｜ " + missing_authority[0]["action"]})
    volatile = [item for item in ledger if item["claim_type"] == "volatile" and item["status"] == "missing_source"]
    if volatile:
        issues.append({"type": "claim_freshness", "severity": "review",
                       "title": "价格或交通信息需要发布前复核",
                       "detail": volatile[0]["claim"] + " ｜ " + volatile[0]["action"]})
    experience = [item for item in ledger if item["claim_type"] == "experience"]
    if experience:
        issues.append({"type": "experience", "severity": "confirm",
                       "title": "第一人称经历需要作者确认",
                       "detail": experience[0]["claim"] + " ｜ " + experience[0]["action"]})
    return issues


def _first_context(text, terms, window=30):
    """Return the first compact snippet around any matched term."""
    for term in terms:
        idx = text.lower().find(str(term).lower())
        if idx >= 0:
            start = max(0, idx - window)
            end = min(len(text), idx + len(str(term)) + window)
            return text[start:end].replace("\n", " ").strip(), term
    return "", ""


def _first_regex_context(text, regex, label, window=30):
    m = regex.search(text)
    if not m:
        return "", ""
    start = max(0, m.start() - window)
    end = min(len(text), m.end() + window)
    return text[start:end].replace("\n", " ").strip(), label


SCAN_CONVERSION_RE = re.compile(
    r"(?:扫码|扫描二维码).{0,14}(?:关注|领取|咨询|购买|报名|下单|加群|联系|添加|优惠|课程|服务)|"
    r"(?:关注|领取|咨询|购买|报名|下单|加群|联系|添加).{0,14}(?:扫码|二维码)"
)


def _scan_conversion_context(text, window=30):
    """Return scan-code context only when it forms a conversion action."""
    value = normalize_text(text)
    match = SCAN_CONVERSION_RE.search(value)
    if not match:
        return "", ""
    start = max(0, match.start() - window)
    end = min(len(value), match.end() + window)
    return value[start:end].replace("\n", " ").strip(), "扫码/二维码"


def _risk_item(surface, quote, signal, mechanism, action, severity="review", keep=""):
    return {
        "surface": surface,
        "quote": quote,
        "signal": signal,
        "mechanism": mechanism,
        "action": action,
        "severity": severity,
        "keep": keep,
    }


def content_risk_review(title, body, track):
    """Split platform-machine review signals from substantive content risks."""
    text = normalize_text(title + "\n" + body)
    compact = compact_text(text).lower()
    machine, substantive, confirm = [], [], []

    contact_quote, contact_hit = _first_context(text, [term for term in CONTACT_TERMS if term != "扫码"])
    if not contact_hit:
        contact_quote, contact_hit = _scan_conversion_context(text)
    commerce_quote, commerce_hit = _first_context(text, COMMERCE_TERMS)
    platform_quote, platform_hit = _first_context(text, PLATFORM_SURFACE_TERMS)
    promise_quote, promise_hit = _first_context(text, PROMISE_TERMS + BANNED_FALSE)
    medical_quote, medical_hit = _first_context(text, BANNED_MEDICAL + HEALTH_RISK)
    finance_quote, finance_hit = _first_context(text, FINANCE_TERMS)
    privacy_quote, privacy_hit = _first_context(text, PRIVACY_TERMS)
    url_quote, url_hit = _first_regex_context(text, URL_RE, "外链")
    phone_quote, phone_hit = _first_regex_context(text, PHONE_RE, "电话")
    email_quote, email_hit = _first_regex_context(text, EMAIL_RE, "邮箱")
    long_id_quote, long_id_hit = _first_regex_context(text, LONG_ID_RE, "长数字编号")

    if url_hit:
        machine.append(_risk_item("正文", url_quote, "外链/跳转", "平台机器审核可能把完整外链当作导流或广告信号。",
                                  "保留必要来源名称；若必须放链接，改成引用来源名+搜索路径。", "review"))
    if contact_hit or phone_hit or email_hit or long_id_hit:
        quote = contact_quote or phone_quote or email_quote or long_id_quote
        hit = contact_hit or phone_hit or email_hit or long_id_hit
        severity = "warn" if commerce_hit else "review"
        machine.append(_risk_item("正文", quote, f"联系方式信号：{hit}", "联系方式、二维码、长数字编号容易触发导流/营销机器审核。",
                                  "删除非必要联系方式；确需保留时改为平台内官方入口或后台自动回复。", severity))
    if platform_hit:
        machine.append(_risk_item("正文", platform_quote, f"平台/圈层词：{platform_hit}",
                                  "平台名本身不等于违规，但机器审核可能结合交易、导流、争议词一起放大风险。",
                                  "只保留叙事必需的平台名，避免和联系方式、价格、下单动作连在同一句。", "review"))
    if commerce_hit and contact_hit:
        substantive.append(_risk_item("正文", commerce_quote or contact_quote, "交易动作 + 导流入口",
                                      "这不是单纯敏感词，而是可能被理解为站外交易/引流闭环。",
                                      "拆掉交易闭环：删联系方式、删下单引导，改成内容价值或官方合规入口。", "warn",
                                      "可以保留真实经验和判断，不必把观点磨平。"))

    medical_signal = medical_hit or track == "health"
    if medical_signal and promise_hit and not any(w in compact for w in [compact_text(x).lower() for x in QUALIFICATION_TERMS]):
        substantive.append(_risk_item("标题/正文", medical_quote or promise_quote, "健康/疗效承诺缺少资质边界",
                                      "医疗健康内容的确定性效果、治愈式表达需要资质、适用边界和来源支撑。",
                                      "改成个人体验/科普边界，删除治愈、保证、立刻见效；补来源或就医提示。", "warn"))
    elif medical_signal and medical_hit:
        confirm.append(_risk_item("正文", medical_quote, "健康词", "健康词出现后需要确认是否有诊疗、功效、适用人群边界。",
                                  "人工核对来源、资质和免责声明，必要时改为生活经验表达。"))

    if finance_hit and (promise_hit or any(w in compact for w in [compact_text(x).lower() for x in ["荐股", "收益翻倍", "稳赚不赔"]])):
        substantive.append(_risk_item("标题/正文", finance_quote or promise_quote, "财经投资承诺",
                                      "投资收益承诺或荐股倾向属于实质风险，不只是词表命中。",
                                      "删收益保证和操作指令，补风险提示、时间范围和非投资建议边界。", "warn"))
    elif finance_hit and track == "finance":
        confirm.append(_risk_item("正文", finance_quote, "财经信息", "财经内容需要核对时间、来源和风险提示。",
                                  "补数据来源、截至日期和非投资建议声明。"))

    if privacy_hit:
        substantive.append(_risk_item("正文", privacy_quote, "隐私/个人信息",
                                      "身份证、手机号、订单、定位等属于真实个人信息暴露风险。",
                                      "打码或改成类别描述，删除可识别个人的完整信息。", "warn"))
    if commerce_hit and promise_hit:
        substantive.append(_risk_item("标题/正文", promise_quote or commerce_quote, "商业承诺/夸大效果",
                                      "购买、服务、课程等商业语境里出现保证、稳赚、包成功，会从营销合规变成事实承诺风险。",
                                      "保留卖点，但改成可验证事实、适用条件和案例边界。", "warn"))

    if commerce_hit and not any(w in compact for w in [compact_text(x).lower() for x in QUALIFICATION_TERMS]):
        confirm.append(_risk_item("正文", commerce_quote, "商业/服务信息", "涉及服务、课程、报价、优惠时，需要确认是否具备资质、价格、售后边界。",
                                  "发布前核对主体、价格、售后、资质和广告标识。"))

    return {
        "machine": machine[:5],
        "substantive": substantive[:5],
        "confirm": confirm[:5],
        "boundary": "本层只基于标题和正文做编辑复核；图片、封面、评论区、账号资料和视频字幕需另行检查。",
    }


def detect_track(title, body, forced=None):
    """自动识别赛道；forced 指定时直接使用"""
    if forced and forced in TRACKS:
        return forced
    text = compact_text(title + body)
    scores = {}
    for tid, t in TRACKS.items():
        if tid == "general":
            continue
        hits = [w for w in t["keywords"] if compact_text(w).lower() in text.lower()] if t["keywords"] else []
        scores[tid] = len(hits)
    best = max(scores, key=scores.get)
    if scores[best] < TRACK_MATCH_THRESHOLD:
        return "general"
    return best


# ============================================================
# 文章风格识别（兼容各种体裁：避免用干货文尺子量情绪文/故事文）
# ------------------------------------------------------------
# 风格(tone) 与 赛道(track) 正交：赛道决定"写给谁"，风格决定"怎么写"。
# 八维评分按风格适配，保证不同体裁在各自该有的标准下被公平评价。
# ============================================================
STYLES = {
    "practical": "干货方法论",
    "emotion":   "情绪随笔",
    "opinion":   "观点评论",
    "narrative": "故事叙事",
    "news":      "资讯热点",
}

# 各风格的"短板改写提示"（用于 build_suggestions 的通用兜底文案，避免给情绪文建议加小标题）
STYLE_FIX_HINT = {
    "practical": "建议按干货体裁补足：分节小标题 + 可操作步骤/清单 + 明确利益点",
    "emotion":   "建议按情绪随笔补足：强化具体场景/细节、情感递进与结尾共鸣句（无需硬塞小标题/清单）",
    "narrative": "建议按故事叙事补足：强化情节推进、人物与转折、场景画面感",
    "opinion":   "建议按观点评论补足：亮明立场 + 论据/案例支撑 + 多角度论证",
    "news":      "建议按资讯热点补足：清晰信源 + 关键数据 + 完整要素(5W1H)",
}


# 各维度的短板改写提示：按维度给出针对性建议，并结合风格微调（避免给所有维度同一句笼统话）
def dim_fix(key, style):
    if key == "interaction":
        if style in ("emotion", "narrative"):
            return "结尾加一句共鸣式提问（如「你最近，又在急着什么呢？」）或软收束句，自然引发评论与分享"
        return "结尾提出与正文直接相关、读者有真实经验可回答的问题；不要用利益交换诱导关注或分享"
    if key == "content":
        if style in ("emotion", "narrative"):
            return "强化具体场景细节与情感递进（反思/转折），用真实对话增强代入，无需硬塞小标题"
        if style == "practical":
            return "加2-3个分节小标题 + 可操作步骤/清单 + 明确利益点，提升干货密度"
        if style == "opinion":
            return "亮明立场 + 论据/案例支撑 + 多角度论证，让观点更立体"
        return "提升信息密度与关键数据，补全要素"
    base = {
        "title": "先写清对象、问题和读者收益；数字或悬念只有在正文能兑现时才保留",
        "opening": "前100字直接抛冲突场景或扎心设问，缩短铺垫，前两句就给钩子",
        "topic": "锚定一个具体赛道人群，补足其痛点词/利益点，或给选题一个新鲜视角",
        "readability": "拆短句（均≤25字）、压段落（≤120字）、减少英文缩写，提升手机阅读友好度",
        "structure": "检查起承转合：开头抛核心问题、中间有转折/递进、结尾补收束或升华金句",
        "visual": "补充分节小标题/加粗关键词；配图必须帮助理解正文，而不是只作装饰",
    }
    return base.get(key, "建议重写该维度")


def detect_style(title, body):
    """识别文章写作风格，返回 (style_id, style_name, signal_scores)。
    用多组信号词/结构打分，取最高；信号都很弱时回退到 emotion（个人化表达）。"""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    text = title + "\n" + body
    subheading = [l for l in lines if SUBHEADING_RE.match(l)]
    has_sub = len(subheading) >= 2
    sc = {"practical": 0, "emotion": 0, "opinion": 0, "narrative": 0, "news": 0}

    # 干货方法论：编号本身不是教程，必须同时出现方法/步骤/建议等行动信号。
    method_hits = sum(1 for w in
        ["方法", "步骤", "清单", "如何", "怎么", "技巧", "攻略", "模板", "教程", "实操",
          "建议", "三步", "两步", "干货", "指南", "全攻略", "一篇搞定", "要点"]
        if w in text)
    if has_sub:
        sc["practical"] += 4 if method_hits else 1
    sc["practical"] += min(4, method_hits)
    sc["practical"] += 1 if re.search(r"\d+[.、]|第一|第二|首先|其次|最后", text) else 0
    if re.search(r"第一|第二|第三|1\.|2\.|3\.", text):
        sc["practical"] += 2

    # 情绪随笔：第一人称 + 情绪/反思词
    fp = len(re.findall(r"我(们)?|咱|自己", text))
    sc["emotion"] += min(4, fp / 6.0)
    sc["emotion"] += min(5, sum(1 for w in
        EMOTION_CONFLICT + SUSPENSE_WORDS +
        ["焦虑", "迷茫", "孤独", "累", "内耗", "心累", "委屈", "难受", "怕", "落后", "着急", "慌"]
        if w in text) / 3.0)
    sc["emotion"] += 2 if re.search(r"突然|那一刻|后来|想起|回头看|想了想|其实我|说真的|我才发现", text) else 0

    # 观点评论：论证连接词 + 立场
    sc["opinion"] += min(5, sum(1 for w in
        ["但是", "其实", "我认为", "本质上", "问题在于", "真相是", "别再", "说白了",
         "换句话说", "然而", "事实上", "我倒觉得", "关键是", "反之"]
        if w in text))
    sc["opinion"] += 2 if re.search(r"不是.*而是|与其.*不如|难道|我们真的", text) else 0

    # 故事叙事：情节词 + 对话 + 人物（收紧：去掉"同事/他/她"等易误判词，需对话或情节支撑）
    plot = sum(1 for w in
        ["那天", "后来", "然后", "有一天", "记得", "小时候", "去年", "上周", "有一次",
         "话说", "事情是这样的", "凌晨", "下班", "醒来", "睡了一个多小时"]
        if w in text)
    sc["narrative"] += min(4, plot / 2.0)
    if "“" in text or "”" in text or '"' in text:
        sc["narrative"] += 2
    chars = sum(1 for w in ["父亲", "母亲", "女儿", "儿子", "朋友", "爷爷", "奶奶", "老伴"] if w in text)
    sc["narrative"] += min(2, chars)
    nostalgia = sum(1 for w in
        ["老物件", "那会儿", "小时候", "当年", "年代", "记忆", "曾年轻", "过去", "妈妈", "爸爸", "全村"]
        if w in text)
    sc["narrative"] += min(6, nostalgia)

    # 资讯热点：时间锚点 + 信源
    sc["news"] += min(4, sum(1 for w in
        ["今天", "昨日", "昨天", "刚刚", "近日", "消息称", "据报道", "据", "宣布", "发布", "通报", "数据显示", "统计"]
        if w in text) / 2.0)
    sc["news"] += 2 if re.search(r"\d{1,2}月\d{1,2}日|\d{4}年", text) else 0

    best = max(sc, key=sc.get)
    if sc[best] <= 1:
        best = "emotion"
    return best, STYLES[best], sc


# ============================================================
# L1-1 标题钩子力 (25)
# ============================================================
def score_title(title, track, body=""):
    b = []
    s = 0
    number_claims = TITLE_NUMBER_RE.findall(title)
    supported_numbers = [token for token in number_claims if _numeric_claim_supported(token, body)]
    if number_claims and len(supported_numbers) == len(number_claims):
        s += 3; b.append(("标题数字承诺均在正文中得到承接", 3))
    elif number_claims:
        b.append(("标题含未被正文承接的数字承诺", 0))
    t = TRACKS[track]
    if any(w in title for w in t["group"]):
        s += 4; b.append((f"明确目标读者（{t['name']}）", 4))
    if any(w in title for w in EMOTION_CONFLICT):
        s += 3; b.append(("呈现明确冲突或反差", 3))
    elif any(w in title for w in SUSPENSE_WORDS):
        s += 1; b.append(("含悬念词；只作轻度编辑信号", 1))
    if any(w in title for w in t["pain"]):
        s += 3; b.append(("指出读者问题", 3))
    if any(w in title for w in t["benefit"]):
        s += 2; b.append(("说明读者收益", 2))
    overlap = _title_body_overlap(title, body) if body else 0
    if overlap >= 0.35:
        s += 3; b.append(("标题核心信息在正文中充分展开", 3))
    elif overlap >= 0.22:
        s += 1; b.append(("标题正文有基本关联", 1))
    else:
        b.append(("标题正文关联偏弱，需核对承诺是否兑现", 0))
    n = len(title)
    if 15 <= n <= 25:
        s += 3; b.append((f"字数{n}，手机端信息密度适中", 3))
    elif 10 <= n <= 32:
        s += 1; b.append((f"字数{n}，长度可用", 1))
    else:
        b.append((f"字数{n}，需检查是否过短或过长", 0))
    s = min(s, 18)
    return s, b
# ============================================================
# L1-2 开头钩子力 (20)
# ============================================================
def score_opening(title, body, track):
    b = []
    s = 0
    op = body[:300]
    ai_hit = sum(1 for w in AI_OPENING if w in op)
    if ai_hit:
        s -= 4
        b.append((f"开头含AI腔（{ai_hit}处：如'在当今/随着'），-4", -4))
    if any(w in op for w in EMOTION_CONFLICT):
        s += 6
        b.append(("开头即抛情绪冲突/戏剧场面", 6))
    if re.search(r"[？?]|\?|为什么|怎么|难道|竟然|悄悄|背后", op[:140]):
        s += 5
        b.append(("开头用设问/悬念制造缺口", 5))
    t = TRACKS[track]
    if any(w in op for w in t["pain"]):
        s += 4
        b.append((f"开头戳中赛道痛点（{t['name']}）", 4))
    if re.search(r"[他她我你].{0,10}(说|发现|没想到|看着|回忆|去年|那天|其实)", op):
        s += 3
        b.append(("开头有具体人物/故事钩子", 3))
    if any(w in op for w in t["benefit"]) and len(op) < 200:
        s += 2
        b.append(("开头前置利益点", 2))
    s = max(0, min(s, 16))
    return s, b


# ============================================================
# L1-3 内容价值与结构 (20) —— 通用基础分 + 风格加成（混合模型）
# ============================================================
def score_content(title, body, track, style):
    b = []
    s = 0
    t = TRACKS[track]
    lines = [l for l in body.splitlines() if l.strip()]
    sub = [l for l in lines if SUBHEADING_RE.match(l)]
    # --- 通用基础分：所有体裁都认可的好内容信号（避免某体裁被一刀切）---
    if len(sub) >= 2:
        s += 4
        b.append((f"结构清晰，含{len(sub)}个分节/小标题", 4))
    elif len(lines) >= 6:
        s += 2
        b.append(("段落分明，层次可读", 2))
    if re.search(r"[他她我你].{0,30}(说|告诉|经历|那年|一次|记得|那天|其实|看着|想起|发现|陪|聊|吃|玩|睡|醒|坐|站|走|哭|笑)", body):
        s += 4
        b.append(("含真实案例/故事佐证", 4))
    # 方法论/清单仅对非情绪·叙事体裁加分（情绪文不应因"清单/步骤"得分）
    if style in ("practical", "opinion", "news") and re.search(
            r"\d+[.、]|第一|第二|步骤|三步|方法|技巧|攻略|模板|清单|如何|怎样|实操", body):
        s += 3
        b.append(("给出可操作方法论/清单", 3))
    emo = sum(1 for w in EMOTION_CONFLICT + SUSPENSE_WORDS +
              ["焦虑", "迷茫", "孤独", "累", "内耗", "心累", "委屈", "难受", "怕", "落后", "着急", "慌"]
              if w in body)
    if emo >= 3:
        s += 3
        b.append((f"情绪价值/共鸣点充足（{emo}处）", 3))
    # --- 风格专属加成（叠加在通用分之上，不剥夺通用分）---
    if style in ("emotion", "narrative"):
        if re.search(r"我.{0,40}(坐|车|窗|凌晨|房间|街|灯|风|雨|看着|想起|发现|觉得|陪|吃|玩|睡|醒|走|站|哭|笑)|我们.{0,40}(都|一起|其实|现在|是不是)", body):
            s += 5
            b.append(("有具体场景/细节，画面感强", 5))
        if re.search(r"突然|那一刻|后来发现|回头看|想了想|我才发现|意识到|说真的|其实我|明白|懂了", body):
            s += 4
            b.append(("有反思/顿悟转折，情感递进", 4))
        if "“" in body or "”" in body:
            s += 3
            b.append(("含真实对话，代入感强", 3))
    elif style == "opinion":
        if re.search(r"但是|其实|我认为|本质上|问题在于|真相是|说白了|我的看法|我倒觉得|关键在于|反之", body):
            s += 4
            b.append(("论点鲜明，立场明确", 4))
        if re.search(r"不是.*而是|与其.*不如|反过来|换个角度", body):
            s += 2
            b.append(("多角度论证，立体", 2))
    elif style == "news":
        if re.search(r"据|报道|消息|宣布|发布|通报|数据显示|统计|调查", body):
            s += 3
            b.append(("信息源清晰", 3))
    elif style == "practical":
        benefit_hit = sum(1 for w in t["benefit"] if w in body)
        if benefit_hit >= 2:
            s += 2
            b.append((f"利益点明确（{benefit_hit}处）", 2))
    s = min(s, 18)
    return s, b


# ============================================================
# L1-4 选题赛道匹配与人群共鸣 (15) —— 风格自适应
# ============================================================
def score_topic(title, body, track, style):
    b = []
    s = 0
    t = TRACKS[track]
    text = title + body
    kw = sum(1 for w in t["keywords"] if w.lower() in text.lower()) if t["keywords"] else 0
    grp = sum(1 for w in t["group"] if w in text)
    pain = sum(1 for w in t["pain"] if w in text)
    # 赛道贴合度
    if kw >= 3:
        s += 6
        b.append((f"选题高度贴合{t['name']}赛道（关键词{kw}处）", 6))
    elif kw >= 1:
        s += 3
        b.append(("选题与赛道相关", 3))
    else:
        b.append(("选题与赛道关联弱（跨赛道泛话题）", 0))
    # 人群指向
    if grp >= 3:
        s += 5
        b.append((f"精准命中目标人群（{grp}处群体词）", 5))
    elif grp >= 1:
        s += 2
        b.append(("有人群指向", 2))
    # 痛点触达
    if pain >= 2:
        s += 4
        b.append((f"痛点覆盖充分（{pain}处）", 4))
    elif pain >= 1:
        s += 2
        b.append(("有痛点触达", 2))
    # 风格专属加成：情绪/故事文的选题势能来自"普遍共鸣 + 新鲜视角"，而非赛道关键词
    if style in ("emotion", "narrative"):
        if grp >= 1 or pain >= 1:
            s += 1
            b.append(("共鸣型选题，击中普遍情绪/处境", 1))
        if re.search(r"突然|那一刻|后来发现|意识到|我才发现|说真的|其实我们|换个角度", text):
            s += 2
            b.append(("有新鲜视角/反思转折，选题不陈旧", 2))
    s = min(s, 12)
    return s, b


# ============================================================
# 平均句长
# ============================================================
def avg_sentence_len(text):
    segs = re.split(r"[。！？!?；;\n]", text)
    segs = [s for s in segs if s.strip()]
    if not segs:
        return 0
    return sum(len(s) for s in segs) / len(segs)


# ============================================================
# L1-5 阅读体验 (10)（原"中老年可读性"升级为通用阅读体验）
# ============================================================
def score_readability(body, track):
    b = []
    s = 0
    lines = [l for l in body.splitlines() if l.strip()]
    avg_line = sum(len(l) for l in lines) / len(lines) if lines else 0
    if avg_line <= 120:
        s += 4
        b.append((f"段落精炼（均{avg_line:.0f}字），手机阅读友好", 4))
    elif avg_line <= 200:
        s += 2
        b.append(("段落偏长但可接受", 2))
    else:
        b.append((f"段落过长（均{avg_line:.0f}字），建议拆短", 0))
    al = avg_sentence_len(body)
    if 12 <= al <= 35:
        s += 3
        b.append((f"平均句长{al:.0f}字，节奏舒适", 3))
    elif al > 0:
        s += 1
        b.append((f"平均句长{al:.0f}字", 1))
    if re.search(r"[？?]|“|”|「|」|你说|我说|他问|其实|说真的|讲真", body):
        s += 3
        b.append(("有对话感/口语化，不枯燥", 3))
    s = min(s, 7)
    return s, b


# ============================================================
# L1-6 互动引导 (10) —— 风格自适应
# ============================================================
def score_interaction(body, style):
    b = []
    s = 0
    tail = body[-400:]

    if style in ("emotion", "narrative"):
        # 情绪/故事文：软提问/共鸣收束即可（不强制硬 CTA）；提问可出现在全文任意位置
        if re.search(r"你(最近|现在|呢|有没有|是否|怎么看|遇到过|也)|我们(都|是不是|也)|吗\s*[？?。.!！]?|呢\s*[？?。.!！]?", body):
            s += 5
            b.append(("有共鸣式提问/软互动，契合情绪文体裁", 5))
        elif re.search(r"其实|说真的|只想|愿|希望|相信|记住|一起|慢慢", tail):
            s += 3
            b.append(("结尾有共鸣收束句，易引发分享", 3))
        if any(w in body for w in ["争议", "分歧", "你怎么看", "有人说", "其实我", "反而", "有没有同感"]):
            s += 2
            b.append(("内容带讨论空间", 2))
        if re.search(r"点赞|在看|收藏|关注|订阅|转发", body):
            s += 3
            b.append(("有点赞/在看/关注等行动召唤", 3))

    elif style == "practical":
        if re.search(r"你怎么看|评论区|说说|留言|聊聊你的|你遇到|在评论|下方|欢迎|分享|转发", tail):
            s += 5
            b.append(("结尾有评论引导/互动钩子", 5))
        if re.search(r"点赞|在看|收藏|关注|订阅|转发", body):
            s += 3
            b.append(("有点赞/在看/关注等行动召唤", 3))
        if any(w in body for w in ["争议", "分歧", "你怎么看", "有人说", "其实我", "反而"]):
            s += 2
            b.append(("内容带讨论空间", 2))

    elif style == "opinion":
        if re.search(r"你怎么看|你怎么认为|同意吗|你站哪边|评论区|说说你的|聊聊", tail):
            s += 5
            b.append(("抛争议点引发站队讨论", 5))
        elif re.search(r"我认为|我倒觉得|我的看法|说白了|本质上", body):
            s += 2
            b.append(("有明确立场，易引发表态", 2))
        if re.search(r"点赞|在看|收藏|关注|订阅|转发", body):
            s += 3
            b.append(("有行动召唤", 3))

    else:  # news / 默认
        if re.search(r"你怎么看|评论区|说说|留言|聊聊|欢迎讨论|下方留言", tail):
            s += 4
            b.append(("结尾有评论引导", 4))
        if re.search(r"点赞|在看|收藏|关注|订阅|转发", body):
            s += 3
            b.append(("有行动召唤", 3))
        if s == 0:
            b.append(("信息价值自带分享属性，但缺互动钩子", 0))

    s = min(s, 7)
    return s, b


# ============================================================
# L1-7 结构节奏 (14) —— 新增维度（逻辑起承转合/节奏紧凑/结尾设计）
# 风格自适应：情绪/故事文允许松散叙事，靠转折与收束句评估，而非硬卡小标题
# ============================================================
def score_structure(title, body, style):
    b = []
    s = 0
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    sub = [l for l in lines if SUBHEADING_RE.match(l)]
    cap_sec = [l for l in lines if re.fullmatch(r"[A-Z]{3,}", l)]  # 用户式英文分节标签
    # --- 逻辑结构 ---
    if len(sub) >= 2 or len(cap_sec) >= 2:
        s += 5
        b.append(("结构清晰，有明确分节/小标题", 5))
    elif 6 <= len(lines):
        s += 2
        b.append(("段落有层次，起承转合可读", 2))
    # --- 开头抛核心问题/观点 ---
    if re.search(r"问题|其实|我发现|我意识到|到底是什么|为什么|背后", body[:400]):
        s += 2
        b.append(("开头抛出核心问题/观点，主线清晰", 2))
    # --- 结尾收束/升华（金句或软收束）---
    tail = body[-300:]
    last_line = lines[-1] if lines else ""
    closing = re.search(r"总之|最后|所以|一句话|记住|其实|说真的|愿|希望|一起|慢慢|相信|别忘了|别让|坐稳|稳住|路", tail)
    if closing or len(last_line) <= 25:
        s += 4
        b.append(("结尾有收束/升华句或金句，给读者余味", 4))
    # --- 节奏紧凑度 ---
    avg_line = sum(len(l) for l in lines) / len(lines) if lines else 0
    if avg_line <= 120:
        s += 3
        b.append((f"节奏紧凑（段均{avg_line:.0f}字），不易走神", 3))
    # --- 风格专属：情绪/故事文看转折递进 ---
    if style in ("emotion", "narrative"):
        if re.search(r"突然|那一刻|后来|转折|意识到|我才发现|说真的|反而", body):
            s += 2
            b.append(("情感有转折/递进，叙事不扁平", 2))
    s = min(s, 14)
    return s, b


# ============================================================
# L1-8 视觉呈现 (8) —— 新增维度（小标题/加粗/配图/留白）
# 纯文本长文给提示；图文/排版稿可拿满
# ============================================================
def score_visual(body, style):
    b = []
    s = 0
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    sub = [l for l in lines if SUBHEADING_RE.match(l)]
    cap_sec = [l for l in lines if re.fullmatch(r"[A-Z]{3,}", l)]
    # --- 小标题/分节 ---
    if len(sub) >= 2 or len(cap_sec) >= 2:
        s += 5
        b.append(("有分节小标题，扫读结构清晰", 5))
    elif len(sub) >= 1 or len(cap_sec) >= 1:
        s += 2
        b.append(("有局部分节，结构尚可", 2))
    # --- 加粗强调 ---
    bold = len(re.findall(r"\*\*[^*]+\*\*|__[^_]+__", body))
    if bold >= 2:
        s += 2
        b.append(("用了加粗强调关键信息", 2))
    # --- 配图/视觉元素 ---
    if re.search(r"!\[|图片|配图|附图|图：|img|http[s]?://[^\s]+\.(?:png|jpg|jpeg|gif|webp)", body):
        s += 1
        b.append(("含配图/视觉元素，提升停留", 1))
    s = min(s, 8)
    return s, b


# ============================================================
# L3 合规词表与上下文复核
# ============================================================
def compliance_check(title, body, track):
    issues = []
    text = normalize_text(title + "\n" + body)
    checks = [
        ("政治时政敏感", "block", ["反政府", "游行示威", "疆独", "藏独", "台独", "港独", "抗议游行", "颠覆"]),
        ("色情低俗", "block", ["约炮", "色情", "成人内容", "擦边", "裸聊", "性爱"]),
        ("暴力血腥", "block", ["杀人", "血腥", "砍人", "尸体", "恐怖袭击", "虐杀"]),
        ("虚假诈骗", "block", ["稳赚不赔", "保本高息", "快速致富", "0元购", "中奖通知", "免费送手机", "跟着买必赚", "稳赚不亏"]),
        ("诱导分享/关注", "block", INDUCE),
        ("标题党", "warn", CLICKBAIT),
        ("迷信伪科学", "warn", SUPERSTITION),
        ("医疗功效承诺", "warn", HEALTH_RISK),
    ]
    for name, sev, words in checks:
        hit = find_hits(text, words)
        if hit:
            issues.append({"line": name, "severity": sev, "hits": hit[:5]})
    if track == "finance":
        if "投资建议" in text and "不构成投资建议" not in text and "仅供参考" not in text:
            issues.append({"line": "金融误导风险(红线5.5)", "severity": "warn",
                           "hits": ["未标注'不构成投资建议'"],
                           "fix": "文末加：以上内容仅供参考，不构成投资建议。"})
    if track == "health":
        med = find_hits(text, ["治愈", "根治", "包治", "药到病除", "抗癌", "降三高立竿见影"])
        if med:
            issues.append({"line": "医疗绝对化表述", "severity": "warn",
                           "hits": med[:5],
                           "fix": "避免'治愈/根治'等绝对化疗效承诺。"})
    # 绝对化广告用语需要结合宣传语境判断；普通序数不命中。
    plat = find_absolute_claim_hits(text)
    if plat:
        issues.append({"line": "绝对化宣传表述（需结合语境）", "severity": "warn",
                       "hits": plat[:6],
                       "fix": "核对是否属于广告宣传、是否有事实依据及限定条件；普通叙事序数不按违规处理。"})
    med2 = find_hits(text, BANNED_MEDICAL)
    if med2:
        issues.append({"line": "医疗功效表述（需核验资质与证据）", "severity": "warn",
                       "hits": med2[:5],
                       "fix": "区分中性医疗叙述与疗效承诺；涉及治疗结论时核验资质、来源和适用范围。"})
    ind = [hit for hit in find_hits(text, BANNED_INDUCE) if hit != "扫码"]
    if _scan_conversion_context(text)[1]:
        ind.append("扫码/二维码")
    if ind:
        issues.append({"line": "营销/导流表述（需结合语境）", "severity": "warn",
                       "hits": ind[:5],
                       "fix": "核对是否形成强制关注、利益交换或站外交易；普通事实叙述不按违规处理。"})
    fal = find_hits(text, BANNED_FALSE)
    if fal:
        issues.append({"line": "虚假承诺词", "severity": "block",
                       "hits": fal[:5],
                       "fix": "删除'保证有效/稳赚不赔/无效退款'等承诺性表述。"})
    return issues


# ============================================================
# L4 写作风格风险检测（不是 AI 来源检测）
# ============================================================
def ai_smell_check(title, body):
    """量化写作风格风险：返回 (penalty 0-12, risk 0-100, findings)。
    综合：黑话密度、空泛修饰、开头AI腔、排比三连、绝对化对比、句式均匀度；
    口语化/对话感作为反向信号冲抵。"""
    import statistics
    findings = []
    penalty = 0
    text = title + "\n" + body
    # 1. 黑话/套话密度（按千字）
    ai_w = sum(1 for w in AI_WORDS if w in text)
    if ai_w:
        d = ai_w / max(1.0, len(text) / 1000.0)
        if d >= 2:
            penalty += 4
            findings.append(f"互联网黑话密度偏高（{ai_w}处/千字），建议改成具体表达")
        elif d >= 0.8:
            penalty += 2
            findings.append(f"含黑话{ai_w}处，建议换成大白话")
    # 2. 空泛修饰
    empty = sum(1 for w in EMPTY_MODIFIERS if w in text)
    if empty:
        penalty += 2
        findings.append(f"空泛修饰词×{empty}（岁月静好/流光溢彩…）")
    # 3. 开头AI腔
    ai_open = sum(1 for w in AI_OPENING if w in body[:200])
    if ai_open:
        penalty += 3
        findings.append(f"开头AI腔×{ai_open}（如'在当今/随着'）")
    # 4. 排比三连
    trips = len(TRIPLE_PATTERN.findall(body))
    if trips >= 8:
        penalty += 2
        findings.append(f"排比三连句式过多×{trips}，机械感重")
    # 5. 绝对化对比词（模板腔）
    ab = sum(1 for w in ABSOLUTE_CLAIM if w in text)
    if ab >= 2:
        penalty += 2
        findings.append(f"绝对化表述×{ab}（一定/必须/所有人都…），像模板")
    # 6. 句式均匀度（标准差过低→AI节奏）
    segs = [s for s in re.split(r"[。！？!?]", body) if len(s.strip()) > 4]
    if len(segs) >= 6:
        lens = [len(s) for s in segs]
        avg = sum(lens) / len(lens)
        sd = statistics.pstdev(lens) if len(lens) > 1 else 0
        cv = sd / avg if avg else 0
        if cv < 0.25:
            penalty += 2
            findings.append("句式长短高度均匀，建议加入真实节奏变化")
    # 7. 口语化/对话感（反向冲抵）
    if re.search(r"[？?]|“|”|你说|我说|其实|说真的|讲真|跟你说|咱|爷们|哥们", text):
        penalty = max(0, penalty - 2)
        findings.append("✅ 自然表达加分：有口语化/对话感（风险抵消 -2）")
    risk = min(100, round(penalty / 12.0 * 100))
    return min(penalty, 12), risk, findings


# ============================================================
# L2 账号数据基线（不做文章阅读量预测）
# ============================================================
def predict_reads(fans, open_rate, score, track, genes=None):
    """Expose only arithmetic account baselines from user-provided data.

    Text rules cannot turn a generic track rate into a reliable article forecast.
    The compatibility keys stay in the payload, but invented scenario numbers are
    deliberately removed.
    """
    baseline_reads = None
    if fans and fans > 0 and open_rate is not None and open_rate >= 0:
        baseline_reads = int(fans * open_rate / 100.0)
        data_state = "account_baseline"
        confidence = "insufficient_for_forecast"
        confidence_note = "仅按用户提供的粉丝数×历史平均打开率计算账号基线，不是本文阅读量预测。"
    else:
        data_state = "missing_history"
        confidence = "not_estimated"
        confidence_note = "缺少账号真实历史数据，不输出阅读量、打开率或流量池数字。"
    return {
        "data_state": data_state,
        "provided_fans": fans,
        "provided_open_rate": open_rate,
        "baseline_reads": baseline_reads,
        "base_open_rate": round(open_rate, 2) if open_rate is not None else None,
        "eff_open_rate": None,
        "predict": None,
        "range": [None, None],
        "confidence": confidence,
        "confidence_note": confidence_note,
        "scenario_reads": [],
        "completion_rate": None,
        "share_rate": None,
        "pool_level": None,
        "pool_prob": None,
    }


# ============================================================
# L2+ 四个传播要素（情绪/实用/身份/社交货币）
# ------------------------------------------------------------
# 用"四基因"透镜重评选题势能与内容价值：命中越多基因，越具备自发传播力。
# 每基因 0-100，输出画像供报告展示，并给选题维度做轻度加成。
# ============================================================
GENE_KEYS = {"emotion": "情绪共鸣", "utility": "实用价值", "identity": "身份认同", "social": "社交货币"}


def viral_genes(title, body, style):
    text = title + "\n" + body
    # 情绪共鸣：冲突/悬念/焦虑类词密度
    emo = sum(1 for w in EMOTION_CONFLICT + SUSPENSE_WORDS +
              ["焦虑", "迷茫", "孤独", "累", "内耗", "心累", "委屈", "难受", "怕", "落后", "着急", "慌"]
              if w in text)
    g_emotion = min(100, emo * 9)
    # 实用价值：方法论/清单/数据/建议（需 ≥2 处方法信号或含数据，避免单字误判）
    method_hits = len(re.findall(
        r"\d+[.、]|第一|第二|步骤|三步|方法|技巧|攻略|模板|清单|如何|怎样|实操", body))
    util = 0
    if method_hits >= 2 or re.search(r"\d|%|倍", text):
        util += 45
    if re.search(r"\d|%|倍", text):
        util += 20
    if re.search(r"建议|应该|可以|试试|记住|做这|别再|一定要", body):
        util += 20
    g_utility = min(100, util)
    # 身份认同："我也是/我们"群体归属（按出现频次计，重复越多归属感越强）
    grp = sum(text.count(w) for w in ["我们", "大家", "普通人", "我也是", "一样", "身边", "每个",
                                      "打工人", "宝妈", "中年", "年轻人", "老年人"])
    g_identity = min(100, grp * 11)
    # 社交货币：让人想转发/显得有见识
    soc = 0
    if re.search(r"转|分享|收藏|发给|朋友圈|看懂|真相|认知|格局|没想到|居然|破防|扎心", text):
        soc += 50
    if g_emotion >= 40 or re.search(r"真实|清醒|通透|看完|句句|说到心", text):
        soc += 30
    g_social = min(100, soc)
    return {"emotion": g_emotion, "utility": g_utility,
            "identity": g_identity, "social": g_social}


# ============================================================
# L2+ 受众共鸣模拟（人格画像启发式模型）
# ------------------------------------------------------------
# 说明：本层为"启发式模拟"，非真实用户行为数据。按「年龄+行业身份+阅读性格」
# 三维定义读者原型，用文章已被 L1 测出的特征（句长/数据/方法论/情绪/口语/互动）
# 去匹配每个原型的偏好权重，输出文本适配指数，不推断用户行为。
# 用途：看清"这篇打动了谁、谁无感、该往哪改去撬动某类人"。
# ============================================================
PERSONAS = {
    "young_student": {
        "name": "青年学生·尝鲜社交型", "age": "18-25", "identity": "学生/年轻群体",
        "style": "猎奇社交，爱热点和社交货币，怕长文干货",
        "affinity": {"tech": 1.3, "food": 1.1, "beauty": 1.2, "relationship": 1.1,
                     "general": 1.0, "education": 0.9},
        "pref": {"short": 0.85, "data": 0.30, "method": 0.35, "emotion": 0.70, "oral": 0.80},
    },
    "young_worker": {
        "name": "青年职场·理性实用型", "age": "26-35", "identity": "职场打工人",
        "style": "重数据时效和方法论，关心涨薪副业，能忍长文",
        "affinity": {"tech": 1.3, "workplace": 1.3, "finance": 1.1,
                     "realestate": 0.9, "general": 0.9},
        "pref": {"short": 0.60, "data": 0.85, "method": 0.85, "emotion": 0.40, "oral": 0.50},
    },
    "mid_parent": {
        "name": "宝妈家庭·实用焦虑型", "age": "30-45", "identity": "宝妈/家庭",
        "style": "重育儿健康干货和安全感，吃真实经验",
        "affinity": {"education": 1.3, "health": 1.2, "food": 1.1, "beauty": 1.0,
                     "relationship": 0.9, "senior": 0.7},
        "pref": {"short": 0.70, "data": 0.50, "method": 0.70, "emotion": 0.60, "oral": 0.70},
    },
    "mid_manager": {
        "name": "企业主·效率功利型", "age": "36-50", "identity": "管理层/企业主",
        "style": "重利益方法和结论，没空看水货，嫌情绪化",
        "affinity": {"finance": 1.3, "workplace": 1.1, "realestate": 1.2,
                     "tech": 1.0, "general": 0.7},
        "pref": {"short": 0.50, "data": 0.90, "method": 0.90, "emotion": 0.30, "oral": 0.30},
    },
    "silver": {
        "name": "银发退休·养生情感型", "age": "50+", "identity": "退休/中老年",
        "style": "重健康政策和情感，怕长句英文，爱口语故事",
        "affinity": {"senior": 1.4, "health": 1.3, "food": 0.9,
                     "general": 0.9, "relationship": 0.8},
        "pref": {"short": 0.95, "data": 0.40, "method": 0.50, "emotion": 0.85, "oral": 0.90},
    },
    "general_feel": {
        "name": "大众·情绪共鸣型", "age": "全年龄", "identity": "普通读者",
        "style": "吃情绪冲突和故事，容易转发共情文",
        "affinity": {"relationship": 1.2, "general": 1.2, "senior": 1.0,
                     "health": 0.9, "workplace": 0.9},
        "pref": {"short": 0.60, "data": 0.30, "method": 0.40, "emotion": 0.95, "oral": 0.80},
    },
    "knowledge_seeker": {
        "name": "知识型·深度阅读型", "age": "全年龄", "identity": "爱好者/深度读者",
        "style": "重数据案例和深度，能忍长文，少互动",
        "affinity": {"tech": 1.2, "finance": 1.1, "health": 1.1,
                     "education": 1.1, "workplace": 1.0},
        "pref": {"short": 0.30, "data": 0.90, "method": 0.85, "emotion": 0.40, "oral": 0.40},
    },
}


def extract_features(title, body, track, interaction_score):
    """把文章转成 0-1 特征向量，供原型匹配复用（不重复算 L1 已得的量）"""
    al = avg_sentence_len(body)
    f_short = max(0.0, min(1.0, 1 - al / 45.0))
    f_data = 1.0 if re.search(r"\d|%|倍|第[一二三四五六七八九十\d]+年|\d+岁|亿元|万", title + body) else 0.30
    f_method = 1.0 if re.search(r"\d+[.、]|第一|第二|步骤|三步|方法|技巧|攻略|模板|清单|如何|怎样", body) else 0.35
    emo = sum(1 for w in EMOTION_CONFLICT + SUSPENSE_WORDS if w in body)
    density = emo / max(1.0, len(body) / 1000.0)
    f_emotion = max(0.20, min(1.0, 0.20 + min(density / 8.0, 1.0) * 0.80))
    f_oral = 1.0 if re.search(r"[？?]|“|”|你说|我说|他问|其实|说真的|讲真|跟你说", body) else 0.35
    f_interaction = max(0.0, min(1.0, interaction_score / 10.0))
    return {"short": f_short, "data": f_data, "method": f_method,
            "emotion": f_emotion, "oral": f_oral, "interaction": f_interaction}


def simulate_audience(title, body, track, interaction_score):
    """Return an editorial persona fit index, never behavior probabilities."""
    feats = extract_features(title, body, track, interaction_score)
    out = []
    for pid, p in PERSONAS.items():
        aff = p["affinity"].get(track, 0.60)
        # 特征贴合度：原型偏好目标值 与 文章实际值的接近度（1=完美匹配）
        fit = 0.0
        for k in ("short", "data", "method", "emotion", "oral"):
            fit += 1 - abs(p["pref"][k] - feats[k])
        fit /= 5.0
        affinity = min(1.0, aff / 1.4)
        match_index = round((fit * 0.75 + affinity * 0.25) * 100)
        gaps = [(k, p["pref"][k] - feats[k]) for k in ("short", "data", "method", "emotion", "oral") if p["pref"][k] - feats[k] > 0.15]
        gaps.sort(key=lambda x: x[1], reverse=True)
        weak = gaps[0][0] if gaps else None
        out.append({
            "id": pid, "name": p["name"], "age": p["age"], "identity": p["identity"],
            "style": p["style"], "open": None, "read": None, "interact": None,
            "resonance": match_index, "match_index": match_index, "fit": round(fit * 100),
            "weak": weak,
        })


    out.sort(key=lambda x: x["resonance"], reverse=True)
    return out


# 原型最薄弱特征 -> 改稿杠杆（用于撬动建议）
FEATURE_TIP = {
    "short": "把长句拆短、段落压到120字内，手机阅读更友好",
    "data": "补充具体数字/数据/对比，增强可信度",
    "method": "加入可操作的方法论/清单/步骤，提升干货感",
    "emotion": "加强情绪冲突与故事共鸣，戳中情感点",
    "oral": "增加对话感与口语化表达，减少书面腔",
}


def build_editorial_gate(scores, compliance, evidence, content_risk):
    """Make release readiness depend on blockers, not on a compensating score."""
    blockers = []
    revisions = []
    confirmations = []
    for item in compliance:
        target = blockers if item.get("severity") == "block" else revisions
        target.append(item["line"])
    for item in evidence:
        if item.get("severity") == "block":
            blockers.append(item["title"])
        elif item.get("severity") == "confirm":
            confirmations.append(item["title"])
        else:
            revisions.append(item["title"])
    for item in content_risk.get("substantive", []):
        target = blockers if item.get("severity") == "block" else revisions
        target.append(item["signal"])
    for key, full in DIM_FULL.items():
        if scores[key] / full < 0.5:
            revisions.append(DIM_NAMES[key] + "偏低")
    blockers = list(dict.fromkeys(blockers))
    revisions = list(dict.fromkeys(revisions))
    confirmations = list(dict.fromkeys(confirmations))
    if blockers:
        status = "hold"
        label = "暂缓发布"
        summary = "存在不能被总分抵消的证据或内容风险，先处理 P0 项。"
    elif revisions:
        status = "revise"
        label = "修改后复核"
        summary = "没有发布阻断项，但仍有明确短板需要修改。"
    else:
        status = "human_review"
        label = "可进入人工终审"
        summary = "规则层未发现明确阻断项；仍需人工核对事实、表达和账号适配。"
    return {
        "status": status,
        "label": label,
        "summary": summary,
        "blockers": blockers,
        "revisions": revisions,
        "confirmations": confirmations,
    }


# ============================================================
# 主检测流程
# ============================================================
def detect(title, body, fans=None, open_rate=None, track=None):
    title = normalize_text(title).strip()
    body = normalize_text(body)
    track = detect_track(title, body, track)
    style_id, style_name, style_scores = detect_style(title, body)
    st, bt = score_title(title, track, body)
    so, bo = score_opening(title, body, track)
    sc, bc = score_content(title, body, track, style_id)
    sst, bst = score_structure(title, body, style_id)
    stp, btp = score_topic(title, body, track, style_id)
    srd, brd = score_readability(body, track)
    svi, bvi = score_visual(body, style_id)
    sin, bin_ = score_interaction(body, style_id)
    # 四个传播要素（命中只作轻度结构信号）
    genes = viral_genes(title, body, style_id)
    gene_max = max(genes.values())
    if gene_max >= 60:
        stp = min(DIM_FULL["topic"], stp + 2)
        btp.append(("命中传播要素（情绪/实用/身份/社交货币）", 2))
    raw = st + so + sc + sst + stp + srd + svi + sin
    penalty, ai_risk, ai_find = ai_smell_check(title, body)
    total = max(0, min(100, raw - penalty))
    level = "C"
    for k in ["S", "A", "B", "C"]:
        if total >= LEVELS[k][0]:
            level = k
            break
    issues = compliance_check(title, body, track)
    pred = predict_reads(fans, open_rate, total, track, genes)
    audience = simulate_audience(title, body, track, sin)
    evidence = evidence_review(title, body, track, style_id)
    source_ledger = build_source_ledger(title, body, track, style_id)
    content_risk = content_risk_review(title, body, track)
    score_payload = {
        "title": st, "opening": so, "content": sc, "structure": sst,
        "topic": stp, "readability": srd, "visual": svi, "interaction": sin,
    }
    editorial_gate = build_editorial_gate(score_payload, issues, evidence, content_risk)
    if len(body.strip()) < 300:
        score_confidence = "low"
    elif len(body.strip()) < 800:
        score_confidence = "medium"
    else:
        score_confidence = "baseline"
    return {
        "title": title,
        "track_id": track,
        "track_name": TRACKS[track]["name"],
        "style_id": style_id,
        "style_name": style_name,
        "style_scores": style_scores,
        "scores": {
            "title": st, "opening": so, "content": sc, "structure": sst,
            "topic": stp, "readability": srd, "visual": svi, "interaction": sin,
            "raw": raw, "ai_penalty": penalty, "total": total,
        },
        "breakdowns": {
            "title": bt, "opening": bo, "content": bc, "structure": bst,
            "topic": btp, "readability": brd, "visual": bvi, "interaction": bin_,
        },
        "level": level,
        "level_desc": LEVELS[level][1],
        "editorial_gate": editorial_gate,
        "compliance": issues,
        "content_risk": content_risk,
        "evidence": evidence,
        "source_ledger": source_ledger,
        "score_confidence": score_confidence,
        "ai_smell": {"penalty": penalty, "risk": ai_risk, "findings": ai_find},
        "genes": genes,
        "predict": pred,
        "audience": audience,
    }


# ============================================================
# 改稿建议生成（按优先级 P0/P1/P2）
# ============================================================
def build_suggestions(r):
    """汇总可执行的改进意见，按 P0(必改) > P1(建议改) > P2(优化) 排序"""
    full = DIM_FULL
    names = DIM_NAMES
    sugg = []
    # 1. 合规红线
    for it in r["compliance"]:
        pr = "P0" if it["severity"] == "block" else "P1"
        detail = "命中：" + "、".join(it["hits"])
        if it.get("fix"):
            detail += " ｜ " + it["fix"]
        sugg.append({"pri": pr, "title": it["line"], "detail": detail})
    content_risk = r.get("content_risk", {})
    for it in content_risk.get("substantive", []):
        pr = "P0" if it.get("severity") == "block" else "P1"
        quote = f"片段：{it['quote']} ｜ " if it.get("quote") else ""
        sugg.append({"pri": pr, "title": "发布风险：" + it["signal"],
                     "detail": quote + it["mechanism"] + " ｜ 最小修改：" + it["action"]})
    for it in content_risk.get("machine", [])[:2]:
        quote = f"片段：{it['quote']} ｜ " if it.get("quote") else ""
        sugg.append({"pri": "P1", "title": "机器审核信号：" + it["signal"],
                     "detail": quote + it["mechanism"] + " ｜ 最小修改：" + it["action"]})
    for it in content_risk.get("confirm", [])[:2]:
        quote = f"片段：{it['quote']} ｜ " if it.get("quote") else ""
        sugg.append({"pri": "P2", "title": "发布前确认：" + it["signal"],
                     "detail": quote + it["mechanism"] + " ｜ 核对：" + it["action"]})
    for it in r.get("evidence", []):
        pr = "P0" if it.get("severity") == "block" else "P1"
        sugg.append({"pri": pr, "title": it["title"], "detail": it["detail"]})
    # 2. 八维短板
    for key, f in full.items():
        v = r["scores"][key]
        ratio = v / f
        if ratio < 0.5:
            pr, tag = "P1", "明显偏低"
        elif ratio < 0.75:
            pr, tag = "P2", "有提升空间"
        else:
            continue
        # 视觉呈现对情绪/故事文体非必需，不强制 P0
        if key == "visual" and r["style_id"] in ("emotion", "narrative"):
            pr, tag = "P2", "本体裁非必需"
        misses = [lbl for lbl, d in r["breakdowns"][key] if d <= 0]
        detail = f"当前 {v}/{f}（{tag}）。"
        detail += (" 待补强：" + "；".join(misses)) if misses else (" " + dim_fix(key, r["style_id"]))
        sugg.append({"pri": pr, "title": "提升" + names[key], "detail": detail})
    # 3. 反AI味
    for f in r["ai_smell"]["findings"]:
        if f.startswith("✅"):
            continue
        sugg.append({"pri": "P2", "title": "降低模板化风险", "detail": f})
    # 4. 受众撬动
    aud = r["audience"]
    if aud and aud[-1]["resonance"] < 50 and aud[-1]["weak"]:
        tip = FEATURE_TIP.get(aud[-1]["weak"], "调整内容取向以贴合该类读者")
        sugg.append({"pri": "P2", "title": "撬动「" + aud[-1]["name"] + "」",
                     "detail": "其偏好：" + aud[-1]["style"] + "。" + tip})
    # 4.5 传播要素补强
    genes = r.get("genes") or {}
    if genes:
        weakest = min(genes, key=genes.get)
        if genes[weakest] < 50:
            gtip = {
                "emotion": "加强情绪冲突与共鸣细节，戳中普遍情感点",
                "utility": "补充可操作方法论/清单/具体数据，提升干货感",
                "identity": "强化群体身份认同（我们/我也是/打工人），制造归属感",
                "social": "增加金句/反转/扎心观点，让人想转发朋友圈",
            }.get(weakest, "强化该基因以提升自发传播力")
            sugg.append({"pri": "P2", "title": "补强传播要素·" + GENE_KEYS[weakest],
                         "detail": gtip})
    order = {"P0": 0, "P1": 1, "P2": 2}
    sugg.sort(key=lambda x: order[x["pri"]])
    return sugg


def build_strengths(r):
    """提取本篇亮点（正向信号），用于在报告中高亮，避免只暴露短板。"""
    full = DIM_FULL
    names = DIM_NAMES
    items = []
    # 0. 体裁适配说明（透明化：评分已按文章实际体裁调整，避免用干货尺子量情绪文）
    items.append({"title": "评分体裁适配",
                  "detail": f"识别为「{r['style_name']}」体裁，八维评分已按该风格标准打分（含结构节奏/视觉呈现），不再以干货文尺子硬量"})
    # 1. 高分维度（>=75%）取前若干，附已命中的具体点
    ranked = sorted(((k, r["scores"][k] / full[k]) for k in full),
                    key=lambda x: x[1], reverse=True)
    for k, ratio in ranked:
        if ratio >= 0.75:
            hits = [lbl for lbl, d in r["breakdowns"][k] if d > 0][:2]
            detail = ("已做到：" + "；".join(hits)) if hits else "该维度表现稳健"
            items.append({"title": names[k] + "突出", "detail": detail})
        else:
            break
    # 2. 合规安全
    if not r["compliance"]:
        items.append({"title": "未命中已知词表",
                      "detail": "未触发当前规则词表；这不等于平台审核通过，仍需人工复核事实、来源和上下文"})
    # 3. 行文自然
    findings = r["ai_smell"]["findings"]
    if not findings or all(f.startswith("✅") for f in findings):
        items.append({"title": "行文自然",
                      "detail": "未检出明显AI腔，读者信任感更高"})
    # 4. 精准命中受众
    aud = r.get("audience") or []
    if aud and aud[0]["resonance"] >= 60:
        items.append({"title": "读者原型适配",
                      "detail": f"文本特征与「{aud[0]['name']}」预设偏好的适配指数为 {aud[0]['match_index']}；不是用户行为概率"})
    # 4.5 传播要素突出
    genes = r.get("genes") or {}
    hot = [GENE_KEYS[k] for k, v in genes.items() if v >= 70]
    if hot:
        items.append({"title": "传播要素突出",
                      "detail": "明显要素：" + "、".join(hot) + "；这是编辑信号，不代表平台推荐"})
    return items[:5]


# ============================================================
# 报告输出
# ============================================================
def fmt_md(r):
    L = []
    L.append(f"# 🔍 公众号文章编辑复核报告（{TRACKS[r['track_id']]['name']}）\n")
    L.append(f"**标题**：{r['title']}")
    L.append(f"**识别赛道**：`{r['track_id']}` {r['track_name']}")
    L.append(f"**文章风格**：`{r['style_id']}` {r['style_name']}（评分按此风格适配）")
    gate = r["editorial_gate"]
    L.append(f"**结构参考分**：**{r['scores']['total']}/100**  → 等级 **{r['level']}**（{r['level_desc']}）")
    L.append(f"**编辑结论**：**{gate['label']}** · {gate['summary']}\n")
    L.append(f"**评分可信度**：{r['score_confidence']}（规则分只描述可检测结构，不能抵消事实、来源或合规问题）")
    if gate["blockers"]:
        L.append("**发布阻断项**：" + "；".join(gate["blockers"]))
    L.append("## L1 内容八维评分")
    for key in ["title", "opening", "content", "structure", "topic",
                "readability", "visual", "interaction"]:
        name = DIM_NAMES[key]
        full = DIM_FULL[key]
        v = r["scores"][key]
        bar = "█" * int(v / full * 20)
        L.append(f"- {name}：{v}/{full} `{bar}`")
    L.append(f"- 写作风格风险扣分：-{r['scores']['ai_penalty']}（风险分 {r['ai_smell']['risk']}/100）")
    L.append("\n## 加分/扣分明细")
    for key in ["title", "opening", "content", "structure", "topic",
                "readability", "visual", "interaction"]:
        for label, delta in r["breakdowns"][key]:
            sign = "+" if delta > 0 else ""
            L.append(f"- [{key}] {label} （{sign}{delta}）")
    L.append("\n## L3 9条红线合规")
    if not r["compliance"]:
        L.append("- ✅ 未命中当前已知词表（不等于平台审核通过）")
    else:
        for it in r["compliance"]:
            tag = "🚫" if it["severity"] == "block" else "⚠️"
            fix = f" → 建议：{it['fix']}" if it.get("fix") else ""
            L.append(f"- {tag} {it['line']}（命中：{', '.join(it['hits'])}）{fix}")
    L.append("\n## L3+ 发布风险复核（机器审核 vs 内容实质）")
    cr = r.get("content_risk", {})
    machine = cr.get("machine", [])
    substantive = cr.get("substantive", [])
    confirm = cr.get("confirm", [])
    if not machine and not substantive:
        L.append("- ✅ 未发现明显的机器审核表面信号或内容实质风险")
    if machine:
        L.append("- 机器审核信号：")
        for it in machine:
            quote = f"｜片段：{it['quote']}" if it.get("quote") else ""
            L.append(f"  - ⚠️ {it['signal']}：{it['mechanism']} → {it['action']}{quote}")
    if substantive:
        L.append("- 内容实质风险：")
        for it in substantive:
            quote = f"｜片段：{it['quote']}" if it.get("quote") else ""
            keep = f"｜保留：{it['keep']}" if it.get("keep") else ""
            L.append(f"  - ⚠️ {it['signal']}：{it['mechanism']} → {it['action']}{quote}{keep}")
    if confirm:
        L.append("- 发布前人工确认：")
        for it in confirm:
            quote = f"｜片段：{it['quote']}" if it.get("quote") else ""
            L.append(f"  - {it['signal']}：{it['action']}{quote}")
    if cr.get("boundary"):
        L.append(f"> {cr['boundary']}")
    L.append("\n## 证据与时效复核")
    if not r.get("evidence"):
        L.append("- ✅ 未发现明显的来源、时效或标题正文关联提示")
    else:
        for it in r["evidence"]:
            L.append(f"- ⚠️ {it['title']}：{it['detail']}")
    L.append("\n## 事实声明账本")
    ledger = r.get("source_ledger", [])
    if not ledger:
        L.append("- 未提取到明显的权威、政策、专业、时效价格或第一人称经历声明。")
    else:
        status_names = {
            "missing_source": "缺少来源",
            "source_marker_present_unverified": "发现来源提示，尚未核验",
            "needs_author_confirmation": "需要作者确认",
        }
        for item in ledger:
            L.append(f"- [{item['claim_type']}] {status_names.get(item['status'], item['status'])}：{item['claim']} → {item['action']}")
    L.append("\n## L4 写作风格风险")
    L.append(f"- 风格风险分：**{r['ai_smell']['risk']}/100**（越高越模板化；不代表 AI 来源概率）")
    if r["ai_smell"]["findings"]:
        for f in r["ai_smell"]["findings"]:
            L.append(f"- {f if f.startswith('✅') else '⚠️ ' + f}")
    else:
        L.append("- ✅ 未发现明显模板化信号")
    L.append("\n## 账号数据基线")
    p = r["predict"]
    if p.get("baseline_reads") is None:
        L.append("- 未估算阅读量：缺少账号真实粉丝数与历史平均打开率。")
    else:
        L.append(f"- 账号历史基线：约 **{p['baseline_reads']:,}**（{p['provided_fans']:,} 粉丝 × {p['provided_open_rate']}% 历史平均打开率）")
    L.append(f"- 数据边界：{p['confidence_note']}")
    L.append("\n## 四个传播要素（启发式编辑透镜）")
    genes = r["genes"]
    for k, v in genes.items():
        bar = "█" * int(v / 100 * 20)
        L.append(f"- {GENE_KEYS[k]}：{v}/100 `{bar}`")
    L.append("\n## 读者原型适配（启发式）")
    L.append("> 说明：这是文本特征与预设读者偏好的适配指数，不是点开、读完、互动或推荐概率。")
    aud = r["audience"]
    top, bottom = aud[0], aud[-1]
    L.append(f"- 最适配：**{top['name']}**（{top['age']}·{top['identity']}）适配指数 **{top['match_index']}**/100")
    L.append(f"- 最不适配：**{bottom['name']}**（{bottom['age']}·{bottom['identity']}）适配指数 **{bottom['match_index']}**/100")
    L.append("\n各原型适配指数：")
    for a in aud:
        mark = " ◀最强" if a is top else (" ◀最弱" if a is bottom else "")
        L.append(f"- {a['name']} [{a['age']}·{a['identity']}]：适配 **{a['match_index']}**{mark}")
    if bottom["resonance"] < 50 and bottom["weak"]:
        tip = FEATURE_TIP.get(bottom["weak"], "调整内容取向以贴合该类读者")
        L.append(f"\n> 💡 想撬动『{bottom['name']}』（偏好：{bottom['style']}）：{tip}。")
    L.append("\n## 本篇亮点")
    st = build_strengths(r)
    if st:
        for s in st:
            L.append(f"- ✅ **{s['title']}**：{s['detail']}")
    else:
        L.append("- 暂无明显亮点，优先参考下方改稿建议。")
    L.append("\n## 改稿建议（按优先级）")
    for s in build_suggestions(r):
        L.append(f"- **[{s['pri']}]** {s['title']}：{s['detail']}")
    return "\n".join(L)


def fmt_html_legacy(r):
    # ---------- 动态内容块（先构建，避免外层 f-string 出现字面花括号） ----------
    p = r["predict"]
    aud = r["audience"]
    top, bottom = aud[0], aud[-1]

    dims = [(DIM_NAMES[k], k, DIM_FULL[k]) for k in
            ["title", "opening", "content", "structure", "topic",
             "readability", "visual", "interaction"]]
    bars_html = ""
    for name, key, full in dims:
        v = r["scores"][key]
        pct = max(4, int(v / full * 100))
        bars_html += (f'<div class="row"><span class="lbl">{name}</span>'
                      f'<div class="track"><div class="fill" style="width:{pct}%"></div></div>'
                      f'<span class="val">{v}<i>/{full}</i></span></div>')

    sg = build_suggestions(r)
    if sg:
        items = ""
        for s in sg:
            items += (f'<div class="sg"><span class="sg-pri pri-{s["pri"]}">{s["pri"]}</span>'
                      f'<div class="sg-body"><div class="sg-title">{s["title"]}</div>'
                      f'<div class="sg-detail">{s["detail"]}</div></div></div>')
        sugg_plain = "\n".join([f"[{s['pri']}] {s['title']}\n  {s['detail']}" for s in sg])
    else:
        items = '<p class="ok">无明显短板，保持即可。</p>'
        sugg_plain = "无明显短板，保持即可。"
    safe_plain = sugg_plain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sugg_html = (f'<div class="card rise" style="animation-delay:.15s">'
                 f'<div class="card-head"><div class="label">改稿建议 · 按优先级</div>'
                 f'<button class="copy-btn" id="copy-btn" onclick="copySuggestions()">复制清单</button></div>'
                 f'{items}'
                 f'<textarea id="sugg-plain" style="position:absolute;left:-9999px;opacity:0" readonly>{safe_plain}</textarea>'
                 f'</div>')

    st = build_strengths(r)
    if st:
        st_items = ""
        for s in st:
            st_items += (f'<div class="st"><span class="st-ico">◆</span>'
                         f'<div><div class="st-title">{s["title"]}</div>'
                         f'<div class="st-detail">{s["detail"]}</div></div></div>')
        st_html = f'<div class="card rise strength" style="animation-delay:.12s"><div class="label">本篇亮点</div>{st_items}</div>'
    else:
        st_html = ""

    genes = r["genes"]
    gene_rows = ""
    for k in ["emotion", "utility", "identity", "social"]:
        v = genes[k]
        cls = "hot" if v >= 60 else ("cold" if v < 35 else "")
        gene_rows += (f'<div class="row"><span class="lbl">{GENE_KEYS[k]}</span>'
                      f'<div class="track"><div class="fill {cls}" style="width:{v}%"></div></div>'
                      f'<span class="val">{v}</span></div>')
    genes_html = (f'<div class="card rise" style="animation-delay:.18s"><div class="label">爆款四基因 · 传播势能</div>'
                  f'{gene_rows}</div>')

    aud_rows = ""
    for a in aud:
        cls = "hot" if a is top else ("cold" if a is bottom else "")
        aud_rows += (f'<div class="row"><span class="lbl">{a["name"]}</span>'
                     f'<div class="track"><div class="fill {cls}" style="width:{a["resonance"]}%"></div></div>'
                     f'<span class="val">{a["resonance"]}</span></div>')
    advice = ""
    if bottom["resonance"] < 50 and bottom["weak"]:
        tip = FEATURE_TIP.get(bottom["weak"], "调整内容取向以贴合该类读者")
        advice = f'<p class="fix">想撬动「{bottom["name"]}」（偏好：{bottom["style"]}）：{tip}</p>'
    aud_html = (f'<div class="card rise" style="animation-delay:.21s"><div class="label">受众共鸣画像 · 启发式模拟</div>'
                f'<p class="aud-lead">🔥 最吃这套 <b>{top["name"]}</b>（{top["resonance"]}）　'
                f'🧊 最不感冒 <b>{bottom["name"]}</b>（{bottom["resonance"]}）</p>'
                f'{aud_rows}{advice}</div>')

    if not r["compliance"]:
        comp = '<p class="ok">未命中当前已知词表（不等于平台审核通过）</p>'
    else:
        comp = ""
        for it in r["compliance"]:
            cls = "block" if it["severity"] == "block" else "warn"
            fix = f'<span class="fix">建议：{it["fix"]}</span>' if it.get("fix") else ""
            comp += (f'<div class="line {cls}"><span class="dot"></span><div>'
                     f'<b>{it["line"]}</b>'
                     f'<div class="muted">命中：{", ".join(it["hits"])}</div>{fix}</div></div>')

    ai_risk = r["ai_smell"]["risk"]
    if r["ai_smell"]["findings"]:
        ai = f'<p class="muted">写作风格风险 <b>{ai_risk}/100</b>（越高越模板化，不代表 AI 来源概率）</p>'
        for f in r["ai_smell"]["findings"]:
            cls = "positive" if f.startswith("✅") else "warn"
            ai += f'<div class="line {cls}"><span class="dot"></span><div>{f}</div></div>'
    else:
        ai = f'<p class="ok">未发现明显模板化信号（风险分 {ai_risk}/100）</p>'

    score = r["scores"]["total"]
    # 按实际分数切换主色，不依赖等级名称。
    lc = "#30D158" if score >= 80 else ("#0A84FF" if score >= 60 else ("#FF9F0A" if score >= 40 else "#FF453A"))
    predict_value = p["predict"] if p["predict"] is not None else "—"
    stats_html = (f'<div class="stats">'
                  f'<div class="stat"><div class="stat-v">{predict_value}</div><div class="stat-l">账号情景阅读</div></div>'
                  f'<div class="stat"><div class="stat-v">{p["eff_open_rate"]}%</div><div class="stat-l">有效打开率</div></div>'
                  f'<div class="stat"><div class="stat-v sm">{p["pool_level"]}</div><div class="stat-l">文本传播信号</div></div>'
                  f'<div class="stat"><div class="stat-v sm">{top["name"].split("·")[0]}</div><div class="stat-l">最强受众</div></div>'
                  f'</div>')
    scenario_html = ""
    if p["predict"] is None and p.get("scenario_reads"):
        cards = "".join(
            f'<div class="scenario-item"><b>{item["fans"]:,}</b><span>粉丝</span>'
            f'<strong>约 {item["predict"]:,}</strong><small>{item["range"][0]:,}~{item["range"][1]:,}</small></div>'
            for item in p["scenario_reads"]
        )
        scenario_html = (f'<div class="scenario-note"><b>假设粉丝规模阅读情景</b>'
                         f'<span>按有效打开率计算，仅供横向参考，不代表你的账号实际阅读量</span>'
                         f'<div class="scenario-grid">{cards}</div></div>')

    css = """
:root{--text:#f5f5f7;--muted:rgba(235,235,245,.56);--border:rgba(255,255,255,.09);
--surface:rgba(28,28,30,.62);--blue:#0A84FF;--indigo:#5E5CE6;--green:#30D158;--orange:#FF9F0A;--red:#FF453A}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:radial-gradient(1100px 720px at 50% -8%,#16161b 0%,#0a0a0c 46%,#000 100%);background-attachment:fixed;
color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;max-width:820px;margin:0 auto;padding:56px 22px 90px;line-height:1.5}
.card{background:rgba(28,28,30,.52);backdrop-filter:blur(34px) saturate(180%);-webkit-backdrop-filter:blur(34px) saturate(180%);
border:1px solid rgba(255,255,255,.16);border-radius:24px;padding:28px 26px;margin:16px 0;
box-shadow:0 1px 0 rgba(255,255,255,.1) inset,0 18px 44px -26px rgba(0,0,0,.85),0 0 0 1px rgba(255,255,255,.025);animation:fadeUp .6s cubic-bezier(.2,.7,.2,1) both}
.hero{padding:32px 30px}
.label{font-size:11.5px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:16px}
.title-main{font-size:25px;font-weight:600;letter-spacing:-.022em;line-height:1.28;margin-bottom:22px;color:#fff}
.hero-row{display:flex;align-items:flex-end;gap:22px;flex-wrap:wrap}
.score-hero{font-size:88px;font-weight:700;letter-spacing:-.045em;line-height:.9;font-variant-numeric:tabular-nums}
.hero-meta{display:flex;flex-direction:column;gap:10px;padding-bottom:8px}
.pill{display:inline-block;font-size:13px;font-weight:600;padding:5px 13px;border-radius:980px}
.verdict{font-size:14px;color:var(--muted)}
.stats{display:flex;gap:14px;margin-top:26px;border-top:1px solid var(--border);padding-top:20px}
.stat{flex:1;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:16px;padding:14px 16px}
.stat-v{font-size:26px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat-v.sm{font-size:17px;font-weight:600}
.stat-l{font-size:12px;color:var(--muted);margin-top:4px;letter-spacing:.02em}
.scenario-note{margin-top:14px;padding:14px 16px;border:1px solid rgba(10,132,255,.2);border-radius:16px;background:rgba(10,132,255,.06);font-size:13px}
.scenario-note>b{display:block;color:#cfe0ff;font-size:13px;margin-bottom:3px}
.scenario-note>span{display:block;color:var(--muted);font-size:11.5px}
.scenario-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}
.scenario-item{display:flex;flex-direction:column;gap:2px;padding:10px 11px;border:1px solid var(--border);border-radius:12px;background:rgba(255,255,255,.03)}
.scenario-item b{font-size:13px}.scenario-item span,.scenario-item small{color:var(--muted);font-size:11px}.scenario-item strong{font-size:16px;color:#fff;margin-top:4px}
.row{display:flex;align-items:center;gap:14px;margin:11px 0}
.lbl{width:104px;font-size:13px;color:var(--muted);flex:none}
.track{flex:1;height:7px;background:rgba(255,255,255,.08);border-radius:5px;overflow:hidden}
.fill{height:100%;background:linear-gradient(90deg,var(--blue),var(--indigo));border-radius:5px}
.fill.hot{background:linear-gradient(90deg,#FF9F0A,#FFD166)}
.fill.cold{background:linear-gradient(90deg,#48484a,#636366)}
.val{width:46px;text-align:right;font-size:14px;font-weight:600;font-variant-numeric:tabular-nums;flex:none}
.val i{font-style:normal;color:var(--muted);font-weight:400;font-size:12px}
.sg{display:flex;gap:14px;padding:15px 0;border-bottom:1px solid var(--border)}
.sg:last-child{border-bottom:none;padding-bottom:0}
.card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.card-head .label{margin-bottom:0}
.copy-btn{font:inherit;font-size:12.5px;font-weight:600;color:#cfe0ff;background:rgba(10,132,255,.14);
border:1px solid rgba(10,132,255,.3);border-radius:980px;padding:6px 15px;cursor:pointer;
transition:background .2s,color .2s,border-color .2s;flex:none}
.copy-btn:hover{background:rgba(10,132,255,.24)}
.copy-btn.copied{color:var(--green);border-color:rgba(48,209,88,.4);background:rgba(48,209,88,.14)}
.sg-pri{flex:none;font-size:11px;font-weight:700;letter-spacing:.04em;padding:4px 9px;border-radius:8px;height:fit-content;margin-top:1px}
.pri-P0{background:rgba(255,69,58,.16);color:#FF6259}
.pri-P1{background:rgba(255,159,10,.16);color:#FFB340}
.pri-P2{background:rgba(10,132,255,.16);color:#5AA9FF}
.sg-title{font-size:15px;font-weight:600;margin-bottom:4px}
.sg-detail{font-size:13.5px;color:var(--muted);line-height:1.55}
.aud-lead{font-size:14px;margin-bottom:16px}
.aud-lead b{color:#fff;font-weight:600}
.strength{border-color:rgba(48,209,88,.22)}
.st{display:flex;gap:13px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--border)}
.st:last-child{border-bottom:none;padding-bottom:0}
.st-ico{color:var(--green);font-size:11px;margin-top:5px;flex:none}
.st-title{font-size:15px;font-weight:600;margin-bottom:3px}
.st-detail{font-size:13.5px;color:var(--muted);line-height:1.5}
.line{display:flex;gap:11px;align-items:flex-start;padding:11px 0;border-bottom:1px solid var(--border)}
.line:last-child{border-bottom:none}
.dot{flex:none;width:8px;height:8px;border-radius:50%;margin-top:6px;background:var(--orange)}
.line.block .dot{background:var(--red)}
.line.warn .dot{background:var(--orange)}
.line.positive .dot{background:var(--green)}
.line.positive{color:#d8ffe2}
.line b{font-weight:600;font-size:14px}
.muted{color:var(--muted);font-size:13px;margin-top:3px;line-height:1.5}
.fix{display:inline-block;color:#9fd0ff;font-size:12.5px;margin-top:5px}
.ok{color:var(--green);font-size:14px}
.foot{font-size:11.5px;color:var(--muted);text-align:center;margin-top:26px;letter-spacing:.02em}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.card{animation:none}}
@media (max-width:560px){.score-hero{font-size:64px}.stats{flex-direction:column}.lbl{width:84px}}
"""
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>公众号爆款检测报告</title>
<style>{css}</style></head><body>
<div class="wrap">
  <div class="card hero rise" style="animation-delay:.03s">
    <div class="label">公众号爆款检测 · {r['track_name']} · {r['style_name']}</div>
    <h1 class="title-main">{r['title']}</h1>
    <div class="hero-row">
      <div class="score-hero" style="color:{lc}">{score}</div>
      <div class="hero-meta">
        <span class="pill" style="background:{lc}22;color:{lc}">等级 {r['level']} · {r['level_desc']}</span>
        <span class="pill" style="background:rgba(94,92,230,.16);color:#9d9bff">体裁 {r['style_name']}</span>
        <div class="verdict">综合评分 / 100 · 八维·已按体裁适配</div>
      </div>
    </div>
    {stats_html}
    {scenario_html}
  </div>
  <div class="card rise" style="animation-delay:.09s"><div class="label">八维评分</div>{bars_html}</div>
  {st_html}
  {genes_html}
  {sugg_html}
  {aud_html}
  <div class="card rise" style="animation-delay:.27s"><div class="label">合规红线 · 9条</div>{comp}</div>
  <div class="card rise" style="animation-delay:.33s"><div class="label">写作风格风险</div>{ai}</div>
  <div class="foot">本报告由 wechat-hit-detector 本地生成 · 阅读量与受众为预测/模拟值，非真实数据</div>
</div>
<script>
function copySuggestions(){{
  var btn=document.getElementById('copy-btn');
  var ta=document.getElementById('sugg-plain');
  if(!ta||!btn)return;
  var text=ta.value;
  if(navigator.clipboard&&navigator.clipboard.writeText){{
    navigator.clipboard.writeText(text).then(function(){{copied(btn);}},function(){{fallback(text,btn);}});
  }}else{{fallback(text,btn);}}
}}
function fallback(text,btn){{
  var t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';
  document.body.appendChild(t);t.select();
  try{{document.execCommand('copy');copied(btn);}}catch(e){{}}
  document.body.removeChild(t);
}}
function copied(btn){{
  var old=btn.textContent;btn.textContent='✓ 已复制';btn.classList.add('copied');
  setTimeout(function(){{btn.textContent=old;btn.classList.remove('copied');}},1800);
}}
</script>
</body></html>"""
    return html


def fmt_html(r):
    """Render the current light App Store-style report UI."""
    esc = lambda value: str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    p = r["predict"]
    aud = r["audience"]
    top, bottom = aud[0], aud[-1]
    score = r["scores"]["total"]
    score_class = "score-high" if score >= 80 else ("score-good" if score >= 60 else ("score-mid" if score >= 40 else "score-low"))
    score_color = "#34C759" if score >= 80 else ("#007AFF" if score >= 60 else ("#FF9500" if score >= 40 else "#FF3B30"))
    if p.get("baseline_reads") is not None:
        scene_body = (f'<div class="scene-caption"><b>账号历史算术基线</b><span>仅使用用户提供的数据，不做本文预测</span></div>'
                      f'<div class="scenario-grid"><div class="scenario-card"><b>{p["provided_fans"]:,}</b><span>粉丝</span>'
                      f'<strong>约 {p["baseline_reads"]:,}</strong><small>{p["provided_open_rate"]}% 历史平均打开率</small></div></div>'
                      f'<div class="note">{esc(p["confidence_note"])}</div>')
        scene_meta = "账号历史基线，不是本文预测"
    else:
        scene_body = '<div class="empty">缺少账号真实粉丝数与历史平均打开率，本报告不输出阅读量、打开率或流量池数字。</div>'
        scene_meta = "未接入账号历史数据"
    # Keep the modal aligned with the engine and the Markdown report: all eight dimensions.
    score_keys = ["title", "opening", "content", "structure", "topic", "readability", "visual", "interaction"]
    dims = [(DIM_NAMES[k], k, DIM_FULL[k]) for k in score_keys]
    score_rows = "".join(f'<div class="score-row"><span>{name}</span><div class="bar"><i style="width:{max(4, int(r["scores"][key] / full * 100))}%"></i></div><b>{r["scores"][key]}<em>/{full}</em></b></div>' for name, key, full in dims)
    weakest_key = min(score_keys, key=lambda key: r["scores"][key] / DIM_FULL[key])
    weakest_name = DIM_NAMES[weakest_key]
    weakest_value = r["scores"][weakest_key]
    weakest_full = DIM_FULL[weakest_key]
    score_note = f'最需要优先复核：{weakest_name}（{weakest_value}/{weakest_full}）。先修正这一项，再看整体传播表现。'
    suggestions = build_suggestions(r)
    if suggestions:
        suggestion_cards = "".join(f'<article class="suggestion"><small>{s["pri"]} · {esc(s["title"])}</small><h3>{esc(s["title"])}</h3><p>{esc(s["detail"])}</p></article>' for s in suggestions[:4])
        plain = "\n".join(f'[{s["pri"]}] {s["title"]}\n  {s["detail"]}' for s in suggestions)
    else:
        suggestion_cards = '<div class="empty">无明显短板，保持即可。</div>'
        plain = "无明显短板，保持即可。"
    gene_rows = "".join(f'<div class="score-row"><span>{GENE_KEYS[k]}</span><div class="bar"><i style="width:{r["genes"][k]}%"></i></div><b>{r["genes"][k]}</b></div>' for k in ["emotion", "utility", "identity", "social"])
    audience_rows = "".join(f'<div class="score-row"><span>{esc(a["name"])}</span><div class="bar"><i style="width:{a["match_index"]}%"></i></div><b>{a["match_index"]}</b></div>' for a in aud[:4])
    compliance = '<div class="success">✓ 未命中当前已知词表<br><small>不等于平台审核通过，仍需结合事实、来源和上下文复核。</small></div>' if not r["compliance"] else '<div class="empty">存在需要人工复核的合规提示。</div>'
    ai_risk = r["ai_smell"]["risk"]
    cr = r.get("content_risk", {})
    risk_notes = []
    for it in cr.get("substantive", [])[:3]:
        risk_notes.append(f'内容实质 · {esc(it["signal"])}：{esc(it["action"])}')
    for it in cr.get("machine", [])[:3]:
        risk_notes.append(f'机器审核 · {esc(it["signal"])}：{esc(it["action"])}')
    for it in cr.get("confirm", [])[:2]:
        risk_notes.append(f'人工确认 · {esc(it["signal"])}：{esc(it["action"])}')
    if risk_notes:
        risk_extra = '<div class="note">' + '<br>'.join(risk_notes) + '</div>'
    else:
        risk_extra = '<div class="success">✓ 未发现明显的机器审核表面信号或内容实质风险</div>'
    ledger = r.get("source_ledger", [])
    if ledger:
        ledger_lines = [f'{esc(item["claim_type"])} · {esc(item["status"])}：{esc(item["claim"])}' for item in ledger[:6]]
        ledger_extra = '<div class="note"><b>事实声明账本</b><br>' + '<br>'.join(ledger_lines) + '</div>'
    else:
        ledger_extra = '<div class="success">✓ 未提取到明显的权威、政策、专业、时效价格或第一人称经历声明</div>'
    risk_body = f'<div class="success">✓ 合规词扫描：{"未发现当前词表命中" if not r["compliance"] else "存在需要人工复核的命中项"}<br>✓ 写作风格风险：{ai_risk}/100<br><small>词表未命中不等于平台审核通过；风险层会区分机器误判信号与内容实质问题。</small></div>{risk_extra}{ledger_extra}'
    css = """
:root{--bg:#f5f5f7;--text:#1d1d1f;--muted:#6e6e73;--blue:#007aff;--green:#34c759;--orange:#ff9500;--red:#ff3b30;--line:rgba(60,60,67,.14)}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Avenir Next","Noto Sans SC","PingFang SC","Microsoft YaHei UI",sans-serif;color:var(--text);background:radial-gradient(820px 480px at 50% -14%,#fff 0,#f5f5f7 58%,#e8ebf0 100%);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}body{padding:26px;line-height:1.5}.app{max-width:980px;margin:auto}.glass{background:rgba(255,255,255,.68);border:1px solid rgba(255,255,255,.82);box-shadow:0 1px 0 rgba(255,255,255,.95) inset,0 14px 36px rgba(60,60,67,.1);backdrop-filter:blur(32px) saturate(170%);-webkit-backdrop-filter:blur(32px) saturate(170%)}.topbar{display:flex;justify-content:space-between;align-items:center;padding:13px 18px;border-radius:17px}.brand{font-size:13px;font-weight:700}.dot{display:inline-block;width:9px;height:9px;margin-right:9px;border-radius:50%;background:#007aff;box-shadow:0 0 0 5px rgba(0,122,255,.12)}.meta{font-size:11px;color:var(--muted)}.hero{margin-top:14px;padding:40px 42px 36px;border-radius:24px}.eyebrow{font-size:11px;color:var(--muted);font-weight:700;letter-spacing:.13em}.title{font-size:clamp(31px,4vw,46px);line-height:1.1;letter-spacing:-.06em;margin:16px 0 12px}.lead{max-width:700px;color:var(--muted);font-size:14px;line-height:1.8}.scoreline{display:flex;align-items:center;gap:24px;margin-top:30px}.score{font-size:102px;line-height:.76;letter-spacing:-.1em;font-weight:800;font-variant-numeric:tabular-nums}.score-high{color:var(--green)}.score-good{color:var(--blue)}.score-mid{color:var(--orange)}.score-low{color:var(--red)}.score-info{border-left:1px solid var(--line);padding-left:24px;display:grid;gap:10px}.pill{display:inline-block;width:max-content;padding:7px 13px;border-radius:999px;font-size:12px;font-weight:700}.pill.level{background:#eaf3ff;color:#007aff}.pill.style{background:#eef0ff;color:#5856d6}.verdict{font-size:12px;color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:32px;padding-top:20px;border-top:1px solid var(--line)}.stat{min-height:78px;padding:16px 17px;border-radius:16px;background:rgba(245,245,247,.72);border:1px solid rgba(60,60,67,.1);display:grid;grid-template-columns:auto 1fr;grid-template-rows:1fr auto;column-gap:8px;align-items:center}.stat b{font-size:25px;line-height:1;grid-column:1;grid-row:1}.stat span{font-size:11px;color:var(--muted);grid-column:2;grid-row:1}.stat em{font-size:11px;color:var(--blue);font-style:normal;grid-column:1/-1;grid-row:2;margin-top:7px}.section-head{display:flex;justify-content:space-between;align-items:center;margin:25px 3px 10px}.section-head h2{font-size:17px;margin:0}.section-head span{font-size:11px;color:var(--muted)}.modules{display:grid;gap:12px}.module{width:100%;min-height:92px;padding:18px 23px;border-radius:19px;border:1px solid rgba(255,255,255,.82);background:rgba(255,255,255,.64);box-shadow:0 1px 0 rgba(255,255,255,.92) inset,0 8px 20px rgba(60,60,67,.08);display:grid;grid-template-columns:52px 1fr auto;align-items:center;gap:17px;text-align:left;color:var(--text);cursor:pointer;transition:.2s}.module:hover{transform:translateY(-2px);border-color:rgba(0,122,255,.34);box-shadow:0 12px 26px rgba(0,122,255,.12)}.module-icon{width:46px;height:46px;display:grid;place-items:center;border-radius:15px;background:#eef2ff;color:var(--blue);font-size:21px}.module:nth-child(3) .module-icon{background:#fff3e0;color:var(--orange)}.module:nth-child(4) .module-icon{background:#e9f9ef;color:var(--green)}.module strong{font-size:17px;letter-spacing:-.025em}.module small{display:block;color:var(--muted);font-size:12px;margin-top:5px}.chevron{color:#8e8e93;font-size:27px}.modal{position:fixed;inset:0;display:none;align-items:center;justify-content:center;padding:28px;background:rgba(0,0,0,.28);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);z-index:10}.modal.open{display:flex}.modal-card{width:min(900px,calc(100vw - 56px));max-height:calc(100vh - 56px);overflow:auto;padding:40px 44px;border-radius:28px;background:rgba(255,255,255,.97);border:1px solid rgba(60,60,67,.16);box-shadow:0 28px 90px rgba(0,0,0,.22)}.modal-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;padding-bottom:22px;margin-bottom:25px;border-bottom:1px solid var(--line)}.modal-head h2{font-size:32px;letter-spacing:-.055em;margin:0}.modal-head p{font-size:14px;color:var(--muted);margin:7px 0 0}.modal-actions{display:flex;gap:9px;align-items:center}.copy{border:0;border-radius:999px;padding:10px 15px;background:var(--blue);color:#fff;font:inherit;font-size:13px;font-weight:650;cursor:pointer}.copy.copied{background:var(--green)}.close{width:40px;height:40px;border-radius:50%;border:1px solid var(--line);background:#f2f2f7;color:var(--muted);font-size:24px;cursor:pointer}.scenario-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.scenario-card{padding:20px;border-radius:17px;background:#f5f5f7;border:1px solid rgba(60,60,67,.11)}.scenario-card b{font-size:14px}.scenario-card strong{display:block;font-size:30px;margin:14px 0 4px}.scenario-card span,.scenario-card small{display:block;color:var(--muted);font-size:12px}.score-row{display:grid;grid-template-columns:120px 1fr 58px;align-items:center;gap:16px;margin:19px 0;font-size:14px}.score-row>span{color:var(--muted)}.bar{height:10px;border-radius:8px;background:#e5e5ea;overflow:hidden}.bar i{display:block;height:100%;border-radius:8px;background:var(--blue)}.score-row b{text-align:right;font-size:15px}.score-row em{font-style:normal;color:var(--muted);font-size:12px}.suggestions{display:grid;grid-template-columns:1fr 1fr;gap:13px}.suggestion{padding:19px;border-radius:17px;background:#f5f5f7;border:1px solid rgba(60,60,67,.11)}.suggestion small{color:#c93400;font-weight:800;font-size:11px}.suggestion h3{font-size:17px;margin:9px 0}.suggestion p{font-size:13px;color:var(--muted);line-height:1.7;margin:0}.success{padding:18px;border-radius:17px;background:#e9f9ef;border:1px solid rgba(52,199,89,.22);color:#176b31;font-size:14px;line-height:1.9}.success small{color:#6e6e73}.note{margin-top:14px;padding:16px 18px;border-radius:16px;background:#eef5ff;border:1px solid rgba(0,122,255,.2);color:#24518a;font-size:14px;line-height:1.7}.empty{padding:20px;color:var(--muted);font-size:14px}.foot{font-size:11px;color:#8e8e93;text-align:center;margin:22px 0 4px}@media(max-width:680px){body{padding:12px}.meta{display:none}.hero{padding:28px 22px}.title{font-size:32px}.scoreline{margin-top:24px}.score{font-size:84px}.stats{grid-template-columns:1fr}.module{min-height:80px;padding:15px 17px}.modal{padding:10px}.modal-card{width:100%;max-height:calc(100vh - 20px);padding:25px 20px}.modal-head h2{font-size:27px}.scenario-grid,.suggestions{grid-template-columns:1fr}.score-row{grid-template-columns:90px 1fr 48px;gap:10px}}
"""
    css += """
.modal{display:flex;visibility:hidden;opacity:0;pointer-events:none;transition:opacity .22s ease}.modal.open{visibility:visible;opacity:1;pointer-events:auto}.modal-card{width:min(920px,calc(100vw - 56px));height:min(720px,calc(100vh - 56px));min-height:520px;max-height:calc(100vh - 56px);display:flex;flex-direction:column;overflow:hidden}.modal-panel{display:none;height:100%}.modal-panel .modal-head{flex:none}.panel-body{min-height:0;height:calc(100% - 96px);overflow:auto;padding:0 6px 8px 0}.scene-note{padding:18px 20px;border-radius:17px;background:#eef5ff;border:1px solid rgba(0,122,255,.2);color:#24518a;font-size:14px;line-height:1.7}.scene-note>b{display:block;font-size:15px;margin-bottom:3px}.scene-note>span{display:block;color:#6e6e73;font-size:12px}.subhead{font-size:18px;margin:28px 0 12px}.modal-panel .success,.modal-panel .suggestions,.modal-panel .score-row,.modal-panel .scenario-grid{flex:none}
@media(max-width:680px){.modal-card{width:100%;height:calc(100vh - 20px);min-height:0;max-height:none}.panel-body{height:calc(100% - 92px)}}
"""
    css += """
.modal{background:rgba(30,30,34,.38);backdrop-filter:blur(18px) saturate(115%);-webkit-backdrop-filter:blur(18px) saturate(115%)}.modal-card{background:#fff!important;border:1px solid rgba(60,60,67,.2);border-radius:26px;padding:34px 38px;box-shadow:0 32px 100px rgba(0,0,0,.28),0 1px 0 rgba(255,255,255,.95) inset}.modal-panel{background:#fff;min-height:100%}.modal-head{background:#fff;position:sticky;top:0;z-index:2;padding-top:2px}.panel-body{width:100%;max-width:820px;margin:0 auto}.scene-note{max-width:820px;margin:0 auto 4px}.score-row{max-width:820px;margin-left:auto;margin-right:auto}.suggestions{max-width:820px;margin:0 auto}.success{max-width:820px;margin:0 auto 12px}.note{max-width:820px;margin-left:auto;margin-right:auto}
@media(max-width:680px){.modal-card{padding:25px 20px;border-radius:22px}.modal-head{padding-top:0}}
"""
    css += """
/* Modal content follows the approved compact sheet reference: auto-height, centered, no dead space. */
.modal{align-items:center;justify-content:center;padding:28px}.modal-card{width:min(920px,calc(100vw - 64px));height:auto;min-height:0;max-height:calc(100vh - 56px);display:block;overflow:auto;padding:34px 44px;border-radius:28px;background:#fff!important}.modal-panel{height:auto;min-height:0}.modal-panel .modal-head{position:static;margin-bottom:28px;padding-bottom:22px}.panel-body{height:auto;min-height:0;overflow:visible;padding:0}.scenario-grid{grid-template-columns:repeat(3,1fr);gap:14px}.scenario-card{min-height:160px;padding:20px}.score-row{grid-template-columns:120px minmax(0,1fr) 58px;margin:20px 0}.bar{height:10px}.suggestions{grid-template-columns:1fr 1fr;gap:14px}.suggestion{min-height:150px;padding:20px}.success{margin-bottom:14px}.note{margin-top:14px}.subhead{margin:26px 0 14px}
@media(max-width:680px){.modal{padding:10px}.modal-card{width:100%;max-height:calc(100vh - 20px);padding:25px 20px;border-radius:24px}.scenario-grid,.suggestions{grid-template-columns:1fr}.score-row{grid-template-columns:90px minmax(0,1fr) 48px;gap:10px}}
"""
    css += """
/* Hard width lock: every popup uses the same wide centered sheet, never a content-sized column. */
.modal-card{width:calc(100vw - 48px)!important;max-width:920px!important;min-width:0!important;margin:0 auto}.modal-panel{width:100%!important}.modal-panel .modal-head{width:100%!important}.panel-body{width:100%!important;max-width:none!important}.score-row{width:100%!important;grid-template-columns:150px minmax(0,1fr) 64px!important}.scenario-grid,.suggestions,.success,.note{width:100%!important;max-width:none!important}
@media(max-width:680px){.modal-card{width:calc(100vw - 24px)!important;max-width:none!important}.score-row{grid-template-columns:92px minmax(0,1fr) 50px!important}}
"""
    css += """
.scene-caption{margin-bottom:18px}.scene-caption b{display:block;font-size:15px;color:#24518a;margin-bottom:3px}.scene-caption span{display:block;color:#6e6e73;font-size:12px}
"""
    css += """
/* Reference modal geometry: a centered white sheet with stable margins on desktop. */
.modal{padding:32px!important;box-sizing:border-box!important}
.modal-card{width:920px!important;max-width:calc(100% - 64px)!important;min-width:0!important;margin:0 auto!important;box-sizing:border-box!important;border-radius:28px!important}
.modal-panel{width:920px!important;max-width:calc(100% - 64px)!important;min-width:0!important;max-height:calc(100vh - 64px)!important;margin:0 auto!important;overflow:auto!important;background:#fff!important;border:1px solid rgba(60,60,67,.16)!important;border-radius:28px!important;box-shadow:0 28px 90px rgba(0,0,0,.22),0 1px 0 rgba(255,255,255,.95) inset!important;box-sizing:border-box!important}
.modal-panel .modal-head,.panel-body{width:100%!important;max-width:none!important;box-sizing:border-box!important}
.modal-panel .modal-head{padding:42px 44px 28px!important}
.panel-body{padding:30px 44px 40px!important}
.score-row{grid-template-columns:120px minmax(0,1fr) 64px!important;column-gap:16px!important}
.score-row .bar{min-width:0!important}
@media(max-width:680px){
  .modal{padding:12px!important}
  .modal-card{width:calc(100% - 24px)!important;max-width:calc(100% - 24px)!important;border-radius:22px!important}
  .modal-panel{width:calc(100% - 24px)!important;max-width:calc(100% - 24px)!important;border-radius:22px!important;max-height:calc(100vh - 24px)!important}
  .modal-panel .modal-head{padding:28px 24px 22px!important}
  .panel-body{padding:24px!important}
  .score-row{grid-template-columns:92px minmax(0,1fr) 50px!important;column-gap:10px!important}
}
.app,.hero,.topbar,.scoreline,.score-info,.stats,.stat{min-width:0}
.hero,.topbar{overflow:hidden}
.title{max-width:100%;overflow-wrap:anywhere;word-break:break-word}
.pill{max-width:100%;width:fit-content;white-space:normal;overflow-wrap:anywhere}
@media(max-width:680px){
  html,body{max-width:100%;overflow-x:hidden}
  .topbar{gap:8px}
  .scoreline{align-items:flex-start;gap:16px}
  .score-info{padding-left:16px}
}
"""
    panels = {
        "scene": ("账号数据", scene_meta, scene_body),
        "score": ("结构评分细节", "规则分只描述可检测结构，不能抵消事实与来源问题", f'{score_rows}<div class="note">{esc(score_note)}</div>'),
        "action": ("改稿方向", "先看最值得改的地方", f'<div class="suggestions">{suggestion_cards}</div>'),
        "risk": ("风险复核", "合规 · 证据 · 写作风格", risk_body),
        "audience": ("读者原型适配", "启发式参考，不是用户行为概率", f'{audience_rows}<div class="note">最适配：{esc(top["name"])}（{top["match_index"]}）。最不适配：{esc(bottom["name"])}（{bottom["match_index"]}）。</div>'),
    }
    panel_html = "".join(f'<section class="modal-panel" id="panel-{key}"><div class="modal-head"><div><h2>{title}</h2><p>{meta}</p></div><div class="modal-actions"><button class="copy" type="button">复制内容</button><button class="close" type="button">×</button></div></div><div class="panel-body">{body}</div></section>' for key, (title, meta, body) in panels.items())
    gate = r["editorial_gate"]
    evidence_count = len(r.get("evidence", []))
    data_value = f'{p["baseline_reads"]:,}' if p.get("baseline_reads") is not None else "未估算"
    data_meta = "账号历史算术基线" if p.get("baseline_reads") is not None else "缺少真实账号数据"
    stats = f'<div class="stats"><div class="stat"><b>{esc(gate["label"])}</b><span>编辑结论</span><em>{esc(gate["summary"])}</em></div><div class="stat"><b>{evidence_count}</b><span>证据提示</span><em>不能被结构分抵消</em></div><div class="stat"><b>{data_value}</b><span>账号数据</span><em>{data_meta}</em></div></div>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>公众号文章编辑复核报告</title><style>{css}</style></head><body><main class="app"><header class="topbar glass"><div class="brand"><span class="dot"></span>wechat-hit-detector · 编辑质量复核</div><div class="meta">公众号文章复核 · {esc(r["style_name"])} · 本地生成</div></header><section class="hero glass"><div class="eyebrow">公众号编辑复核 · {esc(r["track_name"])} · {esc(r["style_name"])}</div><h1 class="title">{esc(r["title"])}</h1><p class="lead">本报告先检查事实、来源和发布风险，再用结构分辅助定位短板。高分不能抵消证据缺失，也不代表平台推荐。</p><div class="scoreline"><div class="score {score_class}">{score}</div><div class="score-info"><span class="pill level" style="color:{score_color}">{esc(gate["label"])} · 等级 {r["level"]}</span><span class="pill style">体裁 {esc(r["style_name"])}</span><div class="verdict">结构参考分 / 100 · 不是爆款概率</div></div></div>{stats}</section><div class="section-head"><h2>查看复核详情</h2><span>点击模块打开详细分析</span></div><section class="modules"><button class="module" data-panel="scene"><span class="module-icon">◌</span><span><strong>账号数据</strong><small>{scene_meta}</small></span><span class="chevron">›</span></button><button class="module" data-panel="score"><span class="module-icon">◎</span><span><strong>结构评分</strong><small>八维规则信号与具体短板</small></span><span class="chevron">›</span></button><button class="module" data-panel="action"><span class="module-icon">↗</span><span><strong>改稿方向</strong><small>优先处理不能被总分抵消的问题</small></span><span class="chevron">›</span></button><button class="module" data-panel="risk"><span class="module-icon">✓</span><span><strong>风险复核</strong><small>合规、证据与自然表达</small></span><span class="chevron">›</span></button><button class="module" data-panel="audience"><span class="module-icon">◉</span><span><strong>读者适配</strong><small>文本特征与预设偏好的适配指数</small></span><span class="chevron">›</span></button></section><footer class="foot">wechat-hit-detector · 本地编辑复核 · 不预测平台推荐、阅读量或用户行为</footer></main><div class="modal" id="modal">{panel_html}</div><script>const modal=document.getElementById('modal');document.querySelectorAll('[data-panel]').forEach(function(btn){{btn.addEventListener('click',function(){{document.querySelectorAll('.modal-panel').forEach(function(p){{p.style.display='none'}});document.getElementById('panel-'+btn.dataset.panel).style.display='block';modal.classList.add('open')}})}});document.querySelectorAll('.close').forEach(function(btn){{btn.addEventListener('click',function(){{modal.classList.remove('open')}})}});modal.addEventListener('click',function(e){{if(e.target===modal)modal.classList.remove('open')}});document.addEventListener('keydown',function(e){{if(e.key==='Escape')modal.classList.remove('open')}});document.querySelectorAll('.copy').forEach(function(btn){{btn.addEventListener('click',function(){{var panel=btn.closest('.modal-panel');var text=panel.innerText;navigator.clipboard.writeText(text).then(function(){{btn.textContent='已复制';btn.classList.add('copied');setTimeout(function(){{btn.textContent='复制内容';btn.classList.remove('copied')}},1600)}})}})}});</script></body></html>'''


def main():
    # Windows PowerShell may expose a GBK stdout.  Reports contain emoji and
    # Chinese punctuation, so use UTF-8 when the stream supports reconfigure.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="公众号文章发布前编辑质量复核 v2.4 全行业版")
    ap.add_argument("title")
    ap.add_argument("article")
    ap.add_argument("--fans", type=int, default=None,
                    help="账号真实粉丝数；需与 --open-rate 同时提供才显示账号历史算术基线")
    ap.add_argument("--open-rate", type=float, default=None,
                    help="账号真实历史平均打开率；只用于算术基线，不预测本文表现")
    ap.add_argument("--track", default="auto", choices=["auto"] + list(TRACKS.keys()))
    ap.add_argument("--html-out", default=None,
                    help="HTML 报告路径；默认写入正文旁，目录不可写时回退到系统临时目录")
    args = ap.parse_args()
    try:
        with open(args.article, "r", encoding="utf-8") as f:
            body = f.read()
    except Exception as e:
        print(f"读取文章失败：{e}", file=sys.stderr)
        sys.exit(1)
    track = None if args.track == "auto" else args.track
    r = detect(args.title, body, fans=args.fans, open_rate=args.open_rate, track=track)
    md = fmt_md(r)
    print(md)
    out = args.html_out or args.article.rsplit(".", 1)[0] + "_report.html"
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(fmt_html(r))
    except OSError as e:
        fallback = os.path.join(tempfile.gettempdir(), os.path.basename(out))
        try:
            with open(fallback, "w", encoding="utf-8") as f:
                f.write(fmt_html(r))
            out = fallback
            print(f"\n⚠️ 原目录不可写，HTML 报告已回退到：{out}")
        except OSError:
            print(f"\n⚠️ HTML 报告写入失败：{e}", file=sys.stderr)
            out = None
    if out:
        print(f"\n📄 HTML 报告已生成：{out}")


if __name__ == "__main__":
    main()
