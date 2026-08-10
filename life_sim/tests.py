# -*- coding: utf-8 -*-
"""life_sim 冒烟测试：python3 tests.py 直接运行，全绿即通过。"""

import unittest

from engine import build_profile, simulate

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
