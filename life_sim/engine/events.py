# -*- coding: utf-8 -*-
"""事件语料库：加载、校验、按人格加权抽取。

语料库是一个 JSON 数组（data/events.json），由 crawler 管线持续补充。
服务器按文件 mtime 热加载——爬虫更新语料后无需重启服务。

抽取逻辑保持模拟的两大原则：
* 可复现 —— 语料按 id 排序后用模拟自身的 RNG 加权抽取，
  同一语料文件 + 同一种子 → 同一条人生；
* 像他本人 —— trait_bias 让事件概率随人格偏移
  （如高开放性的人更容易"捡起搁置多年的爱好"）。
"""

import json
import os

DOMAINS = {"career", "romance", "family", "health", "finance",
           "growth", "social", "misc"}
_TRAIT_KEYS = {"O", "C", "E", "A", "N"}
_EFFECT_KEYS = {"happiness", "stress", "health", "wealth"}

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DEFAULT_PATH = os.path.join(DATA_DIR, "events.json")

_cache = {}  # key -> (version, corpus)


def _valid(ev):
    if not isinstance(ev, dict):
        return False
    if not isinstance(ev.get("id"), str) or not isinstance(ev.get("text"), str):
        return False
    if ev.get("domain") not in DOMAINS:
        return False
    try:
        if not (0 <= int(ev.get("min_age", 0)) <= int(ev.get("max_age", 100)) <= 120):
            return False
        if not (-2 <= int(ev.get("valence", 0)) <= 2):
            return False
        if float(ev.get("weight", 1.0)) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    bias = ev.get("trait_bias", {})
    if not isinstance(bias, dict) or not set(bias) <= _TRAIT_KEYS:
        return False
    effects = ev.get("effects", {})
    if not isinstance(effects, dict) or not set(effects) <= _EFFECT_KEYS:
        return False
    return True


def _read_events(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [ev for ev in data if _valid(ev)] if isinstance(data, list) else []


def load_corpus(path=None):
    """带 mtime 缓存的语料加载；文件缺失或损坏时返回空列表。

    path 为 None 时进入目录模式：合并 data/ 下所有 .json 文件
    （按 id 去重），任何一个文件变化都会触发重新加载。
    """
    if path is not None:
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return []
        cached = _cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        corpus = sorted(_read_events(path), key=lambda ev: ev["id"])
        _cache[path] = (mtime, corpus)
        return corpus

    try:
        files = sorted(
            os.path.join(DATA_DIR, name) for name in os.listdir(DATA_DIR)
            if name.endswith(".json"))
    except OSError:
        return []
    version = []
    for f in files:
        try:
            version.append((f, os.stat(f).st_mtime_ns))
        except OSError:
            pass
    version = tuple(version)
    cached = _cache.get(DATA_DIR)
    if cached and cached[0] == version:
        return cached[1]
    corpus, seen = [], set()
    for f in files:
        for ev in _read_events(f):
            if ev["id"] not in seen:
                seen.add(ev["id"])
                corpus.append(ev)
    corpus.sort(key=lambda ev: ev["id"])  # 稳定顺序保证抽取可复现
    _cache[DATA_DIR] = (version, corpus)
    return corpus


def draw(rng, corpus, age, traits):
    """按年龄过滤 + 权重 × 人格调制，加权随机抽一条事件。

    traits: {"O":..,"C":..,"E":..,"A":..,"N":..} 0~100
    无候选时返回 None。
    """
    candidates, weights = [], []
    for ev in corpus:
        if not (ev.get("min_age", 0) <= age <= ev.get("max_age", 100)):
            continue
        w = float(ev.get("weight", 1.0))
        for key, bias in ev.get("trait_bias", {}).items():
            # 特质 50 为中性；bias=0.5 且特质 100 时权重 ×1.5
            w *= max(0.05, 1.0 + (traits.get(key, 50) - 50) / 50.0 * bias)
        candidates.append(ev)
        weights.append(w)
    if not candidates:
        return None
    return rng.choices(candidates, weights=weights, k=1)[0]
