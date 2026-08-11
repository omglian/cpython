# -*- coding: utf-8 -*-
"""中文数字 → 阿拉伯数字。

人们写年龄时中文数字和阿拉伯数字混用（"我今年二十八" / "我今年28"），
年龄识别要两种都认。本模块只处理 0~999 这个区间——年龄、年级、年限
都在其中，不需要通用的大数解析。

支持：
    二十八 → 28      三十   → 30      十八   → 18
    廿八   → 28      两百   → 200     一百零五 → 105
    〇/零  → 0       两     → 2       俩     → 2
"""

_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "0": 0,
    "一": 1, "壹": 1, "1": 1,
    "二": 2, "贰": 2, "两": 2, "俩": 2, "2": 2,
    "三": 3, "叁": 3, "仨": 3, "3": 3,
    "四": 4, "肆": 4, "4": 4,
    "五": 5, "伍": 5, "5": 5,
    "六": 6, "陆": 6, "6": 6,
    "七": 7, "柒": 7, "7": 7,
    "八": 8, "捌": 8, "8": 8,
    "九": 9, "玖": 9, "9": 9,
}
_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100}

# 廿=20 卅=30 卌=40 是独立的合体数词，不参与十位运算
_COMPOUND = {"廿": 20, "卅": 30, "卌": 40}

CN_DIGIT_CHARS = "零〇○一壹二贰两俩三叁仨四肆五伍六陆七柒八捌九玖十拾百佰廿卅卌"


def cn_to_int(text):
    """把一段中文数字转成整数；无法解析时返回 None。

    纯阿拉伯数字直接走 int()，混合写法（"3十"）不予支持——现实中不出现。
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    # 合体数词：廿八 / 卅 / 卅五
    if text[0] in _COMPOUND:
        base = _COMPOUND[text[0]]
        rest = text[1:]
        if not rest:
            return base
        tail = _DIGITS.get(rest) if len(rest) == 1 else None
        return base + tail if tail is not None else None

    total = 0        # 已结算的部分
    section = 0      # 当前百位小节
    digit = None     # 待结算的个位
    for ch in text:
        if ch in _DIGITS:
            digit = _DIGITS[ch]
        elif ch in _UNITS:
            unit = _UNITS[ch]
            if unit == 10:
                # "十八" 这样省略了前导一
                section += (digit if digit is not None else 1) * 10
                digit = None
            else:  # 百
                section = (section + (digit if digit is not None else 1)) * 100 \
                    if section else (digit if digit is not None else 1) * 100
                digit = None
        else:
            return None  # 出现非数字字符，交给调用方判断
    total += section + (digit or 0)
    return total if total or text[-1] in _DIGITS else None
