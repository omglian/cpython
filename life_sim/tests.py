# -*- coding: utf-8 -*-
"""life_sim 冒烟测试：python3 tests.py 直接运行，全绿即通过。"""

import json
import os
import tempfile
import unittest

from engine import build_profile, simulate
from engine.events import load_corpus, draw
from crawler import distill

STORY_RICH = (
    "我1995年出生在一个小县城，父母都是老师。小时候我很内向，不爱说话，"
    "喜欢一个人看书画画，对什么都好奇。高中时我非常自律，每天早起复习，"
    "按计划刷题，最后高考考上了一所不错的大学，读了计算机专业。"
    "大学里我坚持自学各种新技术，也开始写作，还拿过奖学金。"
    "毕业后我来到大城市工作，经常加班，压力很大，有段时间焦虑失眠，"
    "总是内耗，想太多。我谈过一次恋爱，因为我总是患得患失，害怕被抛弃，"
    "最后分手了。现在我30岁，还是想证明自己，希望事业成功，"
    "但也越来越想要自由，不想被管，甚至想过辞职创业。"
)

STORY_SHORT = "我今年25岁，喜欢打游戏，别的没什么好说的，就是一个普通人而已。"


class TestProfiler(unittest.TestCase):

    def setUp(self):
        self.profile = build_profile(STORY_RICH, current_year=2026)

    def test_scores_in_range(self):
        for dim, score in self.profile["big_five"].items():
            self.assertTrue(0 <= score <= 100, "%s=%s 越界" % (dim, score))

    def test_directional_signals(self):
        b5 = self.profile["big_five"]
        # 内向、看书画画、自律刷题、焦虑内耗 → 方向应正确
        self.assertLess(b5["extraversion"], 50, "内向者外向性应低于均值")
        self.assertGreater(b5["conscientiousness"], 50, "自律者尽责性应高于均值")
        self.assertGreater(b5["openness"], 50, "好奇+自学者开放性应高于均值")
        self.assertGreater(b5["neuroticism"], 50, "焦虑内耗者神经质应高于均值")

    def test_age_extraction(self):
        # 文中"现在我30岁"应被识别
        self.assertEqual(self.profile["age"], 30)

    def test_attachment(self):
        # "患得患失、害怕被抛弃" → 焦虑型依恋
        self.assertEqual(self.profile["attachment"], "anxious")

    def test_facts_extracted(self):
        facts = self.profile["facts"]
        self.assertIn("education", facts)
        self.assertIn("career", facts)
        self.assertIn("romance", facts)

    def test_detail_rewards_length(self):
        short = build_profile(STORY_SHORT, current_year=2026)
        self.assertGreater(self.profile["confidence"], short["confidence"],
                           "写得越详细，置信度应越高")

    def test_extra_overrides(self):
        p = build_profile(STORY_RICH, extra={"age": 42, "gender": "female"},
                          current_year=2026)
        self.assertEqual(p["age"], 42)
        self.assertEqual(p["gender"], "female")


class TestSimulation(unittest.TestCase):

    def setUp(self):
        self.profile = build_profile(STORY_RICH, current_year=2026)

    def test_runs_to_completion(self):
        result = simulate(self.profile, seed_text=STORY_RICH, start_year=2026)
        self.assertGreaterEqual(result["final_age"], self.profile["age"])
        self.assertTrue(result["timeline"], "时间线不应为空")

    def test_deterministic_replay(self):
        # 同一段经历 + 同一种子 → 同一条人生
        a = simulate(self.profile, seed_text=STORY_RICH, start_year=2026)
        b = simulate(self.profile, seed_text=STORY_RICH, start_year=2026)
        self.assertEqual(a, b, "同种子模拟必须可复现")

    def test_parallel_world_differs(self):
        a = simulate(self.profile, seed_text=STORY_RICH, start_year=2026)
        b = simulate(self.profile, seed_text=STORY_RICH, seed_offset=1,
                     start_year=2026)
        self.assertNotEqual(a["timeline"], b["timeline"],
                            "不同种子应产生不同的平行世界")

    def test_states_bounded(self):
        from engine.simulation import LifeSimulation
        sim = LifeSimulation(self.profile, seed_text=STORY_RICH,
                             start_year=2026)
        year = 2026
        while sim.alive and sim.age < 100:
            sim.step_year(year)
            self.assertTrue(0 <= sim.health <= 100)
            self.assertTrue(0 <= sim.happiness <= 100)
            self.assertTrue(0 <= sim.stress <= 100)
            self.assertGreaterEqual(sim.wealth, 0)
            year += 1
            sim.age += 1


class TestChineseNumerals(unittest.TestCase):

    def test_common_forms(self):
        from engine.cn_number import cn_to_int
        cases = {
            "二十八": 28, "三十": 30, "十八": 18, "廿八": 28, "卅五": 35,
            "一百零五": 105, "两百": 200, "零": 0, "28": 28, "三十二": 32,
            "九十九": 99, "十": 10, "五": 5, "两": 2, "一百": 100,
        }
        for text, want in cases.items():
            self.assertEqual(cn_to_int(text), want, "%s 应为 %d" % (text, want))

    def test_rejects_non_numerals(self):
        from engine.cn_number import cn_to_int
        for text in ("岁月", "", "abc", None, "三十岁"):
            self.assertIsNone(cn_to_int(text), "%r 应无法解析" % (text,))


class TestAgeExtraction(unittest.TestCase):
    """年龄自动识别。分两组：识别能力，以及更重要的——不误判。"""

    YEAR = 2026

    def age(self, text):
        from engine.age import extract_age
        return extract_age(text, self.YEAR)["age"]

    def test_recognizes_common_forms(self):
        cases = {
            "我今年28岁，在深圳做程序员。": 28,
            "我今年二十八。": 28,
            "虚岁三十，周岁二十九。": 29,
            "年龄：29": 29,
            "我今年二十七八岁。": 28,
            "今年三十有二。": 32,
            "刚满三十岁。": 30,
            "上个月刚过完30岁生日。": 30,
            "我1995年出生在一个小县城。": 31,
            "我是95年的。": 31,
            "生于一九八八年。": 38,
            "快30了还是单身。": 29,
            "我三十出头。": 32,
            "去年29岁，今年换了工作。": 30,
            "明年就31了。": 30,
            "再过两年我就40了。": 38,
            "本人男，32，北京。": 32,
            "2008年我18岁，第一次出远门。": 36,
            "2010年参加高考。": 34,
            "我上大三。": 21,
            "我上五年级了。": 11,
            "我是90后。": 31,
            "工作五年了。": 27,
        }
        for text, want in cases.items():
            self.assertEqual(self.age(text), want, "%s 应识别为 %d" % (text, want))

    def test_never_takes_someone_elses_age(self):
        """最重要的一组：别人的年龄绝不能算成你的。"""
        for text in ("我爸60岁了，身体还硬朗。",
                     "我女儿5岁，正上幼儿园。",
                     "我妈是1965年生的。",
                     "爷爷93岁走的，那年我刚工作。",
                     "我带的学生18岁。",
                     "我妈今年六十了。她58岁那年查出糖尿病。",
                     "同事都30出头，我还没结婚。",
                     "我们班同学平均25岁。"):
            self.assertIsNone(self.age(text), "%s 不该得出年龄" % text)

    def test_rejects_non_current_ages(self):
        """过去、假设、虚构、差值、表象——都不是当前年龄。"""
        for text in ("我20岁那年去了北京。",
                     "18岁时我第一次离开家。",
                     "记得25岁那会儿。",
                     "我老婆比我小两岁。",
                     "要是能回到18岁就好了。",
                     "游戏里我捏了个25岁的角色。",
                     "别人都以为我25岁。",
                     "我是2018年去的日本。"):
            self.assertIsNone(self.age(text), "%s 不该得出年龄" % text)

    def test_rejects_number_lookalikes(self):
        for text in ("我今年30号搬的家。", "我今年30万年终奖。",
                     "我最近很迷茫。"):
            self.assertIsNone(self.age(text), "%s 不该得出年龄" % text)

    def test_composes_past_age_plus_elapsed(self):
        self.assertEqual(
            self.age("我23岁那年从老家出来打工，今年是我出来的第十七个年头。"), 40)

    def test_melts_down_on_contradiction(self):
        from engine.age import extract_age
        r = extract_age("我今年32岁。我今年40岁。", self.YEAR)
        self.assertIsNone(r["age"], "自相矛盾时应诚实返回无法判断")
        self.assertIn("矛盾", r["how"] or "")

    def test_realistic_stories(self):
        """25 段真实感人生经历（含陷阱与无法判断型）。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "tests_age_cases.json")
        with open(path, encoding="utf-8") as f:
            cases = json.load(f)
        for c in cases:
            got = self.age(c["story"])
            if c["expect_none"]:
                self.assertIsNone(got, "应无法判断: %s" % c["story"][:30])
            else:
                self.assertIsNotNone(got, "应识别出年龄: %s" % c["story"][:30])
                self.assertLessEqual(
                    abs(got - c["expected_age"]), c["tolerance"],
                    "%s → %s，期望 %s±%s"
                    % (c["story"][:30], got, c["expected_age"], c["tolerance"]))

    def test_profile_reports_unknown_age_honestly(self):
        p = build_profile("我最近很迷茫，不知道该干什么，每天都提不起劲。",
                          current_year=self.YEAR)
        self.assertFalse(p["age_known"])
        self.assertEqual(p["age_confidence"], 0)
        self.assertTrue(p["age"], "读不出年龄时仍应给模拟一个可用的起点")

    def test_profile_reports_known_age_with_evidence(self):
        p = build_profile("我是1995年生的，在深圳做设计。", current_year=self.YEAR)
        self.assertTrue(p["age_known"])
        self.assertEqual(p["age"], 31)
        self.assertGreater(p["age_confidence"], 50)
        self.assertIn("1995", p["age_evidence"])


class TestEventCorpus(unittest.TestCase):

    def test_default_corpus_loads_and_validates(self):
        corpus = load_corpus()
        self.assertGreater(len(corpus), 20, "种子语料库应至少有 20+ 条事件")
        for ev in corpus:
            self.assertIn("id", ev)
            self.assertIn("text", ev)

    def test_invalid_events_filtered(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write('[{"id":"a","text":"好事","domain":"misc"},'
                    '{"id":"b","text":"坏域","domain":"nope"},'
                    '{"text":"没有id","domain":"misc"}]')
            path = f.name
        try:
            corpus = load_corpus(path)
            self.assertEqual([ev["id"] for ev in corpus], ["a"])
        finally:
            os.unlink(path)

    def test_draw_respects_age(self):
        import random
        corpus = [
            {"id": "young", "text": "y", "domain": "misc",
             "min_age": 15, "max_age": 20, "weight": 1.0},
            {"id": "old", "text": "o", "domain": "misc",
             "min_age": 60, "max_age": 90, "weight": 1.0},
        ]
        rng = random.Random(1)
        traits = {"O": 50, "C": 50, "E": 50, "A": 50, "N": 50}
        for _ in range(10):
            self.assertEqual(draw(rng, corpus, 18, traits)["id"], "young")
            self.assertEqual(draw(rng, corpus, 70, traits)["id"], "old")
        self.assertIsNone(draw(rng, corpus, 40, traits))

    def test_ambient_quota_holds_regardless_of_corpus_size(self):
        import random
        # 极端配比：1 条亲历 vs 2000 条氛围。没有配额的话氛围会淹没一切。
        corpus = [{"id": "n1", "text": "n", "domain": "misc", "min_age": 0,
                   "max_age": 100, "weight": 1.0, "kind": "narrative"}]
        corpus += [{"id": "a%04d" % i, "text": "a", "domain": "misc",
                    "min_age": 0, "max_age": 100, "weight": 1.0,
                    "kind": "ambient"} for i in range(2000)]
        rng = random.Random(3)
        traits = {"O": 50, "C": 50, "E": 50, "A": 50, "N": 50}
        ambient = sum(1 for _ in range(2000)
                      if draw(rng, corpus, 30, traits)["kind"] == "ambient")
        share = ambient / 2000.0
        self.assertTrue(0.17 < share < 0.27,
                        "氛围事件占比应稳定在配额附近，实际 %.2f" % share)

    def test_draw_falls_back_when_kind_missing(self):
        import random
        # 只有氛围事件时，亲历事件的抽取请求应回退而不是返回 None
        corpus = [{"id": "a1", "text": "a", "domain": "misc", "min_age": 0,
                   "max_age": 100, "weight": 1.0, "kind": "ambient"}]
        rng = random.Random(5)
        traits = {"O": 50, "C": 50, "E": 50, "A": 50, "N": 50}
        for _ in range(20):
            self.assertIsNotNone(draw(rng, corpus, 30, traits))

    def test_trait_bias_shifts_odds(self):
        import random
        corpus = [
            {"id": "open", "text": "x", "domain": "misc",
             "min_age": 0, "max_age": 100, "weight": 1.0,
             "trait_bias": {"O": 1.0}},
            {"id": "flat", "text": "x", "domain": "misc",
             "min_age": 0, "max_age": 100, "weight": 1.0},
        ]
        rng = random.Random(7)
        high_o = {"O": 100, "C": 50, "E": 50, "A": 50, "N": 50}
        hits = sum(1 for _ in range(500)
                   if draw(rng, corpus, 30, high_o)["id"] == "open")
        # 高开放性时 open 权重 2.0 vs 1.0，应显著多于一半
        self.assertGreater(hits, 280)

    def test_simulation_with_corpus_deterministic(self):
        profile = build_profile(STORY_RICH, current_year=2026)
        corpus = load_corpus()
        a = simulate(profile, seed_text=STORY_RICH, start_year=2026,
                     corpus=corpus)
        b = simulate(profile, seed_text=STORY_RICH, start_year=2026,
                     corpus=corpus)
        self.assertEqual(a, b)


class TestDistill(unittest.TestCase):

    def test_pii_scrubbed(self):
        raw = ("我今天很难过，加我微信 abc12345 聊聊，"
               "或打 13812345678，主页 https://example.com/u/9 @小明")
        ev = distill.distill(raw)
        self.assertIsNotNone(ev)
        for leak in ("abc12345", "13812345678", "example.com", "@小明"):
            self.assertNotIn(leak, ev["text"], "隐私信息必须被清除: %s" % leak)

    def test_first_person_converted(self):
        ev = distill.distill("我在深夜的办公室里加班，觉得很孤独很想家")
        self.assertIsNotNone(ev)
        self.assertIn("你", ev["text"])
        self.assertNotIn("我", ev["text"])

    def test_third_person_wrapped(self):
        ev = distill.distill("成年人的崩溃都是从借钱开始的")
        self.assertIsNotNone(ev)
        # 第三人称金句应被包装为氛围事件：原句放进「」里
        self.assertIn("「成年人的崩溃都是从借钱开始的」", ev["text"])
        # 同一句话必须永远得到同一个包装（确定性）
        self.assertEqual(ev["text"], distill.distill("成年人的崩溃都是从借钱开始的")["text"])

    def test_blocklist_filtered(self):
        self.assertIsNone(distill.distill("我真的好想去死，一切都没有意义了"))

    def test_aphorism_not_treated_as_lived_event(self):
        # 第一人称的格言不是"发生过的事"，应走氛围包装
        ev = distill.distill("我一直以为人是慢慢变老的，其实不是")
        self.assertEqual(ev["kind"], "ambient")

    def test_concrete_first_person_is_narrative(self):
        ev = distill.distill("我昨天收到了大学室友寄来的明信片，上面只写了四个字")
        self.assertEqual(ev["kind"], "narrative")
        self.assertIn("你", ev["text"])

    def test_quote_source_never_yields_narrative(self):
        # 句子库来源即使是具体的第一人称叙述也只做氛围事件
        ev = distill.distill("我昨天收到了一封信，读了很久",
                             allow_narrative=False)
        self.assertEqual(ev["kind"], "ambient")

    def test_length_filter(self):
        self.assertIsNone(distill.distill("太短"))
        self.assertIsNone(distill.distill("长" * 300))

    def test_domain_and_valence(self):
        ev = distill.distill("我失业了三个月，每天投简历都石沉大海，真的很绝望")
        self.assertEqual(ev["domain"], "career")
        self.assertLess(ev["valence"], 0)

    def test_dedupe(self):
        items = [("t", "我今天加班到凌晨真的好累好想辞职"),
                 ("t", "我今天加班到凌晨真的好累好想辞职")]
        self.assertEqual(len(distill.distill_all(items)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
