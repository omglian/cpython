# -*- coding: utf-8 -*-
"""人生模拟引擎：基于心理侧写，逐年推演一段"符合逻辑"的人生。

设计原则：

* 真实感 —— 事件概率参考现实规律（如死亡率随年龄指数上升的
  Gompertz 曲线、25~33 岁的结婚高峰、40 岁后健康缓慢下滑）。
* 因果逻辑 —— 每个重大事件都有前置条件和由状态推出的概率，
  叙事中同时给出"为什么"（哪个特质、哪条处境导致了它）。
* 像他本人 —— 所有概率被大五人格、价值观、依恋风格调制；
  人生岔路口(决策点)由侧写自动做出选择，而不是掷硬币。
* 可复现 —— 随机数种子取自经历文本的哈希：同一段人生经历
  重演出同一条人生轨迹；换个种子即可看平行世界。

特质对概率的调制统一通过 _trait_factor 完成：
特质分 50 为中性(乘数 1.0)，每偏离 10 分乘数变化约 strength。
"""

import hashlib
import random


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _trait_factor(score, strength=0.10):
    """把 0~100 的特质分转换为概率乘数。50 → 1.0。

    strength=0.10 表示特质每偏离 10 分，概率乘数变化约 10%。
    """
    return max(0.1, 1.0 + (score - 50) / 10.0 * strength)


def _clamp(value, low, high):
    return max(low, min(high, value))


class _Narrator:
    """把事件积累成逐年文字记录。"""

    def __init__(self):
        self.timeline = []       # [{year, age, events: [str]}]
        self.turning_points = []  # 重大转折点摘要

    def log(self, year, age, text, turning=False):
        if not self.timeline or self.timeline[-1]["age"] != age:
            self.timeline.append({"year": year, "age": age, "events": []})
        self.timeline[-1]["events"].append(text)
        if turning:
            self.turning_points.append("%d岁：%s" % (age, text))


# ---------------------------------------------------------------------------
# 模拟主体
# ---------------------------------------------------------------------------

class LifeSimulation:

    def __init__(self, profile, seed_text="", seed_offset=0,
                 start_year=2026):
        self.p = profile
        digest = hashlib.sha256(
            (seed_text + "#%d" % seed_offset).encode("utf-8")
        ).hexdigest()
        self.rng = random.Random(int(digest[:16], 16))
        self.start_year = start_year
        self.n = _Narrator()

        b5 = profile["big_five"]
        self.O = b5["openness"]
        self.C = b5["conscientiousness"]
        self.E = b5["extraversion"]
        self.A = b5["agreeableness"]
        self.N = b5["neuroticism"]
        self.values = profile.get("values", {})
        self.attachment = profile.get("attachment", "secure")

        # ----- 初始状态（由侧写抽取的事实决定起点） -----
        self.age = profile.get("age", 25)
        self.alive = True
        self.death_cause = None
        edu = profile.get("education_level", 1)
        self.education = edu
        self.in_school = self.age < (16 + max(edu, 1) * 2) and self.age < 28
        self.career = "student" if self.in_school else "employed"
        if profile.get("entrepreneur"):
            self.career = "entrepreneur"
        self.job_level = _clamp((self.age - 22) // 5, 0, 3)
        self.income = 0 if self.in_school else 60 + edu * 25 + self.job_level * 40
        self.wealth = max(0, (self.age - 22) * 15)
        self.married = profile.get("married", False)
        self.in_relationship = self.married
        self.children = 1 if profile.get("has_children") else 0
        self.health = _clamp(95 - max(0, self.age - 30), 40, 100)
        self.happiness = 60
        self.stress = 30 + max(0, self.N - 50) // 2
        self.owns_home = self.age > 32 and self.values.get("security", 0) > 20
        self.burnout_years = 0

    # ------------------------------------------------------------------
    def choose(self, prob):
        return self.rng.random() < prob

    def run(self, max_years=100):
        year = self.start_year
        while self.alive and self.age < 100 and year - self.start_year < max_years:
            self.step_year(year)
            year += 1
            self.age += 1
        return self.summary()

    # ------------------------------------------------------------------
    def step_year(self, year):
        self.tick_health(year)
        if not self.alive:
            return
        if self.in_school:
            self.tick_school(year)
        elif self.career != "retired":
            self.tick_career(year)
        self.tick_relationships(year)
        self.tick_finance(year)
        self.tick_wellbeing(year)
        self.tick_random_events(year)

    # ------------------------------------------------------------------
    # 健康与死亡：Gompertz 式死亡率 + 特质修正
    # ------------------------------------------------------------------
    def tick_health(self, year):
        base_decline = 0.3 if self.age < 40 else (self.age - 30) * 0.06
        # 尽责性高→自我照顾好；神经质高→慢性压力损耗
        decline = base_decline * _trait_factor(100 - self.C, 0.06) \
            * _trait_factor(self.N, 0.04)
        decline += self.stress * 0.01
        self.health = _clamp(self.health - decline, 0, 100)

        # Gompertz 式死亡率：约 30 岁后每年递增 10%，健康状况整体缩放。
        # 参数校准到平均寿命 ~80 岁、90+ 岁明显稀少的现实分布。
        p_death = 0.0003 * (1.10 ** max(0, self.age - 30))
        p_death *= (1.6 - self.health / 100.0)
        if self.choose(p_death):
            self.alive = False
            self.death_cause = "疾病" if self.age > 55 else "意外"
            self.n.log(year, self.age,
                       "生命走到了终点（%s）。" % self.death_cause, turning=True)
            return

        if self.health < 35 and self.choose(0.25):
            self.n.log(year, self.age,
                       "一场大病让你住院了。长期透支的身体发出了警告。",
                       turning=True)
            self.health = _clamp(self.health + 10, 0, 100)
            self.stress = _clamp(self.stress - 10, 0, 100)
            if self.career == "employed" and self.choose(0.3):
                self.n.log(year, self.age, "病后你开始重新审视工作与生活的平衡。")

    # ------------------------------------------------------------------
    # 学生阶段
    # ------------------------------------------------------------------
    def tick_school(self, year):
        grad_age = 16 + max(self.education, 1) * 2
        if self.age >= grad_age or self.age >= 28:
            self.in_school = False
            self.career = "employed"
            self.job_level = 0
            self.income = 60 + self.education * 25
            self.n.log(year, self.age, "你完成了学业，正式步入社会。", turning=True)
            # 决策点：继续深造？由尽责性+开放性+成就价值观决定
            if self.education == 3 and self.age < 24:
                p_grad = 0.15 * _trait_factor(self.C, 0.15) \
                    * _trait_factor(self.O, 0.10) \
                    * (1 + self.values.get("achievement", 0) / 60.0)
                if self.choose(p_grad):
                    self.education = 4
                    self.in_school = True
                    self.career = "student"
                    self.income = 0
                    self.n.log(year, self.age,
                               "凭着高尽责性(%d)和对深造的执念，你决定继续读研。"
                               % self.C, turning=True)
        else:
            if self.choose(0.3 * _trait_factor(self.O, 0.1)):
                self.n.log(year, self.age, "校园里的一年：你在课业之外探索着自己的兴趣。")

    # ------------------------------------------------------------------
    # 职业阶段
    # ------------------------------------------------------------------
    def tick_career(self, year):
        if self.age >= 62 and self.career != "retired":
            self.career = "retired"
            self.n.log(year, self.age, "你退休了，开始了人生的新阶段。", turning=True)
            return

        if self.career == "employed":
            # 晋升：尽责性是最强预测因子(工业组织心理学的稳定结论)
            p_promo = 0.12 * _trait_factor(self.C, 0.15) \
                * _trait_factor(self.E, 0.06)
            if self.job_level < 5 and self.choose(p_promo):
                self.job_level += 1
                self.income = int(self.income * 1.3)
                self.n.log(year, self.age,
                           "你升职了（第%d级）。多年的%s让上级看到了你。"
                           % (self.job_level,
                              "踏实尽责" if self.C >= 50 else "临场发挥"))
                self.happiness = _clamp(self.happiness + 5, 0, 100)

            # 裁员/失业风险
            p_layoff = 0.03 * _trait_factor(100 - self.C, 0.08)
            if self.choose(p_layoff):
                self.career = "unemployed"
                self.n.log(year, self.age,
                           "行业波动，你被裁员了。", turning=True)
                self.stress = _clamp(self.stress + 20, 0, 100)
                return

            # 决策点：跳槽或转行？开放性驱动
            p_switch = 0.06 * _trait_factor(self.O, 0.15) \
                * (1 + self.values.get("self_direction", 0) / 80.0)
            if self.stress > 60:
                p_switch *= 1.6
            if self.choose(p_switch):
                if self.choose(0.3 * _trait_factor(self.O, 0.2)):
                    self.n.log(year, self.age,
                               "高开放性(%d)让你做出了旁人意外的决定：转行进入一个全新领域。"
                               % self.O, turning=True)
                    self.income = int(self.income * 0.85)
                    self.job_level = max(0, self.job_level - 1)
                else:
                    self.income = int(self.income * 1.15)
                    self.n.log(year, self.age, "你跳槽到了一家新公司，薪资上了一个台阶。")
                self.stress = _clamp(self.stress - 15, 0, 100)

            # 决策点：辞职创业？开放性+外向性+自主价值观，安全价值观抑制
            p_startup = 0.015 * _trait_factor(self.O, 0.12) \
                * _trait_factor(self.E, 0.08) \
                * (1 + self.values.get("self_direction", 0) / 60.0) \
                / (1 + self.values.get("security", 0) / 50.0)
            if self.wealth > 100 and self.age < 45 and self.choose(p_startup):
                self.career = "entrepreneur"
                self.income = int(self.income * 0.5)
                self.n.log(year, self.age,
                           "你辞职创业了。对自主的渴望压过了对安稳的留恋。",
                           turning=True)

        elif self.career == "unemployed":
            p_rehire = 0.55 * _trait_factor(self.C, 0.08) \
                * _trait_factor(self.E, 0.08)
            if self.choose(p_rehire):
                self.career = "employed"
                self.income = int(max(self.income * 0.9, 50))
                self.n.log(year, self.age, "经过一段低谷，你找到了新工作。")
                self.stress = _clamp(self.stress - 15, 0, 100)
            else:
                self.n.log(year, self.age, "求职的一年并不顺利，积蓄在慢慢消耗。")
                self.wealth = max(0, self.wealth - 30)
                self.stress = _clamp(self.stress + 10, 0, 100)

        elif self.career == "entrepreneur":
            roll = self.rng.random()
            grind = _trait_factor(self.C, 0.10)
            if roll < 0.12 * grind:
                self.income = int(self.income * 2.2)
                self.n.log(year, self.age,
                           "创业迎来爆发的一年，业务翻了一番还多。", turning=True)
                self.happiness = _clamp(self.happiness + 8, 0, 100)
            elif roll > 0.88 / grind:
                self.n.log(year, self.age,
                           "创业失败了。你关掉了公司，回到职场。", turning=True)
                self.career = "employed"
                self.income = 80 + self.education * 20
                self.wealth = max(0, self.wealth - 80)
                self.stress = _clamp(self.stress + 15, 0, 100)
            else:
                self.income = int(self.income * (0.95 + self.rng.random() * 0.25))
                self.n.log(year, self.age, "创业维艰的一年，起起伏伏但还撑着。")
                self.stress = _clamp(self.stress + 5, 0, 100)

    # ------------------------------------------------------------------
    # 感情与家庭
    # ------------------------------------------------------------------
    def tick_relationships(self, year):
        if not self.in_relationship and 18 <= self.age <= 70:
            # 结婚高峰曲线：25~33 岁概率最高
            peak = max(0.0, 1.0 - abs(self.age - 29) / 20.0)
            p_meet = 0.18 * peak * _trait_factor(self.E, 0.10)
            if self.attachment == "avoidant":
                p_meet *= 0.55
            if self.choose(p_meet):
                self.in_relationship = True
                how = "朋友聚会上" if self.E >= 50 else "一个共同的小圈子里"
                self.n.log(year, self.age, "你在%s遇到了让你心动的人，开始了一段感情。" % how)
                self.happiness = _clamp(self.happiness + 8, 0, 100)

        elif self.in_relationship and not self.married:
            # 分手风险：焦虑型依恋与高神经质增加冲突
            p_break = 0.15 * _trait_factor(self.N, 0.08) \
                / _trait_factor(self.A, 0.06)
            if self.attachment == "anxious":
                p_break *= 1.5
            elif self.attachment == "secure":
                p_break *= 0.6
            if self.choose(p_break):
                self.in_relationship = False
                reason = {
                    "anxious": "反复的患得患失最终耗尽了两个人",
                    "avoidant": "你始终没能真正敞开自己",
                    "secure": "你们和平地发现彼此并不合适",
                }[self.attachment]
                self.n.log(year, self.age, "这段感情结束了——%s。" % reason)
                self.happiness = _clamp(self.happiness - 10, 0, 100)
                self.stress = _clamp(self.stress + 8, 0, 100)
            else:
                p_marry = 0.30 if 24 <= self.age <= 38 else 0.12
                p_marry *= _trait_factor(self.A, 0.05)
                if self.attachment == "secure":
                    p_marry *= 1.3
                if self.choose(p_marry):
                    self.married = True
                    self.n.log(year, self.age, "你们结婚了。", turning=True)
                    self.happiness = _clamp(self.happiness + 12, 0, 100)

        elif self.married:
            # 离婚风险
            p_div = 0.02 * _trait_factor(self.N, 0.10) \
                / _trait_factor(self.A, 0.08)
            if self.attachment != "secure":
                p_div *= 1.4
            if self.stress > 70:
                p_div *= 1.5
            if self.choose(p_div):
                self.married = False
                self.in_relationship = False
                self.n.log(year, self.age,
                           "婚姻走到了尽头，你们离婚了。", turning=True)
                self.happiness = _clamp(self.happiness - 15, 0, 100)
                self.wealth = int(self.wealth * 0.6)
                return
            # 生育
            if self.children < 3 and 22 <= self.age <= 42:
                p_child = 0.22 / (1 + self.children)
                p_child *= (1 + self.values.get("benevolence", 0) / 80.0)
                if self.choose(p_child):
                    self.children += 1
                    self.n.log(year, self.age,
                               "你们的第%d个孩子出生了。" % self.children,
                               turning=True)
                    self.happiness = _clamp(self.happiness + 8, 0, 100)
                    self.stress = _clamp(self.stress + 8, 0, 100)

    # ------------------------------------------------------------------
    # 财务
    # ------------------------------------------------------------------
    def tick_finance(self, year):
        if self.career == "retired":
            pension = int(self.income * 0.5)
            spend = 40 + self.children * 2
            self.wealth = max(0, self.wealth + pension - spend)
            return
        save_rate = 0.15 * _trait_factor(self.C, 0.12)
        if self.values.get("hedonism", 0) > 30:
            save_rate *= 0.6
        spend = 40 + self.children * 15 + (20 if self.owns_home else 30)
        self.wealth = max(0, self.wealth + int(self.income * save_rate)
                          - max(0, spend - self.income))

        # 决策点：买房？安全价值观驱动
        if (not self.owns_home and self.wealth > 250
                and self.values.get("security", 0) > 15
                and self.choose(0.35)):
            self.owns_home = True
            self.wealth = int(self.wealth * 0.35)
            self.n.log(year, self.age,
                       "你掏空积蓄付了首付，买下了自己的房子。对安稳的看重让你觉得值得。",
                       turning=True)
            self.happiness = _clamp(self.happiness + 6, 0, 100)

    # ------------------------------------------------------------------
    # 心理状态
    # ------------------------------------------------------------------
    def tick_wellbeing(self, year):
        base = 50
        base += (self.health - 60) * 0.15
        base += 10 if self.married else (4 if self.in_relationship else -2)
        base += min(self.children, 2) * 2
        base += (self.income - 100) * 0.03
        base += 6 if self.owns_home else 0
        base -= self.stress * 0.15
        # 神经质拉低幸福基线，外向性抬高（主观幸福感研究的经典结论）
        base -= (self.N - 50) * 0.20
        base += (self.E - 50) * 0.10
        # 成就导向抬高欲望水位：收入不够高时反而更不满足
        if self.values.get("achievement", 0) > 30 and self.income < 200:
            base -= 5
        self.happiness = _clamp(int(self.happiness * 0.6 + base * 0.4), 0, 100)

        # 压力自然衰减，尽责性帮助恢复
        self.stress = _clamp(self.stress - 5 - (self.C - 50) // 10, 0, 100)
        if self.career in ("employed", "entrepreneur") and self.job_level >= 3:
            self.stress = _clamp(self.stress + 5, 0, 100)

        # 心理危机：高神经质 + 高压 + 低幸福
        if self.N > 62 and self.stress > 55 and self.happiness < 40:
            self.burnout_years += 1
            if self.burnout_years >= 2 and self.choose(0.4):
                self.n.log(year, self.age,
                           "长期内耗之后，你陷入了一段严重的情绪低谷，开始寻求心理咨询。",
                           turning=True)
                self.stress = _clamp(self.stress - 25, 0, 100)
                self.burnout_years = 0
        else:
            self.burnout_years = 0

        # 中年反思：开放性高的人更可能主动转向
        if self.age in (40, 45) and self.O > 60 and self.happiness < 55:
            self.n.log(year, self.age,
                       "站在人生中场，你认真问自己：现在的生活是我想要的吗？")

    # ------------------------------------------------------------------
    # 低频随机事件
    # ------------------------------------------------------------------
    def tick_random_events(self, year):
        roll = self.rng.random()
        if roll < 0.02 * _trait_factor(self.E, 0.1):
            self.n.log(year, self.age, "一位老朋友重新回到你的生活里，你们聊了整晚。")
            self.happiness = _clamp(self.happiness + 4, 0, 100)
        elif roll > 0.985:
            self.n.log(year, self.age, "家中长辈离世，你回了一趟老家，想了很多。")
            self.happiness = _clamp(self.happiness - 6, 0, 100)
        elif 0.5 < roll < 0.52 and self.O > 55:
            self.n.log(year, self.age, "你捡起了一个搁置多年的爱好，久违地感到纯粹的快乐。")
            self.happiness = _clamp(self.happiness + 5, 0, 100)

    # ------------------------------------------------------------------
    def summary(self):
        return {
            "final_age": self.age,
            "alive": self.alive,
            "death_cause": self.death_cause,
            "lived": "%d 岁" % self.age,
            "career_final": {
                "student": "学生", "employed": "上班族",
                "entrepreneur": "创业者", "unemployed": "待业",
                "retired": "退休",
            }.get(self.career, self.career),
            "married": self.married,
            "children": self.children,
            "owns_home": self.owns_home,
            "wealth": self.wealth,
            "final_happiness": self.happiness,
            "timeline": self.n.timeline,
            "turning_points": self.n.turning_points,
        }


def simulate(profile, seed_text="", seed_offset=0, start_year=2026,
             max_years=100):
    """便捷入口：构建并运行一次完整模拟。"""
    sim = LifeSimulation(profile, seed_text=seed_text,
                         seed_offset=seed_offset, start_year=start_year)
    return sim.run(max_years=max_years)
