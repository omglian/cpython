# -*- coding: utf-8 -*-
"""人物侧写引擎：从用户写下的人生经历中构建心理画像。

核心理念：写得越详细，画像越像本人。
实现上分四步：

1. 证据扫描 —— 全文匹配心理学词典(lexicon)中的语言信号，逐条记录
   「哪句话 → 哪个维度 → 多少权重」，保证侧写可解释、可追溯。
2. 维度打分 —— 把证据加权汇总成大五人格 / 价值观 / 依恋风格分数。
   用 tanh 压缩避免单一关键词刷爆量表，文本越长信号越可信。
3. 事实抽取 —— 用模式匹配重建生平硬事实（年龄、学历、职业、婚育…），
   这些事实决定模拟的起点状态。
4. 置信度评估 —— 根据文本长度、细节密度（数字、年份、具体名词）给出
   0~100 的置信度，直接回应"写得越详细就越像他"。

本版本为纯规则实现（零外部依赖）。接口刻意设计为可替换：
将来接入 LLM 侧写器时只需实现同样的 build_profile(text, extra) -> dict。
"""

import math
import re

from . import lexicon


# ---------------------------------------------------------------------------
# 证据扫描
# ---------------------------------------------------------------------------

def _split_sentences(text):
    """粗粒度分句，用于给证据定位出处。"""
    parts = re.split(r"[。！？!?\n;；]+", text)
    return [p.strip() for p in parts if p.strip()]


def _scan(text, sentences, table):
    """在全文中匹配一个 {keyword: weight} 词典。

    返回 (总分, 证据列表)。证据记录关键词、权重和所在句子片段。
    """
    score = 0.0
    evidence = []
    lowered = text.lower()
    for keyword, weight in table.items():
        count = lowered.count(keyword.lower())
        if count <= 0:
            continue
        # 同一关键词重复出现按 sqrt 衰减，避免复读刷分
        gained = weight * math.sqrt(count)
        score += gained
        source = ""
        for sent in sentences:
            if keyword.lower() in sent.lower():
                source = sent[:60]
                break
        evidence.append({
            "keyword": keyword,
            "weight": round(weight, 2),
            "count": count,
            "sentence": source,
        })
    evidence.sort(key=lambda e: abs(e["weight"]) * e["count"], reverse=True)
    return score, evidence


def _to_scale(raw_score, text_len):
    """把原始加权分映射到 0~100 量表，50 为人群均值。

    文本越短，越向 50 回归（信息不足时不妄下判断）。
    """
    # tanh 压缩：raw 约 ±8 时接近量表两端
    squashed = math.tanh(raw_score / 8.0)
    # 长度可信度：200 字以上信号权重才接近满额
    reliability = min(1.0, text_len / 200.0) ** 0.5
    return int(round(50 + squashed * 45 * reliability))


# ---------------------------------------------------------------------------
# 生平事实抽取
# ---------------------------------------------------------------------------

_AGE_PATTERNS = [
    re.compile(r"(?:今年|我)\s*(\d{1,2})\s*岁"),
    re.compile(r"(\d{1,2})\s*岁(?:了|的我)"),
]
_BIRTH_YEAR_PATTERNS = [
    re.compile(r"(19[5-9]\d|20[0-2]\d)\s*年\s*(?:出生|生)"),
    re.compile(r"出生于\s*(19[5-9]\d|20[0-2]\d)"),
    re.compile(r"我是\s*(19[5-9]\d|20[0-2]\d)\s*年"),
]

_EDU_RANK = [
    ("博士", 5), ("硕士", 4), ("研究生", 4), ("考研", 4), ("本科", 3),
    ("大学", 3), ("留学", 3), ("大专", 2), ("专科", 2), ("高中", 1),
    ("辍学", 0), ("退学", 0),
]

_GENDER_HINTS = [
    (re.compile(r"我是?(?:一个|个)?(男生|男孩|男人|小伙|儿子)"), "male"),
    (re.compile(r"我是?(?:一个|个)?(女生|女孩|女人|姑娘|女儿)"), "female"),
    (re.compile(r"(女朋友|女友|老婆|妻子)"), "male"),
    (re.compile(r"(男朋友|男友|老公|丈夫)"), "female"),
]


def _extract_age(text, current_year):
    for pat in _AGE_PATTERNS:
        m = pat.search(text)
        if m:
            age = int(m.group(1))
            if 5 <= age <= 100:
                return age, "文中提到年龄"
    for pat in _BIRTH_YEAR_PATTERNS:
        m = pat.search(text)
        if m:
            age = current_year - int(m.group(1))
            if 5 <= age <= 100:
                return age, "由出生年份推算"
    return None, None


def _extract_facts(text, sentences):
    """按领域抽取生平事实句，供模拟器初始化状态。"""
    facts = {}
    for domain, keywords in lexicon.FACT_PATTERNS.items():
        hits = []
        for keyword in keywords:
            if keyword in text:
                for sent in sentences:
                    if keyword in sent:
                        snippet = sent[:80]
                        if snippet not in hits:
                            hits.append(snippet)
                        break
        if hits:
            facts[domain] = hits[:8]
    return facts


def _education_level(text):
    for keyword, rank in _EDU_RANK:
        if keyword in text:
            return rank
    return 1  # 默认按高中处理


# ---------------------------------------------------------------------------
# 细节密度与置信度
# ---------------------------------------------------------------------------

def _detail_score(text):
    """细节密度 0~100：数字、年份、专有细节越多，故事越具体。"""
    length = len(text)
    numbers = len(re.findall(r"\d+", text))
    years = len(re.findall(r"(?:19|20)\d{2}", text))
    # 具体化标志词：时间、地点、因果连接
    concrete_markers = sum(
        text.count(w) for w in
        ["那年", "那天", "后来", "因为", "所以", "记得", "当时", "第一次"]
    )
    raw = (
        min(length / 800.0, 1.0) * 50
        + min(numbers / 10.0, 1.0) * 20
        + min(years / 4.0, 1.0) * 15
        + min(concrete_markers / 8.0, 1.0) * 15
    )
    return int(round(raw))


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------

def build_profile(text, extra=None, current_year=2026):
    """从人生经历文本构建完整心理侧写。

    text: 用户写下的自由文本经历
    extra: 可选的结构化补充 {"age": int, "gender": "male"/"female"}
    返回 dict，可直接 JSON 序列化。
    """
    extra = extra or {}
    text = (text or "").strip()
    sentences = _split_sentences(text)
    text_len = len(text)

    # --- 大五人格 ---
    big_five = {}
    big_five_evidence = {}
    for dim, table in lexicon.BIG_FIVE.items():
        raw, evidence = _scan(text, sentences, table)
        big_five[dim] = _to_scale(raw, text_len)
        big_five_evidence[dim] = evidence[:6]

    # --- 价值观：取相对强度并归一化排序 ---
    value_raw = {}
    for key, table in lexicon.VALUES.items():
        raw, _ = _scan(text, sentences, table)
        value_raw[key] = max(raw, 0.0)
    total = sum(value_raw.values()) or 1.0
    values = {
        key: int(round(100 * raw / total)) for key, raw in value_raw.items()
    }

    # --- 依恋风格：三型取证据最强者，无信号则默认安全型 ---
    attach_scores = {}
    for style, table in lexicon.ATTACHMENT.items():
        raw, _ = _scan(text, sentences, table)
        attach_scores[style] = raw
    best_style = max(attach_scores, key=lambda k: attach_scores[k])
    if attach_scores[best_style] < 1.5:
        best_style = "secure"

    # --- 生平事实 ---
    facts = _extract_facts(text, sentences)
    age, age_source = _extract_age(text, current_year)
    if extra.get("age"):
        age, age_source = int(extra["age"]), "用户填写"
    if age is None:
        age, age_source = 25, "默认值(文中未提及)"

    gender = extra.get("gender")
    if gender not in ("male", "female"):
        gender = None
        for pat, g in _GENDER_HINTS:
            if pat.search(text):
                gender = g
                break

    detail = _detail_score(text)
    # 总置信度 = 细节密度与证据数量的加权
    evidence_count = sum(len(v) for v in big_five_evidence.values())
    confidence = int(round(
        detail * 0.6 + min(evidence_count / 25.0, 1.0) * 40
    ))

    return {
        "big_five": big_five,
        "big_five_names": lexicon.BIG_FIVE_NAMES,
        "big_five_evidence": big_five_evidence,
        "values": values,
        "value_names": lexicon.VALUE_NAMES,
        "attachment": best_style,
        "attachment_name": lexicon.ATTACHMENT_NAMES[best_style],
        "facts": facts,
        "fact_names": lexicon.FACT_NAMES,
        "age": age,
        "age_source": age_source,
        "gender": gender,
        "education_level": _education_level(text),
        "married": any(k in text for k in ("结婚", "老婆", "妻子", "老公", "丈夫")) and "离婚" not in text,
        "has_children": any(k in text for k in ("女儿", "儿子", "孩子上", "我的孩子")),
        "entrepreneur": "创业" in text,
        "detail_score": detail,
        "confidence": confidence,
        "text_length": text_len,
    }
