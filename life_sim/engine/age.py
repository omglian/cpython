# -*- coding: utf-8 -*-
"""年龄自动识别：从自由文本的人生经历里推断"你现在多大"。

中文里说年龄的方式极多，而朴素正则极容易把别人的年龄当成你的。
本模块把识别拆成"找候选 → 过安全关 → 按可信度排序"三步：

1. **分层找候选**（tier 越小越可信）
   1 明确年龄      我今年28岁 / 廿八岁了 / 虚岁三十
   2 出生年份      1995年出生 / 我是95年的 / 生于一九九五年
   3 概数年龄      快30了 / 三十出头 / 而立之年 / 年过半百
   4 里程碑年份    2010年高考 / 2018年毕业 / 2015年上的大学
   5 在读学段      大三 / 研二 / 高二 / 小学五年级
   6 代际          90后 / 零零后
   7 工龄          工作五年了 / 毕业三年
   8 人生阶段      我退休了 / 有孙子了

2. **安全关**（任何一关不过，候选直接作废）
   * 主语归属：候选必须属于"我"。"我爸60岁""我带的学生18岁""她58岁"
     全部丢弃。主语在小句间延续——"我妈今年六十了。去年查出糖尿病"
     里第二句仍归属妈妈。
   * 过去时：  "我20岁那年"是过去的年龄，不是现在的年龄。
   * 差值表述："我老婆比我小两岁"里的"两岁"不是任何人的年龄。
   * 逝者标记："爷爷93岁走的""享年88"。
   * 群体统计："同事平均30岁""他们那一辈六十多了"。

3. **取舍**：先按 tier，再按可信度，最后按出现位置。识别不出来时
   诚实返回 None，由界面提示补一句年龄，而不是默默按默认值模拟。
"""

import re

from .cn_number import cn_to_int

# 阿拉伯数字或中文数字（年龄、年级、年限都在 0~999 内）
_NUM = r"(\d{1,3}|[零〇一二两俩三仨四五六七八九十拾廿卅百]{1,4})"

# 中文年份逐字映射——绝不能走 cn_to_int（"一九九五"是四个数字并排，不是位值）
_YEAR_DIGITS = {"零": "0", "〇": "0", "○": "0", "一": "1", "二": "2", "三": "3",
                "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
_CN_YEAR = r"([零〇○一二三四五六七八九]{2,4})"


def _cn_year_to_int(text):
    """一九九五 → 1995；九五 → 95。逐字映射，失败返回 None。"""
    out = ""
    for ch in text:
        if ch not in _YEAR_DIGITS:
            return None
        out += _YEAR_DIGITS[ch]
    return int(out) if out else None


def _century(yy, current_year):
    """两位数年份补世纪：出生年不可能晚于今年。"""
    candidate = 2000 + yy
    return candidate if candidate <= current_year else 1900 + yy


# ---------------------------------------------------------------------------
# 主语归属
# ---------------------------------------------------------------------------

# 他者：亲属 + 社会关系 + 第三人称代词。允许"我/我的"前缀，
# 这样"我女儿"会整体匹配成他者，而不是先匹配到"我"。
_OTHER_WORDS = (
    "爸爸|爸|父亲|老爸|妈妈|妈|母亲|老妈|爷爷|奶奶|外公|外婆|姥姥|姥爷|"
    "哥哥|哥|姐姐|姐|弟弟|弟|妹妹|妹|儿子|女儿|孩子|娃|外甥|侄子|侄女|"
    "孙子|孙女|老婆|妻子|老公|丈夫|媳妇|爱人|对象|男朋友|女朋友|男友|女友|"
    "前任|前妻|前夫|叔叔|阿姨|舅舅|姑姑|姨|伯父|表哥|表姐|表弟|表妹|堂哥|"
    "同事|同学|朋友|哥们|闺蜜|室友|老师|学生|学员|徒弟|师傅|领导|老板|"
    "客户|甲方|病人|患者|邻居|房东|租客|保姆|司机|员工|下属|教练|"
    "他|她|他们|她们"
)
_OTHER_RE = r"(?:我|我们|咱|咱们|俺)?(?:的)?(?:%s)" % _OTHER_WORDS
# "我"但不是"我们"；"我们"按他者处理（"我们领导""我们班"都不是本人）
_SELF_RE = r"(?:我|俺|本人)(?!们)"
_SUBJECT_RE = re.compile("(%s)|(%s)" % (_OTHER_RE, _SELF_RE))

SELF, OTHER, UNKNOWN = "self", "other", "unknown"

# 口语写作常用空格代替标点（"26了 还在读研 每天两点一线"），所以空白也断句
_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;，,、\n\r…—\s]+")


def _clause_spans(text):
    """把全文切成小句，返回 [(起, 止)]。主语判定以小句为单位。"""
    spans, start = [], 0
    for m in _CLAUSE_SPLIT_RE.finditer(text):
        if m.start() > start:
            spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _subject_marks(text):
    """全文里所有主语出现的位置：[(位置, SELF/OTHER)]。"""
    marks = []
    for m in _SUBJECT_RE.finditer(text):
        marks.append((m.start(), OTHER if m.group(1) else SELF))
    return marks


def _subject_at(pos, clause, marks):
    """判断某个位置的候选归属于谁。

    规则：先看同一小句里该位置**之前**最后一个主语；没有就继承前文
    最后一个主语（中文里主语常跨句延续）；都没有则未知。
    """
    c_start, _c_end = clause
    # 用 <= ：主语可能正是候选自己的开头（"我是1988年的"里的"我"），
    # 而他者模式会把"我女儿"整体吃掉，所以不会误判成第一人称。
    in_clause = [k for (p, k) in marks if c_start <= p <= pos]
    if in_clause:
        return in_clause[-1]
    before = [k for (p, k) in marks if p < c_start]
    return before[-1] if before else UNKNOWN


# ---------------------------------------------------------------------------
# 安全关：过去时 / 差值 / 逝者 / 群体
# ---------------------------------------------------------------------------

_PAST_RIGHT_RE = re.compile(
    r"^\s*(?:岁)?\s*(?:那年|那会儿|那会|那阵|那几年|的时候|时候|时[，,]|时我|"
    r"之前|以前|当年|当时|前后|左右的时候)")
_PAST_LEFT_RE = re.compile(
    r"(?:记得|还记得|想当年|回想|回头看|曾经|以前|从前|小时候|年轻时|当初|"
    r"那时候|那年|当年)[^。！？!?\n]{0,10}$"
    # "熬到六十岁才办的手续"——到达某个年龄，说的是过去的时点
    r"|(?:熬到|干到|做到|活到|等到|直到|一直到)\s*$")

# 假设/未来语气："又怕35岁被优化"里的 35 岁不是当前年龄
_HYPOTHETICAL_LEFT_RE = re.compile(
    r"(?:怕|担心|害怕|万一|如果|要是|假如|等到|将来|以后|听说|据说|"
    r"传说|据传)[^。！？!?\n]{0,8}$")
_HYPOTHETICAL_RIGHT_RE = re.compile(
    r"^\s*(?:岁)?\s*(?:就)?\s*(?:被优化|被裁|裁员|危机|门槛|之前一定|前一定)")

_DIFF_RE = re.compile(
    r"(?:比|跟|和)\s*[^，。！？\n]{0,6}?\s*(?:大|小)\s*(?:了)?\s*%s\s*岁"
    r"|(?:大|小)\s*(?:我|他|她)\s*%s\s*岁"
    r"|(?:差|相差|差了)\s*%s\s*岁" % (_NUM, _NUM, _NUM))

_DECEASED_RIGHT_RE = re.compile(
    # 明确的逝世表述
    r"^\s*(?:岁)?\s*(?:那年)?\s*(?:就)?\s*(?:走的|去世|过世|离世|不在了|"
    r"驾鹤|寿终|病逝)"
    # "走了/没了"有歧义（"走了半小时"），只有独占小句末尾才算
    r"|^\s*(?:岁)?\s*(?:那年)?\s*(?:就)?\s*(?:走了|没了)\s*$")
_DECEASED_LEFT_RE = re.compile(r"(?:享年|终年)\s*$")

_GROUP_RE = re.compile(
    r"平均|人均|中位|大多数|大部分|普遍|多数人|同龄人|那一辈|一代人|"
    r"我们班|我们公司|我们那|同事们|同学们")

# 虚拟语气："要是能回到18岁" —— 愿望不是事实
_WISH_RE = re.compile(
    r"如果|假如|要是|假设|万一|但愿|希望|多希望|恨不得|要能|若能|"
    r"回到|重来|重活|穿越|梦见|想象|幻想")

# 虚构语境："游戏里我捏了个25岁的角色" —— 有"我"也不是我的年龄
_FICTION_RE = re.compile(
    r"角色|主角|女主|男主|主人公|小说|电影|电视剧|动漫|漫画|游戏里|"
    r"书里|片子|剧里|作者|明星|偶像|演员|扮演|捏了个|设定")

# 表象年龄："别人都以为我25岁" —— 是别人的猜测，不是事实
_APPARENT_RE = re.compile(
    r"以为|看着像|看起来|显得|说我像|猜我|误以为|被当成|像个")

# 数字后面跟这些单位就不是年龄（用于允许省略"岁"的宽松模式）
_UNIT_GUARD = (r"(?![0-9]|岁|周|楼|层|号|路|室|栋|分|块|元|万|千|毛|角|斤|"
               r"公斤|克|吨|米|厘|公里|秒|点|天|周|月|年|届|班|名|位|个|人|"
               r"次|遍|条|件|台|度|平|％|%|k|K)")


def _blocked(text, start, end, clause):
    """安全关。返回 None 表示通过，否则返回被拦下的原因。"""
    c_start, c_end = clause
    left = text[max(c_start, start - 12):start]
    right = text[end:min(c_end + 6, end + 12)]
    clause_text = text[c_start:c_end]

    if _DECEASED_LEFT_RE.search(left) or _DECEASED_RIGHT_RE.match(right):
        return "逝者年龄"
    if _HYPOTHETICAL_LEFT_RE.search(left) or _HYPOTHETICAL_RIGHT_RE.match(right):
        return "假设/未来的年龄"
    if _PAST_LEFT_RE.search(left) or _PAST_RIGHT_RE.match(right):
        return "过去的年龄"
    if _GROUP_RE.search(clause_text):
        return "群体/平均年龄"
    if _WISH_RE.search(clause_text):
        return "假设语气"
    if _FICTION_RE.search(clause_text):
        return "虚构人物"
    if _APPARENT_RE.search(text[c_start:start]):
        return "别人以为的年龄"
    for m in _DIFF_RE.finditer(clause_text):
        if m.start() <= start - c_start < m.end():
            return "年龄差值"
    return None


# ---------------------------------------------------------------------------
# 分层候选抽取
# ---------------------------------------------------------------------------

def _n(raw):
    """把捕获到的数字（阿拉伯或中文）转成整数。"""
    return cn_to_int(raw) if raw else None


# 传统年龄代称：基准年龄 + 前缀偏移
_CLASSIC_AGES = {
    "弱冠": 20, "而立": 30, "不惑": 40, "知天命": 50, "天命": 50,
    "半百": 50, "花甲": 60, "古稀": 70, "耄耋": 80,
}
_CLASSIC_RE = re.compile(
    r"(年过|年逾|过了|已过|年近|将近|快到|快|步入|迈入|正值|届)?\s*"
    r"(弱冠|而立|不惑|知天命|天命|半百|花甲|古稀|耄耋)")

_EDU_STAGE = {
    "大一": 19, "大二": 20, "大三": 21, "大四": 22, "大五": 23,
    "研一": 23, "研二": 24, "研三": 25,
    "博一": 26, "博二": 27, "博三": 28,
    "高一": 16, "高二": 17, "高三": 18,
    "初一": 13, "初二": 14, "初三": 15,
}
_EDU_STAGE_RE = re.compile("|".join(_EDU_STAGE))

# 毕业年份 → 毕业时的典型年龄
_GRAD_BASE = [("博士", 28), ("硕士", 25), ("研究生", 25), ("本科", 22),
              ("大学", 22), ("大专", 20), ("专科", 20), ("高中", 18),
              ("中专", 18), ("初中", 15), ("小学", 12)]


class _Cand(object):
    """一个年龄候选：值、来源、位置、可信度。"""

    __slots__ = ("age", "tier", "conf", "start", "end", "how", "evidence")

    def __init__(self, age, tier, conf, start, end, how, evidence):
        self.age = age
        self.tier = tier
        self.conf = conf
        self.start = start
        self.end = end
        self.how = how
        self.evidence = evidence


def _collect(text, current_year):
    """扫出全部年龄候选（尚未过安全关）。"""
    out = []

    claimed = []  # 专用模式命中后占用的区间

    def add(age, tier, conf, m, how, span_group=None, generic=False):
        """span_group 指定用哪个捕获组定位候选——需要让左侧的
        '那年''熬到'等修饰词落在窗口内时使用。

        generic=True 的通用模式不会覆盖专用模式已占用的区间：
        "去年29岁"里的 29 归"去年"那条处理（+1），通用的"N岁"不再插手。
        """
        if age is None or not (5 <= age <= 100):
            return
        start = m.start(span_group) if span_group else m.start()
        end = m.end(span_group) if span_group else m.end()
        if generic:
            if any(s < m.end() and m.start() < e for s, e in claimed):
                return
        else:
            claimed.append((m.start(), m.end()))
        out.append(_Cand(int(age), tier, conf, start, end, how,
                         m.group(0).strip()))

    # --- tier 1: 明确的当前年龄 ---
    # 虚岁要在通用"N岁"之前跑，否则"虚岁三十"会被读成 30
    for m in re.finditer(r"(虚岁|毛岁|周岁|实岁|足岁)\s*(?:才|都|已|刚)?\s*" + _NUM, text):
        n = _n(m.group(2))
        if n is not None:
            add(n - 1 if m.group(1) in ("虚岁", "毛岁") else n,
                1, 95, m, "文中写明%s" % m.group(1))
    # 年龄字段式："年龄：29" / "我年纪三十一" / "岁数四十了"
    for m in re.finditer(r"(?:年龄|年纪|岁数)\s*(?:是|为|[:：,，])?\s*" + _NUM, text):
        add(_n(m.group(1)), 1, 93, m, "文中写明年龄")
    # 相邻数字概数："二十七八岁" → 28（必须在通用式之前 claim 掉）
    for m in re.finditer(r"([一二三四五六七八九]?[十拾])?\s*([一二三四五六七八九])"
                         r"\s*([一二三四五六七八九])\s*岁", text):
        d1, d2 = _n(m.group(2)), _n(m.group(3))
        if d1 is not None and d2 == d1 + 1:   # 只认连续数字，挡掉"三五岁"
            tens = _n(m.group(1)) if m.group(1) else 0
            add((tens or 0) + d2, 1, 82, m, "由'二十七八'式概数推算")
    # "三十有二" = 32
    for m in re.finditer(r"([一二三四五六七八九]?[十拾])\s*(?:有|又|零)\s*"
                         r"([一二三四五六七八九])\s*岁?", text):
        tens, unit = _n(m.group(1)), _n(m.group(2))
        if tens and unit:
            add(tens + unit, 1, 84, m, "文中写明年龄")
    # 刚满/整岁："刚满三十岁" —— 与"快三十"语义相反，不能合并
    for m in re.finditer(r"(?:刚刚|刚|才|将将)\s*(?:满|到|过|够|迈过)\s*"
                         + _NUM + r"\s*(?:周)?岁", text):
        add(_n(m.group(1)), 1, 90, m, "文中写明刚满的岁数")
    # "上个月刚过完30岁生日"
    for m in re.finditer(_NUM + r"\s*岁\s*(?:的)?生日\s*(?:刚|才|刚刚)?\s*(?:过完|过了|过)", text):
        add(_n(m.group(1)), 1, 90, m, "由生日推算")
    # 去年/前年的年龄要加回来
    for m in re.finditer(r"(去年|上一年|前年)\s*(?:我)?\s*(?:才|刚|就|已经)?\s*"
                         + _NUM + r"\s*(?:岁|了)", text):
        n = _n(m.group(2))
        if n is not None:
            add(n + (2 if m.group(1) == "前年" else 1), 1, 78, m,
                "由'%s的年龄'推算" % m.group(1))
    # 明年/再过N年就X了 —— 未来时要减回来
    for m in re.finditer(r"(?:明年|过完年|过了年|开年|开春)\s*(?:我)?\s*"
                         r"(?:就|才|要|便)?\s*" + _NUM + r"\s*(?:岁)?\s*了", text):
        n = _n(m.group(1))
        add(n - 1 if n else None, 1, 76, m, "由'明年就某岁'推算")
    for m in re.finditer(r"(?:再过|还有)\s*" + _NUM + r"\s*年\s*(?:我)?\s*"
                         r"(?:就|才)?\s*" + _NUM + r"\s*(?:岁)?\s*了", text):
        span, target = _n(m.group(1)), _n(m.group(2))
        if span and target:
            add(target - span, 1, 74, m, "由'再过几年就某岁'推算")
    # 简历式自述："本人男，32，北京"
    for m in re.finditer(r"(?:本人|我)?\s*[男女]\s*[,，、/|]\s*(\d{1,3})\s*(?=[,，、/|。]|$)", text):
        add(int(m.group(1)), 1, 76, m, "由自述格式识别")
    # --- tier 2: 年份锚点折算 —— "2008年我18岁" → 现在 36 岁 ---
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年[^。！？；\n]{0,8}?我\s*"
                         r"(?:才|刚|已经|那年)?\s*" + _NUM + r"\s*岁", text):
        year, n = int(m.group(1)), _n(m.group(2))
        if n is not None and 1930 <= year <= current_year:
            born = year - n
            if 1926 <= born <= current_year:
                add(current_year - born, 2, 78, m, "由'%d年时%d岁'推算" % (year, n))
    for m in re.finditer(r"我\s*" + _NUM + r"\s*岁[^。！？；\n]{0,8}?那年是?\s*"
                         r"(19\d{2}|20[0-2]\d)\s*年", text):
        n, year = _n(m.group(1)), int(m.group(2))
        if n is not None and 1930 <= year <= current_year:
            born = year - n
            if 1926 <= born <= current_year:
                add(current_year - born, 2, 78, m, "由'%d年时%d岁'推算" % (year, n))

    # 通用式放最后，前面的专用式已经把特殊写法认掉了
    for m in re.finditer(_NUM + r"\s*岁", text):
        add(_n(m.group(1)), 1, 92, m, "文中写明年龄", generic=True)
    # 省略"岁"："我今年28" / "我28了"。必须收右边界，
    # 否则"今年30号搬的家""我今年30万年终奖"都会被当成年龄。
    for m in re.finditer(r"(?:今年|现在|如今)\s*(?:我)?\s*(?:都|也|已经|才|刚)?\s*"
                         + _NUM + _UNIT_GUARD + r"(?=[了，,。、；;：:！!？?…\s]|$)", text):
        add(_n(m.group(1)), 1, 80, m, "文中写明年龄")
    for m in re.finditer(r"我\s*(?:都|也|已经|才)?\s*" + _NUM + r"\s*了" + _UNIT_GUARD, text):
        add(_n(m.group(1)), 1, 72, m, "文中写明年龄")
    # 过去时锚点："刚参加工作那年我二十二"——没有"岁"字，但有时间标记。
    # 定位到数字本身，好让左侧的"那年"被过去时判定捕获，进而参与组合推算。
    for m in re.finditer(r"(?:那年|那一年|当年|那会儿|当时|时)\s*我\s*" + _NUM
                         + r"(?![0-9岁点块元万千年月日分楼层号个])", text):
        add(_n(m.group(1)), 1, 70, m, "文中写明年龄", span_group=1)
    # 口语里常直接以"26了"开头，前面既没有"我"也没有"岁"
    for c_start, c_end in _clause_spans(text):
        m = re.match(r"\s*" + _NUM + r"\s*了$", text[c_start:c_end])
        if m:
            n = _n(m.group(1))
            if n is not None and 10 <= n <= 100:
                out.append(_Cand(n, 1, 68, c_start + m.start(1),
                                 c_start + m.end(0), "文中写明年龄",
                                 m.group(0).strip()))

    # --- tier 2: 出生年份 ---
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年?[^，。！？\n]{0,6}?(出生|生人|生的|生)", text):
        add(current_year - int(m.group(1)), 2, 90, m, "由出生年份推算")
    for m in re.finditer(r"(?:出生于|生于)\s*(19\d{2}|20[0-2]\d)", text):
        add(current_year - int(m.group(1)), 2, 90, m, "由出生年份推算")
    # "我是1995年的" —— "的"后必须收尾或接"人"，避免吃掉"我是2018年去的日本"
    for m in re.finditer(r"(?:我|本人)\s*是\s*(19\d{2}|20[0-2]\d)\s*年(?:出生|生)?的(?:人)?(?![一-龥])", text):
        add(current_year - int(m.group(1)), 2, 88, m, "由出生年份推算")
    # 两位数年份："我是95年的" / "本人03年生"
    for m in re.finditer(r"(?:我|本人)\s*(?:是)?\s*(\d{2})\s*年(?:出生|生人|生的|生|的)", text):
        add(current_year - _century(int(m.group(1)), current_year),
            2, 82, m, "由出生年份推算")
    # 中文年份："生于一九九五年" / "我是一九八八年生人"
    for m in re.finditer(r"(?:出生于|生于|我是|本人)\s*" + _CN_YEAR + r"\s*年", text):
        y = _cn_year_to_int(m.group(1))
        if y is not None:
            if y < 100:
                y = _century(y, current_year)
            if 1900 <= y <= current_year:
                add(current_year - y, 2, 80, m, "由出生年份推算")

    # --- tier 3: 概数年龄 ---
    for m in re.finditer(r"(?:快|将近|接近|差不多|马上|眼看|就要)\s*" + _NUM + r"\s*(?:岁|了)", text):
        n = _n(m.group(1))
        add(n - 1 if n else None, 3, 70, m, "由'快到某岁'估算")
    for m in re.finditer(_NUM + r"\s*(?:岁)?\s*出头", text):
        n = _n(m.group(1))
        add(n + 2 if n else None, 3, 70, m, "由'某岁出头'估算")
    for m in re.finditer(_NUM + r"\s*多岁", text):
        n = _n(m.group(1))
        add(n + 4 if n else None, 3, 66, m, "由'某十多岁'估算")
    for m in re.finditer(_NUM + r"\s*来岁", text):
        add(_n(m.group(1)), 3, 66, m, "由'某十来岁'估算")
    for m in re.finditer(_NUM + r"\s*岁?\s*好几", text):
        n = _n(m.group(1))
        add(n + 5 if n else None, 3, 64, m, "由'某十好几'估算")
    for m in _CLASSIC_RE.finditer(text):
        base = _CLASSIC_AGES[m.group(2)]
        prefix = m.group(1) or ""
        if prefix in ("年过", "年逾", "过了", "已过"):
            base += 2
        elif prefix in ("年近", "将近", "快到", "快"):
            base -= 1
        add(base, 3, 68, m, "由'%s'推算" % m.group(2))
    for m in re.finditer(r"(?:年方)?\s*二八(?:年华|佳人)", text):
        add(16, 3, 60, m, "由'二八年华'推算")

    # --- tier 4: 里程碑年份 ---
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年?\s*(?:参加)?\s*高考", text):
        add(current_year - int(m.group(1)) + 18, 4, 74, m, "由高考年份推算")
    for m in re.finditer(r"高考\s*(?:是在|在|是)\s*(19\d{2}|20[0-2]\d)", text):
        add(current_year - int(m.group(1)) + 18, 4, 74, m, "由高考年份推算")
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年[^，。！？\n]{0,10}?毕业", text):
        window = text[max(0, m.start() - 12):m.end() + 6]
        base = next((b for kw, b in _GRAD_BASE if kw in window), 22)
        add(current_year - int(m.group(1)) + base, 4, 70, m, "由毕业年份推算")
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年\s*(?:上|考上|考进|读)\s*(?:的)?\s*大学", text):
        add(current_year - int(m.group(1)) + 18, 4, 72, m, "由入学年份推算")
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*届", text):
        window = text[max(0, m.start() - 10):m.end() + 8]
        base = next((b for kw, b in _GRAD_BASE if kw in window), 22)
        add(current_year - int(m.group(1)) + base, 4, 66, m, "由毕业届别推算")

    # --- tier 5: 在读学段 ---
    for m in _EDU_STAGE_RE.finditer(text):
        add(_EDU_STAGE[m.group(0)], 5, 62, m, "由在读年级推算")
    for m in re.finditer(r"小学\s*" + _NUM + r"\s*年级", text):
        n = _n(m.group(1))
        add(6 + n if n else None, 5, 60, m, "由在读年级推算")
    # 裸年级："我上五年级了"——1~6 年级按小学算
    for m in re.finditer(r"(?<![大高初中学])" + _NUM + r"\s*年级", text):
        n = _n(m.group(1))
        if n is not None and 1 <= n <= 6:
            add(6 + n, 5, 58, m, "由在读年级推算")
    for m in re.finditer(r"应届(?:生|毕业生)?", text):
        add(22, 5, 58, m, "由'应届'推算")
    # 备考中：高考在即说明是高三应届生
    for m in re.finditer(r"(?:还有|距离|马上|即将|准备|备战|复习)"
                         r"[^。！？\n]{0,10}?高考", text):
        add(18, 5, 60, m, "由'即将高考'推算")

    # --- tier 6: 代际 ---
    for m in re.finditer(r"(\d{2})\s*后(?![来面续期]|勤)", text):
        yy = int(m.group(1))
        if yy % 10 == 0:      # 90后 → 取该十年中点
            born = _century(yy, current_year) + 5
        else:                 # 95后 → 95~99 中点
            born = _century(yy, current_year) + 2
        add(current_year - born, 6, 50, m, "由代际推算")
    for m in re.finditer(r"([零〇八九一二三四五六七]{2})\s*后(?![来面续期])", text):
        yy = _cn_year_to_int(m.group(1))
        if yy is not None:
            born = _century(yy, current_year) + (5 if yy % 10 == 0 else 2)
            add(current_year - born, 6, 46, m, "由代际推算")

    # --- tier 7: 工龄 / 毕业年限 ---
    for m in re.finditer(r"(?:工作|上班)\s*(?:了)?\s*" + _NUM + r"\s*年", text):
        n = _n(m.group(1))
        add(22 + n if n else None, 7, 48, m, "由工作年限推算")
    for m in re.finditer(r"毕业\s*(?:了)?\s*" + _NUM + r"\s*年", text):
        n = _n(m.group(1))
        add(22 + n if n else None, 7, 48, m, "由毕业年限推算")
    for m in re.finditer(r"刚\s*毕业", text):
        add(22, 7, 46, m, "由'刚毕业'推算")

    # --- tier 8: 人生阶段 ---
    for m in re.finditer(r"我\s*(?:已经)?\s*退休", text):
        add(62, 8, 40, m, "由'已退休'推算")
    for m in re.finditer(r"(?:快|将)\s*退休", text):
        add(58, 8, 38, m, "由'快退休'推算")

    return out


# ---------------------------------------------------------------------------
# 组合推算：过去的年龄 + 从那以后经过的年数 = 现在的年龄
#
# 中文叙事里这个结构非常常见，而且单看任何一半都会算错：
#   "我23岁那年出来打工……今年是我出来的第十七个年头"  → 23 + 17
#   "刚参加工作那年我二十二，从警二十三年了"            → 22 + 23
#   "熬到六十岁才办的退休手续，退休五年了"              → 60 + 5
# ---------------------------------------------------------------------------

_DURATION_RES = [
    re.compile(r"第\s*" + _NUM + r"\s*个?\s*年头"),
    re.compile(r"(?:从警|从医|从教|从业|入行|干|做|工作|上班|退休|出来|"
               r"北漂|漂了|来这|在这|待了|过去)\s*(?:了)?\s*" + _NUM + r"\s*年"),
    re.compile(_NUM + r"\s*年\s*(?:过去了|过去|下来|了)"),
]


def _durations(text):
    """抽出"经过了多少年"的表述。"""
    found = []
    for pat in _DURATION_RES:
        for m in pat.finditer(text):
            n = _n(m.group(1))
            if n is not None and 1 <= n <= 80:
                found.append((n, m.start(), m.group(0).strip()))
    return found


def _compose(past_cands, text):
    """把最早的过去年龄和最长的经过年数拼成当前年龄。"""
    durations = _durations(text)
    if not past_cands or not durations:
        return None
    anchor = min(past_cands, key=lambda c: c.start)
    span, _pos, evidence = max(durations, key=lambda d: d[0])
    age = anchor.age + span
    if not (5 <= age <= 100):
        return None
    return _Cand(age, 2, 66, anchor.start, anchor.end,
                 "由'%s'加上经过的%d年推算" % (anchor.evidence, span),
                 "%s + %s" % (anchor.evidence, evidence))


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------

def extract_age(text, current_year=2026):
    """从人生经历文本推断当前年龄。

    返回 dict：
        age        识别出的年龄，识别不出为 None
        confidence 0~100
        how        人话说明是怎么来的
        evidence   命中的原文片段
        rejected   被安全关拦下的候选（用于解释和调试）
    """
    text = text or ""
    result = {"age": None, "confidence": 0, "how": None, "evidence": None,
              "rejected": []}
    if not text.strip():
        return result

    clauses = _clause_spans(text)
    marks = _subject_marks(text)

    def clause_of(pos):
        for span in clauses:
            if span[0] <= pos < span[1]:
                return span
        return (0, len(text))

    accepted, past_cands = [], []
    for cand in _collect(text, current_year):
        clause = clause_of(cand.start)
        reason = _blocked(text, cand.start, cand.end, clause)
        subject = _subject_at(cand.start, clause, marks)
        if reason is None:
            if subject == OTHER:
                reason = "说的是别人"
            elif subject == UNKNOWN:
                cand.conf -= 10  # 没有明确主语，可信度打折但不丢弃
        if reason:
            # 属于本人的"过去年龄"留着做组合推算，别人的直接扔掉
            if reason == "过去的年龄" and subject != OTHER:
                past_cands.append(cand)
            result["rejected"].append(
                {"text": cand.evidence, "reason": reason, "age": cand.age})
        else:
            accepted.append(cand)

    # 只有在没拿到高可信当前年龄时，才用"过去年龄+经过年数"组合
    if past_cands and not any(c.tier <= 2 for c in accepted):
        composed = _compose(past_cands, text)
        if composed:
            accepted.append(composed)

    if not accepted:
        return result

    # 取舍：tier 小的优先 → 可信度高的优先 → 出现早的优先
    accepted.sort(key=lambda c: (c.tier, -c.conf, c.start))
    best = accepted[0]

    # 熔断：若有两个都很可信的当前年龄互相矛盾（差 2 岁以上），
    # 说明文本本身有歧义——诚实返回"无法判断"，而不是二选一。
    # 差 1 岁不算矛盾（出生年折算 vs 自述，生日没过就差一岁）。
    strong = [c for c in accepted if c.tier == 1 and c.conf >= 80]
    if len(strong) > 1 and max(c.age for c in strong) - min(c.age for c in strong) >= 2:
        result["how"] = "文中出现了互相矛盾的年龄"
        result["rejected"].append({
            "text": "、".join(sorted({"%d岁" % c.age for c in strong})),
            "reason": "多个自述年龄互相矛盾", "age": None})
        return result

    # 同层级里若有多个不一致的候选，可信度打折
    same_tier = [c for c in accepted if c.tier == best.tier]
    if len(same_tier) > 1 and any(abs(c.age - best.age) > 2 for c in same_tier):
        best.conf = max(30, best.conf - 15)

    result.update({"age": best.age, "confidence": max(0, min(100, best.conf)),
                   "how": best.how, "evidence": best.evidence})
    return result
