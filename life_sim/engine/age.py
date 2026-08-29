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
_NUM = r"(\d{1,3}|[零〇一二两俩三仨四五六七八九十拾廿卅卌百]{1,4})"

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
    # 直系与长辈（含口语：爹娘、老爷子、姥、爷）
    "爸爸|爸|爹|父亲|老爸|老爹|妈妈|妈|娘|母亲|老妈|老娘|爷爷|奶奶|"
    "外公|外婆|姥姥|姥爷|姥|爷|老爷子|老太太|老头|老伴|那口子|"
    # 平辈与晚辈（含口语：闺女、丫头、小子）
    "哥哥|哥|姐姐|姐|弟弟|弟|妹妹|妹|儿子|女儿|闺女|丫头|小子|崽|"
    "孩子|小孩|娃|宝宝|外甥|外甥女|侄子|侄女|侄儿|孙子|孙女|外孙|外孙女|"
    # 配偶与姻亲
    "老婆|妻子|老公|丈夫|媳妇|爱人|对象|男朋友|女朋友|男友|女友|"
    "前任|前妻|前夫|岳父|岳母|公公|婆婆|女婿|儿媳|嫂子|姐夫|妹夫|弟妹|"
    # 旁系亲属
    "叔叔|叔|阿姨|舅舅|舅|姑姑|姑|姨|伯父|大伯|伯母|舅妈|姑父|姨夫|"
    "表哥|表姐|表弟|表妹|堂哥|堂姐|堂弟|堂妹|小舅子|大姨子|"
    # 学习与工作关系
    "同事|同学|朋友|哥们|闺蜜|室友|老师|导师|班主任|教授|学生|学员|"
    "学长|学姐|学弟|学妹|师兄|师姐|师弟|师妹|徒弟|师傅|师父|"
    "领导|老板|上司|主管|经理|助理|秘书|员工|下属|同行|合伙人|搭档|"
    # 其他社会关系
    "客户|甲方|乙方|病人|患者|医生|护士|邻居|房东|租客|保姆|司机|保安|"
    "教练|战友|队友|网友|发小|死党|老乡|老人|老者|大爷|大妈|大叔|"
    # 宠物也会被写年龄（"家里养了条狗，6岁了"）
    "狗|猫|狗子|猫咪|宠物|乌龟|鹦鹉|"
    # 第三人称代词
    "他|她|他们|她们|人家"
)
_OTHER_RE = (
    r"(?:我|我们|咱|咱们|俺)?(?:的)?(?:%s)"
    # 指示短语引入的另一个主体："这台车明年就20了"说的不是人的年龄
    r"|(?:这|那)(?:台|辆|个|只|条|间|套|部|本|张|把|双|件|棵|株|家)[一-龥]{0,3}"
    # 量词短语同理："家里还养了条狗，6岁了"
    r"|(?:养|买|有|捡|领养|收养)(?:了)?\s*(?:一|两|三|几)?\s*"
    r"(?:条|只|头|匹|台|辆|部|棵|盆)[一-龥]{0,3}"
    % _OTHER_WORDS)
# "我"但不是"我们"；"我们"按他者处理（"我们领导""我们班"都不是本人）
_SELF_RE = r"(?:我|俺|本人)(?!们)"
_SUBJECT_RE = re.compile("(%s)|(%s)" % (_OTHER_RE, _SELF_RE))

# "我" + 一个不在词表里的称谓（"我表侄""我那位战友"）：说不准是谁，按未知处理，
# 总好过把陌生称谓的年龄安到使用者头上。
_UNKNOWN_KIN_RE = re.compile(
    r"(?:我|我们|咱)(?:那位|这位|那个|这个|的)?\s*"
    # 中间必须是称谓性的词：排除数字与时间词，否则"我今年三十八岁"
    # 会被当成"我+称谓'今年三'"，把使用者自己的年龄判成陌生人的
    r"[^0-9零〇一二两俩三仨四五六七八九十拾廿卅卌百今现明昨去前，。！？；\s]{1,3}"
    r"(?=今年|现在|[0-9零〇一二两三四五六七八九十廿卅]{1,4}\s*岁)")

# "我"在这些词后面是宾语不是主语："我爸念叨我"里的"我"不能当主语
_OBJECT_MARKERS = (
    "念叨|骂|说|问|告诉|带|教|照顾|陪|骗|夸|批评|表扬|喊|叫|找|等|"
    "看|管|养|生|接|送|催|劝|帮|拉|推|打|疼|爱|恨|想|见|跟|对|给|替|和|与|比")
_OBJECT_SELF_RE = re.compile(r"(?:%s)\s*$" % _OBJECT_MARKERS)

# 引号内的第一人称是别人的自述："他说'我今年40了'"
_QUOTE_RE = re.compile(r"[\"“”'‘’「」『』]")
_SPEECH_VERB_RE = re.compile(r"(?:说|讲|问|答|回|抱怨|感慨|念叨|嘟囔|表示)\s*[:：]?\s*$")

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


def _in_quote(text, pos):
    """位置是否落在引号里（引号内的"我"是被引述者的自称）。"""
    return len(_QUOTE_RE.findall(text[:pos])) % 2 == 1


def _subject_marks(text):
    """全文里所有主语出现的位置：[(位置, SELF/OTHER)]。

    三种情况下的"我"不算第一人称主语：
    * 宾语位（"我爸念叨我"）
    * 定语从句里（"跟我一起长大的发小"——中心词才是主语）
    * 引号内（"他说'我今年40了'"）
    """
    marks = []
    for m in _SUBJECT_RE.finditer(text):
        if m.group(1):
            marks.append((m.start(), OTHER))
            continue
        left = text[max(0, m.start() - 6):m.start()]
        if _OBJECT_SELF_RE.search(left):
            continue                      # 宾语位的"我"
        if _in_quote(text, m.start()):
            marks.append((m.start(), OTHER))   # 引述别人的自称
            continue
        # 定语从句："…我…的 + 名词"，真正的主语是后面那个名词
        tail = text[m.end():m.end() + 12]
        if re.match(r"[^，。！？；\n]{0,8}的[一-龥]{1,4}", tail):
            continue
        marks.append((m.start(), SELF))
    # "我" + 未收录称谓 → 未知归属，防止陌生称谓穿透成第一人称
    for m in _UNKNOWN_KIN_RE.finditer(text):
        if not _SUBJECT_RE.match(text, m.start()) or \
                _SUBJECT_RE.match(text, m.start()).group(1) is None:
            marks.append((m.end() - 1, UNKNOWN))
    marks.sort()
    return marks


_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n\r]+")


def _sentence_start(text, pos):
    """候选所在句子的起点。主语继承不跨句——中文里换一句话通常会
    重新确立主语，顺口提到的"班主任""同事"不该污染后面的句子。"""
    starts = [m.end() for m in _SENTENCE_SPLIT_RE.finditer(text)
              if m.end() <= pos]
    return starts[-1] if starts else 0


def _subject_at(pos, clause, marks, text=""):
    """判断某个位置的候选归属于谁。

    先看同一小句里该位置**之前**最后一个主语；没有就看小句里位置
    之后的主语（"今年五十岁的是我妈"这种判断句语序）；再没有就继承
    **同一句话内**前面的主语；都没有则未知。
    """
    c_start, c_end = clause
    # 用 <= ：主语可能正是候选自己的开头（"我是1988年的"里的"我"），
    # 而他者模式会把"我女儿"整体吃掉，所以不会误判成第一人称。
    in_clause = [k for (p, k) in marks if c_start <= p <= pos]
    if in_clause:
        return in_clause[-1]
    # 后视：主语出现在数字之后（"今年五十岁的是我妈"）
    after = [k for (p, k) in marks if pos < p < c_end]
    if after and after[0] == OTHER:
        return OTHER
    s_start = _sentence_start(text, c_start) if text else 0
    before = [k for (p, k) in marks if s_start <= p < c_start]
    return before[-1] if before else UNKNOWN


# ---------------------------------------------------------------------------
# 安全关：过去时 / 差值 / 逝者 / 群体
# ---------------------------------------------------------------------------

_PAST_RIGHT_RE = re.compile(
    r"^\s*(?:岁)?\s*(?:那年|那会儿|那会|那阵|那阵子|那几年|那时|的时候|时候|"
    r"时[，,]|时我|之前|以前|当年|当时|前后|左右的时候)")
# 完成体"V+的+O"：我25岁结的婚 / 30岁买的房 / 18岁去当的兵。
# 要在**小句范围内**判断——"我25岁结的婚，那年刚工作"里"结的婚"到逗号为止。
_PERFECTIVE_RE = re.compile(
    r"^\s*(?:岁)?\s*(?:就|才|上|下|去|才去)?\s*[一-龥]{1,3}的[一-龥]{1,4}\s*$")
_PAST_LEFT_RE = re.compile(
    r"(?:记得|还记得|想当年|回想|回头看|曾经|以前|从前|小时候|年轻时|当初|"
    r"那时候|那年|那会儿|那会|那阵|那阵子|那几年|那年头|那时|当年|"
    r"读书时|上学时)[^。！？!?\n]{0,10}$"
    # "熬到六十岁才办的手续"——到达某个年龄，说的是过去的时点
    r"|(?:熬到|干到|做到|活到|等到|直到|一直到|攒到|涨到|降到)\s*$")

# 回溯叙事标记：整段在讲往事，段内的年龄都不是当前年龄
_RETROSPECT_RE = re.compile(
    r"那时候|那会儿|那阵子|后来|再后来|一晃|回头看|如今想来|现在想想")
# 现在时锚点：出现后，回溯语境结束
_PRESENT_ANCHOR_RE = re.compile(r"现在|如今|目前|今年|眼下|这会儿|至今")

# 假设/未来/意图语气："又怕35岁被优化""我计划40岁前还完房贷"
_HYPOTHETICAL_LEFT_RE = re.compile(
    r"(?:怕|担心|害怕|万一|如果|要是|假如|将来|以后|听说|据说|传说|据传|"
    # 意图与计划：中文表达未来目标最常用的一批词
    r"计划|打算|准备|争取|力争|目标|期限|盼着|盼望|指望|想在|想着|梦想|"
    r"立志|规划|希望在)[^。！？!?\n]{0,8}$"
    # "等我到40岁"——主语常插在"等"和"到"中间
    r"|等\s*(?:我|你|他|她|孩子|娃)?\s*(?:到了?|长到|活到)?[^。！？\n]{0,4}$")
_HYPOTHETICAL_RIGHT_RE = re.compile(
    r"^\s*(?:岁)?\s*(?:就)?\s*(?:被优化|被裁|裁员|危机|门槛|之前一定|前一定)"
    # "40岁前把房贷还完""35岁以下"——年龄作为界标而非当前状态
    r"|^\s*(?:岁)?\s*(?:前|之前|以后|之后|以下|以上|左右就|才能|之前一定)")

# 引用外部年龄标准：招聘门槛、政策规定，不是本人年龄
_NORM_RE = re.compile(
    r"招聘|启事|岗位|要求|限|卡在|规定|法定|政策|新闻|报道|市场上|这行|"
    r"门槛|标准|年龄段|以下的|以上的|分水岭")

# 体检/比喻年龄：心脏年龄、骨龄、"心态上还是18岁"都不是实际年龄
_METAPHOR_RE = re.compile(
    r"骨龄|骨骼年龄|心脏年龄|血管年龄|肺年龄|皮肤年龄|生理年龄|身体机能|"
    r"心态上|心理上|心里|精神上|骨子里|感觉自己|觉得自己|还是那个|镜子里|"
    r"相当于")

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
    r"回到|重来|重活|穿越|梦见|想象|幻想|"
    r"宁愿|宁可|真想|好想|巴不得|停在|停留在|变回|退回|回不到|"
    r"后悔|要不是|当初要是|一辈子停")

# 虚构语境："游戏里我捏了个25岁的角色" —— 有"我"也不是我的年龄
_FICTION_RE = re.compile(
    r"角色|主角|女主|男主|主人公|小说|电影|电视剧|动漫|漫画|游戏里|"
    r"书里|片子|剧里|作者|明星|偶像|演员|扮演|捏了个|设定")

# 表象年龄："别人都以为我25岁" —— 是别人的猜测，不是事实
_APPARENT_RE = re.compile(
    r"以为|看着像|看起来|显得|说我像|说我长得像|夸我像|猜我|误以为|被当成|"
    r"像个|长得像|看上去")

# 数量语境：小句里在谈体重/身高/工资/分数时，不带"岁"字的数字不是年龄
_QUANTITY_CONTEXT_RE = re.compile(
    r"体重|身高|称重|工资|月薪|年薪|存款|房贷|分数|成绩|考了|公斤|公里|"
    r"斤|米|块钱|万元|度|楼|层|号|分钟|小时|价格|降到|涨到")

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
    if _PAST_LEFT_RE.search(left) or _PAST_RIGHT_RE.match(right) \
            or _PERFECTIVE_RE.match(text[end:c_end]):
        return "过去的年龄"
    if _GROUP_RE.search(clause_text):
        return "群体/平均年龄"
    if _WISH_RE.search(clause_text):
        return "假设语气"
    if _FICTION_RE.search(clause_text):
        return "虚构人物"
    if _NORM_RE.search(clause_text):
        return "外部年龄标准"
    if _METAPHOR_RE.search(clause_text):
        return "比喻/体检年龄"
    if _APPARENT_RE.search(text[c_start:start]):
        return "别人以为的年龄"
    # 谈论数量的句子里，没有"岁"字的数字不是年龄（"体重八十出头"）
    if _QUANTITY_CONTEXT_RE.search(clause_text) \
            and "岁" not in text[start:min(end + 2, c_end)]:
        return "数量而非年龄"
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
    for m in re.finditer(r"(去年|上一年|前年)\s*(?:我\s*)?(?:才|刚|就|已经)?\s*"
                         + _NUM + r"\s*(?:岁|了(?=[，,。！？\s]|$))", text):
        n = _n(m.group(2))
        if n is not None:
            add(n + (2 if m.group(1) == "前年" else 1), 1, 78, m,
                "由'%s的年龄'推算" % m.group(1))
    # 明年/再过N年就X了 —— 未来时要减回来
    for m in re.finditer(r"(?:我\s*)?(?:明年|过完年|过了年|开年|开春)\s*(?:我\s*)?"
                         r"(?:就|才|要|便)?\s*" + _NUM
                         + r"\s*(?:岁\s*了|了" + _UNIT_GUARD + r")", text):
        n = _n(m.group(1))
        add(n - 1 if n else None, 1, 76, m, "由'明年就某岁'推算")
    for m in re.finditer(r"(?:再过|还有)\s*" + _NUM + r"\s*年\s*(?:我)?\s*"
                         r"(?:就|才)?\s*" + _NUM + r"\s*(?:岁)?\s*了", text):
        span, target = _n(m.group(1)), _n(m.group(2))
        if span and target:
            add(target - span, 1, 74, m, "由'再过几年就某岁'推算")
    # 简历式自述："本人男，32，北京"
    for m in re.finditer(r"(?:本人|我)\s*[，,]?\s*[男女]\s*[,，、/|]\s*(\d{1,3})\s*(?=[,，、/|。]|$)", text):
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
                         + _UNIT_GUARD, text):
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
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年?[^，。！？\n]{0,6}?"
                         r"(?:出生|生人|生的|生(?![意活产长机命病气死物存育娃]))", text):
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
    for m in re.finditer(r"(?:快|将近|接近|差不多|马上|眼看|就要)\s*(?:我)?\s*"
                         + _NUM + r"\s*(?:岁|了)", text):
        n = _n(m.group(1))
        add(n - 1 if n else None, 3, 70, m, "由'快到某岁'估算")
    for m in re.finditer(_NUM + r"\s*岁?\s*出头(?![0-9])", text):
        n = _n(m.group(1))
        add(n + 2 if n else None, 3, 70, m, "由'某岁出头'估算")
    for m in re.finditer(_NUM + r"\s*多岁", text):
        n = _n(m.group(1))
        add(n + 4 if n else None, 3, 66, m, "由'某十多岁'估算")
    for m in re.finditer(_NUM + r"\s*来岁", text):
        add(_n(m.group(1)), 3, 66, m, "由'某十来岁'估算")
    for m in re.finditer(_NUM + r"\s*岁\s*好几", text):
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
    for m in re.finditer(r"(19\d{2}|20[0-2]\d)\s*年?\s*(?:参加)?\s*"
                         r"高考(?!作文|题|试卷|新闻|政策|改革|人数)", text):
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
    for m in re.finditer(r"(?<![大高初中学教带])" + _NUM + r"\s*年级", text):
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
    for m in re.finditer(r"(?<![过到于])(\d{2})\s*后(?![来面续期]|勤)(?![我才就的]?[0-9])", text):
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

    has_self = any(k == SELF for (_p, k) in marks)
    has_other = any(k == OTHER for (_p, k) in marks)

    accepted, past_cands = [], []
    last_past_end = -1   # 上一个"过去年龄"候选的位置，用于时态继承
    for cand in sorted(_collect(text, current_year), key=lambda c: c.start):
        clause = clause_of(cand.start)
        reason = _blocked(text, cand.start, cand.end, clause)

        # 出生年、里程碑年份是绝对时间锚点，本身换算出的就是当前年龄，
        # 不受时态影响——"2019年毕业"无论出现在多少回忆之后都成立。
        absolute_anchor = cand.tier in (2, 4)
        if reason == "过去的年龄" and absolute_anchor:
            reason = None

        # 时态继承：前一句已在讲往事，中间又没有出现"现在/今年"这类
        # 现在时锚点，那么这一句的年龄同样属于往事。
        # "我18岁那年考上大学，22岁毕业进了国企" —— 22 也是过去的年龄。
        if reason is None and not absolute_anchor \
                and 0 <= last_past_end < cand.start:
            between = text[last_past_end:cand.start]
            if len(between) <= 40 and not _PRESENT_ANCHOR_RE.search(between):
                reason = "过去的年龄"

        subject = _subject_at(cand.start, clause, marks, text)
        if reason is None:
            if subject == OTHER:
                reason = "说的是别人"
            elif subject == UNKNOWN:
                # 没有明确主语时，看这句之前有没有出现过别人：出现过就
                # 可能是在接着说别人（"床上那位老人今年九十五岁"），不认领；
                # 没出现过则默认是叙述者自己（"26了 还在读研"），但打折。
                s_start = _sentence_start(text, cand.start)
                other_before = any(k == OTHER and s_start <= p < cand.start
                                   for (p, k) in marks)
                if other_before:
                    reason = "说不准是谁的年龄"
                else:
                    cand.conf -= 10
        if reason == "过去的年龄":
            last_past_end = cand.end
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
    # 只有"我"直接锚定的自述年龄才参与矛盾判定——否则一个漏网的他人年龄
    # 会把使用者明明白白写出来的年龄一起熔断掉。
    strong = [c for c in accepted if c.tier == 1 and c.conf >= 80
              and re.search(r"(?:我|本人|今年|年龄|年纪|岁数)",
                            text[max(0, c.start - 8):c.end])]
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
