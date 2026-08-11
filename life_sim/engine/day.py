# -*- coding: utf-8 -*-
"""逐日模拟引擎：一次生成一整天，带上下文记忆。

年度模拟给的是人生骨架（哪年升职、哪年结婚），这里给的是血肉：
每天从清晨到深夜六个时段，十来条具体的事。

**上下文记忆**是这个引擎的核心，靠四样东西实现：

1. **状态连续** —— 精力、心情、压力、钱、健康逐日结转。昨天熬到两点，
   今早就起不来；连着加班三天，身体会出问题。
2. **剧情线（threads）** —— 跨天的故事线：一个赶不完的项目、一段刚
   萌芽的感情、一场感冒、一个坚持不下去的健身计划。每条线有阶段，
   每天推进一点，会自己开始也会自己结束。
3. **人物记忆（npcs）** —— 出现过的人会被记住：名字、关系、亲密度、
   上次见面是哪天。同一个同事会反复出现，关系有来有回。
4. **近期记忆（recent）** —— 最近几天发生了什么，今天的叙述会回指
   （"昨天没睡好的后遗症一直到中午才散"）。

可复现：随机种子取自 经历文本 + 第几天，同一段经历重演出同一串日子。
"""

import hashlib
import json
import os
import random

SLOTS = [
    ("dawn", "清晨"),
    ("morning", "上午"),
    ("noon", "中午"),
    ("afternoon", "下午"),
    ("evening", "傍晚"),
    ("night", "夜里"),
]

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

SEASONS = {
    (3, 4, 5): "春", (6, 7, 8): "夏",
    (9, 10, 11): "秋", (12, 1, 2): "冬",
}

# 天气按季节有不同的分布，并且有惯性——不会晴一天雨一天地乱跳
WEATHER_BY_SEASON = {
    "春": ["晴", "多云", "小雨", "阴", "大风"],
    "夏": ["晴", "闷热", "雷阵雨", "多云", "暴雨"],
    "秋": ["晴", "多云", "阴", "小雨", "转凉"],
    "冬": ["晴", "阴", "小雪", "寒风", "雾霾"],
}

DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "day_events.json")

_templates_cache = {}


def load_templates(path=None):
    """加载日常事件模板，按时段分组。"""
    path = path or DATA_PATH
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    cached = _templates_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    by_slot = {}
    for tpl in data if isinstance(data, list) else []:
        if not isinstance(tpl, dict) or "text" not in tpl:
            continue
        by_slot.setdefault(tpl.get("slot", "any"), []).append(tpl)
    for slot in by_slot:
        by_slot[slot].sort(key=lambda t: t.get("id", t["text"]))
    _templates_cache[path] = (mtime, by_slot)
    return by_slot


# ---------------------------------------------------------------------------
# 剧情线定义：跨天的故事
# ---------------------------------------------------------------------------

THREAD_KINDS = {
    "project": {
        "title": "手上的项目",
        "stages": ["刚接手", "推进中", "卡住了", "赶工", "交付", "复盘"],
        "domain": "career",
        "start_when": "employed",
        "base_chance": 0.05,
        "advance": 0.35,
    },
    "crush": {
        "title": "一段刚起头的心动",
        "stages": ["注意到对方", "开始搭话", "约了一次", "越聊越晚", "挑明"],
        "domain": "romance",
        "start_when": "single",
        "base_chance": 0.025,
        "advance": 0.22,
    },
    "cold": {
        "title": "一场感冒",
        "stages": ["嗓子不舒服", "开始发烧", "最难受的一天", "退烧", "痊愈"],
        "domain": "health",
        "start_when": "always",
        "base_chance": 0.012,
        "advance": 0.45,
    },
    "fitness": {
        "title": "健身计划",
        "stages": ["办了卡", "新鲜劲", "开始偷懒", "重新捡起", "成了习惯"],
        "domain": "health",
        "start_when": "always",
        "base_chance": 0.02,
        "advance": 0.2,
    },
    "jobhunt": {
        "title": "看新机会",
        "stages": ["偷偷改简历", "投了几家", "接到面试", "等结果", "有了答复"],
        "domain": "career",
        "start_when": "employed",
        "base_chance": 0.015,
        "advance": 0.25,
    },
    "family": {
        "title": "家里的事",
        "stages": ["接到电话", "放心不下", "决定回去", "回了一趟", "心里踏实了"],
        "domain": "family",
        "start_when": "always",
        "base_chance": 0.02,
        "advance": 0.3,
    },
    "hobby": {
        "title": "捡起来的爱好",
        "stages": ["买了工具", "笨拙地开始", "有点上手", "做出了个东西"],
        "domain": "growth",
        "start_when": "always",
        "base_chance": 0.025,
        "advance": 0.22,
    },
    "conflict": {
        "title": "一点没解开的疙瘩",
        "stages": ["起了争执", "冷着", "有人先开口", "说开了"],
        "domain": "social",
        "start_when": "always",
        "base_chance": 0.018,
        "advance": 0.3,
    },
    "move": {
        "title": "搬家这件事",
        "stages": ["房东涨租", "开始看房", "定下来了", "打包", "搬完了"],
        "domain": "finance",
        "start_when": "always",
        "base_chance": 0.008,
        "advance": 0.25,
    },
}

# 剧情线每个阶段的具体叙述，按 kind → 阶段序号
THREAD_TEXTS = {
    "project": [
        "{npc}把一个新项目扔给了你，说不急，但你知道那意味着什么。",
        "项目推进到一半，需求又改了两版。你把改动记在便签上，贴满了半个屏幕。",
        "卡在一个怎么也绕不过去的问题上，你盯着屏幕发了十分钟呆。",
        "为了赶进度，你又留到了很晚。楼里只剩几盏灯还亮着。",
        "东西终于交出去了。{npc}回了个「收到」，你却在工位上坐了好一会儿。",
        "复盘会上大家说了不少漂亮话。你想起那些改需求的夜晚，没说什么。",
    ],
    "crush": [
        "你注意到{npc}今天换了发型，还多看了两眼——这个念头让你自己愣了一下。",
        "你和{npc}多聊了几句，聊的都是废话，但你回想起来还挺开心。",
        "你和{npc}一起吃了顿饭。散场时谁都没提「下次」，但都知道会有下次。",
        "和{npc}的消息聊到了半夜，明明第二天都要早起。",
        "你把想说的话说了。心跳得厉害，但说完那一刻反而轻松了。",
    ],
    "cold": [
        "嗓子有点发紧，你灌了杯热水，没当回事。",
        "半夜烧起来了，你翻出退烧药，就着凉水吞了下去。",
        "整个人像被抽空，躺了一天，连手机都不想看。",
        "烧退了，人还是虚。喝粥的时候觉得米汤都是甜的。",
        "终于好利索了。你出门走了两圈，觉得空气都比平时清楚。",
    ],
    "fitness": [
        "你办了张健身卡，销售说的话你一句没信，卡还是办了。",
        "第三次去健身房，你已经能面不改色地走过器械区了。",
        "今天又没去。你把这事在心里合理化了三遍。",
        "隔了半个月，你重新去了一趟。教练居然还记得你的名字。",
        "不知不觉练成了习惯，不去反而浑身不对劲。",
    ],
    "jobhunt": [
        "你把简历翻出来改了改，改完又存成了「新建文档(3)」。",
        "投了几家。投完就把招聘软件卸载了，两小时后又装了回来。",
        "接到了面试邀请。你请了半天假，跟{npc}说是去看牙。",
        "面完了，对方说「再联系」。你反复琢磨这三个字的含义。",
        "有结果了。无论好坏，悬着的心总算落了地。",
    ],
    "family": [
        "{npc}打来电话，说家里都好，你却听出话里有别的意思。",
        "一整天心里都惦记着家里的事，做什么都走神。",
        "你决定回去一趟，订了周末的票。",
        "回了趟家。饭桌上谁都没提那件事，但你知道大家都在想。",
        "回来以后心里踏实了些。有些事说不清，但见一面就是不一样。",
    ],
    "hobby": [
        "你下单了一套工具，收货那天像拆生日礼物。",
        "第一次动手，做出来的东西丑得很有个性。",
        "练了几次，居然有点样子了。你拍了照，没发出去。",
        "你做成了一个能拿得出手的东西，摆在桌上看了很久。",
    ],
    "conflict": [
        "和{npc}因为一件小事呛了几句，话赶话，谁都没让。",
        "和{npc}还僵着。今天照面时都装作在看手机。",
        "{npc}主动找你说了句无关的话。台阶递过来了。",
        "你们把话说开了，其实都是些误会。松快了不少。",
    ],
    "move": [
        "房东通知涨租。你把消息看了三遍，回了个「好的」。",
        "开始看房。中介带你看的第一间，采光好得像样板间，价格也是。",
        "定下来了。签合同的时候手有点抖，还是签了。",
        "打包的时候才发现自己有这么多东西，也有这么多可以扔。",
        "搬完了。新家的第一晚，你在陌生的天花板下躺了很久。",
    ],
}

# 可复用的人物池：按关系类型，名字取常见姓氏 + 称呼
NPC_POOL = {
    "colleague": ["老陈", "小林", "阿伟", "张姐", "老王", "小周"],
    "friend": ["阿哲", "大鹏", "小雅", "老孟", "阿May", "胖子"],
    "family": ["妈", "爸", "姐", "哥", "妹妹"],
    "partner": ["Ta"],
    "neighbor": ["楼下阿姨", "对门大哥", "便利店老板"],
}


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


class DaySim(object):
    """逐日模拟器。状态可 JSON 序列化，方便在前后端之间来回传。"""

    # ------------------------------------------------------------------
    @staticmethod
    def new_state(profile, start_year=2026, start_month=4, start_day=8):
        """从心理侧写建立第 0 天的状态。"""
        b5 = profile["big_five"]
        age = profile.get("age", 25)
        employed = not (age < 23 and profile.get("education_level", 1) >= 3)
        return {
            "day_index": 0,
            "year": start_year, "month": start_month, "date": start_day,
            "weekday": 2,                       # 从周三开始，日子不那么整齐
            "weather": "多云",
            "energy": 70, "mood": profile_mood(profile),
            "stress": 30 + max(0, b5["neuroticism"] - 50) // 2,
            "health": _clamp(95 - max(0, age - 30)),
            "money": 60,                        # 相对值，不是具体金额
            "age": age,
            "employed": employed,
            "in_school": not employed,
            "partnered": profile.get("married", False),
            "threads": [],
            "npcs": {},
            "recent": [],                       # 最近几天的摘要
            "flags": [],                        # 已确立的事实
            "streaks": {"overtime": 0, "early": 0, "lonely": 0, "goodsleep": 0},
            "slept_late": False,
            "recent_used": [],   # 最近几天用过的模板，避免连着几天重样
        }

    # ------------------------------------------------------------------
    def __init__(self, profile, state, seed_text=""):
        self.p = profile
        self.s = state
        b5 = profile["big_five"]
        self.O, self.C = b5["openness"], b5["conscientiousness"]
        self.E, self.A = b5["extraversion"], b5["agreeableness"]
        self.N = b5["neuroticism"]
        self.values = profile.get("values", {})
        digest = hashlib.sha256(
            ("%s#day%d" % (seed_text, state["day_index"])).encode("utf-8")
        ).hexdigest()
        self.rng = random.Random(int(digest[:16], 16))
        self.templates = load_templates()

    # ------------------------------------------------------------------
    def chance(self, p):
        return self.rng.random() < p

    def trait(self, score, strength=0.1):
        return max(0.1, 1.0 + (score - 50) / 10.0 * strength)

    # ------------------------------------------------------------------
    def npc(self, kind):
        """取一个该类关系的人。已认识的优先复现——这就是"记忆"。"""
        known = [name for name, info in self.s["npcs"].items()
                 if info.get("kind") == kind]
        if known and self.chance(0.75):
            name = self.rng.choice(sorted(known))
        else:
            pool = [n for n in NPC_POOL.get(kind, ["某人"])
                    if n not in self.s["npcs"]]
            name = self.rng.choice(sorted(pool)) if pool else \
                (self.rng.choice(sorted(known)) if known else "某人")
        info = self.s["npcs"].setdefault(
            name, {"kind": kind, "closeness": 50, "last_seen": -99, "met": 0})
        info["last_seen"] = self.s["day_index"]
        info["met"] += 1
        return name

    # ------------------------------------------------------------------
    def advance_calendar(self):
        s = self.s
        days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        s["date"] += 1
        if s["date"] > days_in_month[s["month"] - 1]:
            s["date"] = 1
            s["month"] += 1
            if s["month"] > 12:
                s["month"] = 1
                s["year"] += 1
        s["weekday"] = (s["weekday"] + 1) % 7
        s["day_index"] += 1

    def season(self):
        for months, name in SEASONS.items():
            if self.s["month"] in months:
                return name
        return "春"

    def roll_weather(self):
        """天气有惯性：七成概率延续昨天的倾向。"""
        pool = WEATHER_BY_SEASON[self.season()]
        if self.s["weather"] in pool and self.chance(0.45):
            return self.s["weather"]
        return self.rng.choice(pool)

    def is_rest_day(self):
        return self.s["weekday"] >= 5

    # ------------------------------------------------------------------
    # 剧情线
    # ------------------------------------------------------------------
    def maybe_start_thread(self):
        """按状态与性格开一条新的故事线。同时最多三条，免得太乱。"""
        if len([t for t in self.s["threads"] if t["stage"] >= 0]) >= 3:
            return None
        for kind, spec in sorted(THREAD_KINDS.items()):
            if any(t["kind"] == kind for t in self.s["threads"]):
                continue
            gate = spec["start_when"]
            if gate == "employed" and not self.s["employed"]:
                continue
            if gate == "single" and self.s["partnered"]:
                continue
            p = spec["base_chance"]
            if kind == "hobby":
                p *= self.trait(self.O, 0.15)
            elif kind == "fitness":
                p *= self.trait(self.C, 0.12)
            elif kind == "crush":
                p *= self.trait(self.E, 0.12)
            elif kind == "conflict":
                p *= self.trait(100 - self.A, 0.12)
            elif kind == "cold":
                p *= 1.0 + max(0, self.s["stress"] - 50) / 100.0
            elif kind == "jobhunt":
                p *= 1.0 + max(0, self.s["stress"] - 55) / 60.0
            if self.chance(p):
                thread = {"kind": kind, "stage": 0,
                          "started": self.s["day_index"],
                          "npc": None, "last_advance": self.s["day_index"]}
                if kind in ("project", "jobhunt", "conflict"):
                    thread["npc"] = self.npc("colleague")
                elif kind == "crush":
                    thread["npc"] = self.npc("colleague" if self.chance(0.5)
                                             else "friend")
                elif kind == "family":
                    thread["npc"] = self.npc("family")
                self.s["threads"].append(thread)
                return thread
        return None

    def advance_threads(self, day):
        """推进剧情线，产出当天与之相关的叙述。"""
        finished = []
        for t in self.s["threads"]:
            spec = THREAD_KINDS[t["kind"]]
            texts = THREAD_TEXTS[t["kind"]]
            # 刚开始的那一天必定叙述一次
            just_started = t["started"] == self.s["day_index"]
            gap = self.s["day_index"] - t["last_advance"]
            advance = just_started or (gap >= 1 and self.chance(spec["advance"]))
            if not advance:
                continue
            idx = min(t["stage"], len(texts) - 1)
            text = texts[idx].replace("{npc}", t.get("npc") or "对方")
            slot = self._thread_slot(t["kind"], idx)
            day["slots"][slot].append({"text": text, "thread": t["kind"]})
            day["threads"].append({
                "kind": t["kind"], "title": spec["title"],
                "stage": idx + 1, "total": len(texts),
                "stage_name": spec["stages"][min(idx, len(spec["stages"]) - 1)],
            })
            self._thread_effects(t["kind"], idx)
            if not just_started:
                t["last_advance"] = self.s["day_index"]
            t["stage"] = idx + 1
            if t["stage"] >= len(texts):
                finished.append(t)
        for t in finished:
            self.s["threads"].remove(t)
            self.s["flags"].append("done:" + t["kind"])
        return day

    def _thread_slot(self, kind, stage):
        """不同剧情线发生在不同时段，让一天有节奏。"""
        table = {
            "project": ["morning", "afternoon", "afternoon", "night",
                        "afternoon", "morning"],
            "crush": ["morning", "noon", "evening", "night", "evening"],
            "cold": ["dawn", "night", "afternoon", "dawn", "morning"],
            "fitness": ["evening", "evening", "night", "evening", "dawn"],
            "jobhunt": ["night", "night", "morning", "afternoon", "morning"],
            "family": ["evening", "noon", "night", "afternoon", "night"],
            "hobby": ["evening", "evening", "night", "evening"],
            "conflict": ["morning", "noon", "afternoon", "evening"],
            "move": ["evening", "afternoon", "evening", "night", "night"],
        }
        seq = table.get(kind, ["afternoon"])
        return seq[min(stage, len(seq) - 1)]

    def _thread_effects(self, kind, stage):
        s = self.s
        if kind == "project":
            if stage == 3:      # 赶工
                s["stress"] = _clamp(s["stress"] + 10)
                s["energy"] = _clamp(s["energy"] - 15)
                s["streaks"]["overtime"] += 1
            elif stage == 4:    # 交付
                s["stress"] = _clamp(s["stress"] - 15)
                s["mood"] = _clamp(s["mood"] + 8)
        elif kind == "cold":
            if stage <= 2:
                s["health"] = _clamp(s["health"] - 6)
                s["energy"] = _clamp(s["energy"] - 20)
                s["mood"] = _clamp(s["mood"] - 5)
            else:
                s["health"] = _clamp(s["health"] + 5)
        elif kind == "crush":
            s["mood"] = _clamp(s["mood"] + 6)
            if stage == 4:
                s["partnered"] = True
                s["flags"].append("in_relationship")
        elif kind == "fitness":
            if stage in (1, 4):
                s["health"] = _clamp(s["health"] + 3)
                s["mood"] = _clamp(s["mood"] + 3)
        elif kind == "conflict":
            if stage <= 1:
                s["mood"] = _clamp(s["mood"] - 6)
                s["stress"] = _clamp(s["stress"] + 5)
            else:
                s["mood"] = _clamp(s["mood"] + 6)
        elif kind == "family":
            if stage <= 1:
                s["stress"] = _clamp(s["stress"] + 6)
            else:
                s["mood"] = _clamp(s["mood"] + 4)
        elif kind == "move":
            if stage >= 3:
                s["energy"] = _clamp(s["energy"] - 12)
                s["money"] = _clamp(s["money"] - 10)

    # ------------------------------------------------------------------
    # 日常事件
    # ------------------------------------------------------------------
    def pick_template(self, slot, day):
        """按时段挑一条日常事件，考虑状态与性格。"""
        pool = []
        for tpl in self.templates.get(slot, []):
            if not self._template_fits(tpl):
                continue
            w = float(tpl.get("weight", 1.0))
            for key, bias in (tpl.get("trait_bias") or {}).items():
                score = {"O": self.O, "C": self.C, "E": self.E,
                         "A": self.A, "N": self.N}.get(key, 50)
                w *= max(0.05, 1.0 + (score - 50) / 50.0 * bias)
            if tpl.get("id") in day["_used"]:
                continue
            # 最近几天出现过的，权重压到很低——不是禁用，是让它不容易再抽到
            if tpl.get("id") in self.s.get("recent_used", []):
                w *= 0.12
            pool.append((tpl, w))
        if not pool:
            return None
        tpls = [t for t, _w in pool]
        weights = [w for _t, w in pool]
        return self.rng.choices(tpls, weights=weights, k=1)[0]

    def _template_fits(self, tpl):
        s = self.s
        need = tpl.get("requires") or {}
        if "rest_day" in need and bool(need["rest_day"]) != self.is_rest_day():
            return False
        if "employed" in need and bool(need["employed"]) != s["employed"]:
            return False
        if "partnered" in need and bool(need["partnered"]) != s["partnered"]:
            return False
        if "min_age" in need and s["age"] < need["min_age"]:
            return False
        if "max_age" in need and s["age"] > need["max_age"]:
            return False
        if "energy_below" in need and s["energy"] >= need["energy_below"]:
            return False
        if "energy_above" in need and s["energy"] <= need["energy_above"]:
            return False
        if "stress_above" in need and s["stress"] <= need["stress_above"]:
            return False
        if "mood_below" in need and s["mood"] >= need["mood_below"]:
            return False
        if "season" in need and need["season"] != self.season():
            return False
        if "weather" in need and need["weather"] not in s["weather"]:
            return False
        return True

    def render(self, tpl):
        """填充模板里的占位符，并记录人物。"""
        text = tpl["text"]
        for kind in ("colleague", "friend", "family", "neighbor"):
            token = "{%s}" % kind
            while token in text:
                text = text.replace(token, self.npc(kind), 1)
        if "{partner}" in text:
            text = text.replace("{partner}", self.npc("partner"))
        return text

    def apply_effects(self, tpl):
        """把事件的影响加到状态上，并按人格调制情绪反应。

        主观幸福感研究里的两个稳定结论：外向者从积极事件中获得的
        正性情绪更多，而高神经质者对消极事件的反应更强。同一件好事，
        不同的人心情涨幅不一样——这正是"像他本人"的一部分。
        """
        s = self.s
        for key, delta in (tpl.get("effects") or {}).items():
            if key not in ("energy", "mood", "stress", "health", "money"):
                continue
            if key == "mood":
                if delta > 0:
                    delta *= self.trait(self.E, 0.06)
                else:
                    delta *= self.trait(self.N, 0.06)
            elif key == "stress" and delta > 0:
                delta *= self.trait(self.N, 0.05)
            s[key] = _clamp(s[key] + int(round(delta)))
        for flag in tpl.get("set_flags") or []:
            if flag not in s["flags"]:
                s["flags"].append(flag)

    # ------------------------------------------------------------------
    # 记忆回指：让今天的叙述提到昨天
    # ------------------------------------------------------------------
    def carryover_lines(self, day):
        s = self.s
        lines = []
        if s.get("slept_late"):
            lines.append(("dawn", "昨晚睡得太晚，闹钟响了三遍你才挣扎着坐起来。"))
            s["energy"] = _clamp(s["energy"] - 10)
        if s["streaks"]["overtime"] >= 3:
            lines.append(("morning",
                          "连着加了几天班，你端着咖啡的手都有点抖。"))
            s["health"] = _clamp(s["health"] - 3)
        if s["streaks"]["early"] >= 4:
            lines.append(("dawn", "连续早起到第%d天，你发现天亮的时间在慢慢变早。"
                          % s["streaks"]["early"]))
        if s["energy"] < 30:
            lines.append(("afternoon", "整个下午你都在和困意搏斗，效率低得可怕。"))
        if s["stress"] > 75 and self.N > 55:
            lines.append(("night", "躺下之后脑子反而清醒，那些没做完的事一件件浮上来。"))
            s["mood"] = _clamp(s["mood"] - 4)
        # 很久没见的人会被想起——这是"人物记忆"的一部分
        for name, info in sorted(s["npcs"].items()):
            gap = s["day_index"] - info.get("last_seen", 0)
            if gap > 20 and info.get("met", 0) >= 2 and self.chance(0.12):
                lines.append(("night", "你忽然想起好久没联系%s了，翻到聊天框却没发出消息。" % name))
                info["last_seen"] = s["day_index"]
                break
        return lines

    # ------------------------------------------------------------------
    def simulate_day(self):
        """生成一整天。返回可直接展示的 dict。"""
        self.advance_calendar()
        s = self.s
        s["weather"] = self.roll_weather()

        day = {
            "day_index": s["day_index"],
            "date_text": "%d年%d月%d日 %s" % (
                s["year"], s["month"], s["date"], WEEKDAY_NAMES[s["weekday"]]),
            "weather": s["weather"],
            "season": self.season(),
            "is_rest_day": self.is_rest_day(),
            "slots": {key: [] for key, _name in SLOTS},
            "threads": [],
            "_used": set(),
            "_used_ids": [],
        }

        # 1. 昨天的余波（记忆回指）
        for slot, text in self.carryover_lines(day):
            day["slots"][slot].append({"text": text, "carryover": True})

        # 2. 剧情线：先看有没有新线开启，再推进已有的
        self.maybe_start_thread()
        self.advance_threads(day)

        # 3. 日常事件：按时段填充，休息日和工作日的密度不同
        counts = {
            "dawn": 1, "morning": 2, "noon": 1,
            "afternoon": 2, "evening": 2, "night": 2,
        }
        if self.is_rest_day():
            counts.update({"morning": 1, "afternoon": 2, "evening": 2})
        if s["energy"] < 25:
            counts = {k: max(1, v - 1) for k, v in counts.items()}

        for slot_key, _slot_name in SLOTS:
            need = counts[slot_key] - len(day["slots"][slot_key])
            for _ in range(max(0, need)):
                tpl = self.pick_template(slot_key, day)
                if not tpl:
                    break
                day["_used"].add(tpl.get("id"))
                day["_used_ids"].append(tpl.get("id"))
                day["slots"][slot_key].append({"text": self.render(tpl)})
                self.apply_effects(tpl)

        # 4. 一天结束：状态结转
        self.end_of_day(day)

        # 5. 整理成展示结构
        out_slots = []
        for key, name in SLOTS:
            entries = day["slots"][key]
            if entries:
                out_slots.append({"key": key, "name": name,
                                  "entries": [e["text"] for e in entries]})
        day["slots"] = out_slots
        day.pop("_used", None)
        day.pop("_used_ids", None)
        day["state"] = {
            "energy": int(s["energy"]), "mood": int(s["mood"]),
            "stress": int(s["stress"]), "health": int(round(s["health"])),
            "money": int(s["money"]),
        }
        day["active_threads"] = [
            {"title": THREAD_KINDS[t["kind"]]["title"],
             "stage_name": THREAD_KINDS[t["kind"]]["stages"][
                 min(t["stage"], len(THREAD_KINDS[t["kind"]]["stages"]) - 1)],
             "stage": t["stage"], "total": len(THREAD_TEXTS[t["kind"]])}
            for t in s["threads"]]
        day["known_people"] = sorted(
            [{"name": n, "met": i["met"],
              "days_since": s["day_index"] - i["last_seen"]}
             for n, i in s["npcs"].items()],
            key=lambda x: (x["days_since"], x["name"]))[:6]
        return day

    def end_of_day(self, day):
        s = self.s
        # 精力恢复取决于是否熬夜、压力、休息日
        night_texts = " ".join(e["text"] for e in
                               [x for x in day["slots"]["night"]])
        s["slept_late"] = ("熬" in night_texts or "半夜" in night_texts
                           or "睡不着" in night_texts or "两点" in night_texts)
        # 睡一觉恢复精力，恢复量与"亏空"成正比：越累的时候一觉睡醒
        # 补得越多，本来就精神时睡一觉也涨不了几分。加上压力、熬夜、
        # 健康的折扣，精力就成了一条真正会起伏的曲线。
        deficit = 100 - s["energy"]
        recover = deficit * (0.62 if self.is_rest_day() else 0.45)
        recover -= max(0, s["stress"] - 45) / 3.0
        recover -= max(0, 70 - s["health"]) / 6.0
        if s["slept_late"]:
            recover -= 14
        # 工作日累积疲惫：一周越往后越难满血
        if not self.is_rest_day():
            recover -= s["weekday"] * 1.2
        ceiling = 94 - max(0, s["stress"] - 50) // 2
        s["energy"] = _clamp(min(int(s["energy"] + recover), ceiling))
        # 压力与心情都向**人格决定的基线**回归，而不是回归到零。
        # 一个高神经质的人即使今天很顺，压力也不会真的归零——这正是
        # "内耗"的含义：基线本身就高。
        stress_base = _clamp(28 + (self.N - 50) * 0.45 - (self.C - 50) * 0.1)
        s["stress"] = _clamp(int(s["stress"] * 0.78 + stress_base * 0.22))
        if not self.is_rest_day() and self.s["employed"]:
            s["stress"] = _clamp(s["stress"] + 2)

        # 心情向基线回归的力度要够大，否则一连串小确幸会把它顶到天花板，
        # 而现实里人对好事会迅速适应（享乐适应）。
        mood_base = 55 - (self.N - 50) * 0.3 + (self.E - 50) * 0.12
        s["mood"] = _clamp(int(s["mood"] * 0.58 + mood_base * 0.42))

        # 健康随长期状态缓慢漂移：压力大、睡不好会一点点耗掉它
        drift = 0.0
        if s["stress"] > 60:
            drift -= 0.5
        if s["slept_late"]:
            drift -= 0.3
        if s["energy"] > 70 and s["stress"] < 45:
            drift += 0.4
        if s["age"] > 40:
            drift -= 0.1
        s["health"] = _clamp(round(s["health"] + drift, 1), 0, 100)
        if not s["employed"]:
            s["money"] = _clamp(s["money"] - 1)
        elif self.is_rest_day():
            s["money"] = _clamp(s["money"] - 2)
        else:
            s["money"] = _clamp(s["money"] + 1)

        # 连续计数
        if s["streaks"]["overtime"] and not any(
                "加班" in e["text"] or "留到" in e["text"]
                for e in day["slots"]["night"] + day["slots"]["evening"]):
            s["streaks"]["overtime"] = 0
        if any("早起" in e["text"] or "六点" in e["text"]
               for e in day["slots"]["dawn"]):
            s["streaks"]["early"] += 1
        else:
            s["streaks"]["early"] = 0

        # 生日
        if s["month"] == 4 and s["date"] == 8 and s["day_index"] > 0:
            s["age"] += 1

        # 近期用过的模板：记最近三天左右的量，让内容不至于连着重样
        s["recent_used"] = (s.get("recent_used", []) + sorted(day["_used_ids"]))[-28:]

        # 近期记忆：留最近 5 天
        summary = self.day_summary(day)
        day["summary"] = summary
        s["recent"].append({"day": s["day_index"], "summary": summary})
        s["recent"] = s["recent"][-5:]

    def day_summary(self, day):
        """一句话总结这一天，用于近期记忆与列表展示。"""
        s = self.s
        if day["threads"]:
            kind = day["threads"][-1]["title"]
            return "%s有了进展。" % kind
        if s["energy"] < 30:
            return "累得像被抽干的一天。"
        if s["mood"] >= 70:
            return "心情不错的一天。"
        if s["mood"] <= 35:
            return "有点低落的一天。"
        if self.is_rest_day():
            return "松散但不算浪费的一天。"
        return "平平常常的一天。"


# ---------------------------------------------------------------------------
# 对外便捷函数
# ---------------------------------------------------------------------------

def profile_mood(profile):
    b5 = profile["big_five"]
    return _clamp(int(58 - (b5["neuroticism"] - 50) * 0.3
                      + (b5["extraversion"] - 50) * 0.12))


def start(profile, start_year=2026):
    """开始逐日模拟，返回初始状态。"""
    return DaySim.new_state(profile, start_year=start_year)


def next_day(profile, state, seed_text=""):
    """生成下一天。返回 (这一天, 新状态)。"""
    sim = DaySim(profile, state, seed_text=seed_text)
    day = sim.simulate_day()
    return day, sim.s
