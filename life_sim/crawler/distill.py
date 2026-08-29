# -*- coding: utf-8 -*-
"""蒸馏器：把原始留言/帖子转成游戏事件模板。

流程：清洗 → 去隐私(强制) → 长度过滤 → 领域分类 → 情感定价 →
      人称改写 → 生成事件模板(dict)。

事件模板 schema（engine/events.py 负责校验与抽取）：
    id          文本规范化后的哈希，天然去重
    text        第二人称叙事文本
    domain      career/romance/family/health/finance/growth/social/misc
    valence     -2..+2 情感强度（决定默认幸福度影响）
    min_age/max_age  适用年龄段
    weight      抽取权重
    trait_bias  可选 {"O":0.3,...} 人格调制（正=该特质高更易发生）
    effects     可选 {"happiness":+4,"stress":-2,...} 状态影响
    source      来源标签
"""

import hashlib
import re

# ---------------------------------------------------------------------------
# 去隐私（顺序敏感：先长模式后短模式）
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    re.compile(r"https?://\S+|www\.\S+"),                       # 链接
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                     # 邮箱
    re.compile(r"(?:微信|weixin|wx|vx|qq|QQ)[号:：\s]*[A-Za-z0-9_-]{5,}"),  # 社交号
    re.compile(r"1[3-9]\d{9}"),                                 # 手机号
    re.compile(r"@[\w一-鿿.-]+"),                       # @用户名
    re.compile(r"\d{15,}"),                                     # 超长数字串
]


def scrub_pii(text):
    for pat in _PII_PATTERNS:
        text = pat.sub("", text)
    return text


def clean(text):
    text = scrub_pii(str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# 领域分类与情感定价（关键词启发式，中英文混合）
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS = {
    "career": ["工作", "上班", "老板", "同事", "加班", "裁员", "离职", "跳槽",
               "创业", "面试", "工资", "失业", "求职", "简历", "职场", "实习",
               "job", "work", "boss", "career", "startup", "quit", "fired",
               "interview", "resume", "layoff"],
    "romance": ["恋爱", "分手", "结婚", "离婚", "相亲", "喜欢的人", "前任",
                "对象", "爱情", "love", "girlfriend", "boyfriend", "marriage",
                "divorce", "date"],
    "family": ["父母", "爸妈", "孩子", "女儿", "儿子", "老家", "家人", "爷爷",
               "奶奶", "亲戚", "family", "parents", "kids", "mom", "dad"],
    "health": ["生病", "住院", "体检", "失眠", "抑郁", "焦虑", "健身", "锻炼",
               "医生", "health", "sick", "hospital", "sleep", "anxiety",
               "depression", "gym"],
    "finance": ["房租", "房贷", "买房", "存款", "工资", "欠债", "省钱", "涨价",
                "股票", "基金", "money", "rent", "mortgage", "salary", "debt",
                "invest"],
    "growth": ["学习", "读书", "考试", "自学", "课程", "毕业", "技能", "书",
               "learn", "study", "book", "course", "skill", "graduate"],
    "social": ["朋友", "聚会", "同学", "邻居", "网友", "孤独", "社交",
               "friend", "party", "lonely", "social", "neighbor"],
}

_POS_WORDS = ["开心", "幸福", "感动", "温暖", "惊喜", "美好", "顺利", "成功",
              "感谢", "治愈", "满足", "happy", "great", "love", "wonderful",
              "amazing", "grateful", "success"]
_NEG_WORDS = ["难过", "崩溃", "失望", "痛苦", "后悔", "失败", "焦虑", "孤独",
              "累", "哭", "绝望", "委屈", "sad", "fail", "tired", "regret",
              "terrible", "cry", "lost", "worst"]

_AGE_HINTS = [
    (["高中", "高考", "school", "teenager"], (15, 20)),
    (["大学", "毕业", "college", "campus"], (18, 26)),
    (["实习", "第一份工作", "first job"], (20, 28)),
    (["退休", "养老", "retire"], (55, 90)),
    (["孩子上学", "带娃", "kids school"], (28, 48)),
]


def classify_domain(text):
    lowered = text.lower()
    best, best_hits = "misc", 0
    for domain, words in _DOMAIN_KEYWORDS.items():
        hits = sum(1 for w in words if w in lowered)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


def score_valence(text):
    lowered = text.lower()
    pos = sum(1 for w in _POS_WORDS if w in lowered)
    neg = sum(1 for w in _NEG_WORDS if w in lowered)
    return max(-2, min(2, pos - neg))


def guess_age_range(text):
    for words, rng in _AGE_HINTS:
        if any(w in text for w in words):
            return rng
    return (16, 75)


# ---------------------------------------------------------------------------
# 人称改写：以"我"开头的叙述改为"你"；否则包装成"刷到留言"氛围事件。
# 包装模板按文本哈希确定性选择——同一句话永远得到同一个事件，保证可复现。
# ---------------------------------------------------------------------------

_WRAPPERS = [
    "你刷到一条陌生人的留言：「%s」，恍惚间想到了自己的生活。",
    "深夜的评论区里，一句话停住了你的拇指：「%s」。",
    "歌单随机到一首老歌，热评第一写着：「%s」。你单曲循环了一晚上。",
    "朋友转发来一句话：「%s」。你回了个表情，心里却记下了。",
    "你在旧笔记本的扉页看到自己抄过的一句话：「%s」，已经想不起是什么时候抄的了。",
    "地铁上你瞥见邻座手机屏幕上的一句签名：「%s」。到站了你还在想。",
]


def _stable_hash(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


# 具体事件的语言信号：有时间锚点或完成态动作，才算"发生过的事"。
# 只靠第一人称判断会把格言误当经历（"我一直以为人是慢慢变老的"不是事件）。
_TIME_MARKERS = [
    "今天", "昨天", "那天", "上周", "上个月", "去年", "前几天", "刚才",
    "早上", "中午", "下午", "晚上", "深夜", "凌晨", "今年", "那年", "当时",
]
_ACTION_VERBS = [
    "去了", "买了", "吃了", "喝了", "看到", "见到", "遇到", "收到", "接到",
    "发现", "捡到", "回了", "走了", "睡了", "醒了", "哭了", "笑了", "写了",
    "做了", "打了", "拍了", "找到", "路过", "报名", "参加", "搬", "养了",
]
# 格言腔：泛指主语 + 断言口吻，即便是第一人称也不是事件
_APHORISM_MARKERS = [
    "其实", "永远", "应该", "人生", "生命", "世界上", "所有人", "每个人",
    "总是要", "才是", "本来就", "无非", "不过是",
]


def _is_concrete_event(text):
    if any(m in text for m in _APHORISM_MARKERS):
        return False
    return (any(m in text for m in _TIME_MARKERS)
            or any(v in text for v in _ACTION_VERBS))


def to_second_person(text, allow_narrative=True):
    """返回 (叙事文本, 是否为亲历事件)。

    allow_narrative=False 时强制走氛围包装——用于一言这类"句子库"
    来源：里面即使是第一人称也是格言警句，不是某个人真实发生过的事。
    """
    first_person = re.match(r"^(我|我们)", text) or " I " in " %s " % text
    if allow_narrative and first_person and _is_concrete_event(text):
        converted = text.replace("我们", "你们").replace("我", "你")
        converted = re.sub(r"\bI\b", "you", converted)
        return converted, True
    quoted = text.rstrip("。.!！?？~；;，,")  # 引号内去掉句尾标点，避免「。」。
    wrapped = _WRAPPERS[_stable_hash(text) % len(_WRAPPERS)] % quoted
    return wrapped, False


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

MIN_LEN, MAX_LEN = 8, 160

# 内容安全过滤：涉及自我伤害等的语料不进入游戏事件池
_CONTENT_BLOCKLIST = ["自杀", "轻生", "割腕", "去死", "上吊", "烧炭", "自残"]


def distill(raw_text, source="import", allow_narrative=True):
    """单条原始文本 → 事件模板 dict；不合格返回 None。

    allow_narrative=False 用于句子/语录类来源：产出的事件一律是
    "刷到一句话"的氛围事件，不冒充玩家的亲历经历。
    """
    text = clean(raw_text)
    if not (MIN_LEN <= len(text) <= MAX_LEN):
        return None
    if any(term in text for term in _CONTENT_BLOCKLIST):
        return None
    domain = classify_domain(text)
    valence = score_valence(text)
    min_age, max_age = guess_age_range(text)
    narrative, direct = to_second_person(text, allow_narrative=allow_narrative)

    event = {
        "id": "evt_" + hashlib.sha256(
            re.sub(r"\W+", "", text.lower()).encode("utf-8")).hexdigest()[:12],
        "text": narrative,
        "domain": domain,
        "valence": valence,
        "min_age": min_age,
        "max_age": max_age,
        # kind 决定事件走哪条抽取配额（见 engine/events.py）：
        # 第一人称改写后是"亲历事件"，第三人称金句是"氛围事件"
        "kind": "narrative" if direct else "ambient",
        "weight": 1.0 if direct else 0.5,
        "effects": {"happiness": valence * 3,
                    "stress": -valence * 2 if valence else 1},
        "source": source,
    }
    return event


def distill_all(items, allow_narrative=True):
    """(source, text) 迭代器 → 去重后的事件列表。"""
    seen, out = set(), []
    for source, raw in items:
        ev = distill(raw, source=source, allow_narrative=allow_narrative)
        if ev and ev["id"] not in seen:
            seen.add(ev["id"])
            out.append(ev)
    return out
