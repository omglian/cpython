# -*- coding: utf-8 -*-
"""life_sim.engine — 人生模拟游戏的核心引擎。

模块划分：
* lexicon    心理学词典（大五人格 / 价值观 / 依恋风格的语言信号）
* profiler   人物侧写引擎（文本 → 心理画像）
* simulation 人生模拟引擎（心理画像 → 逐年人生轨迹）
"""

from .profiler import build_profile
from .simulation import simulate, LifeSimulation

__all__ = ["build_profile", "simulate", "LifeSimulation"]
