# -*- coding: utf-8 -*-
"""礼貌抓取器：robots.txt 检查 + 全局限速 + 标准库 urllib 实现。"""

import json
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlsplit

USER_AGENT = "LifeReplayCrawler/0.1 (+life-sim event corpus; polite; contact: repo issues)"
MIN_INTERVAL = 1.0   # 同进程内任意两次请求的最小间隔（秒）
TIMEOUT = 15

_last_request_at = [0.0]
_robots_cache = {}


def _robots_allowed(url):
    """按站点缓存 robots.txt；robots 不可达时按业界惯例视为允许。"""
    parts = urlsplit(url)
    base = "%s://%s" % (parts.scheme, parts.netloc)
    rp = _robots_cache.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(
                base + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                rp.parse(resp.read().decode("utf-8", "replace").splitlines())
        except (urllib.error.URLError, OSError, ValueError):
            rp.allow_all = True
        _robots_cache[base] = rp
    return rp.can_fetch(USER_AGENT, url)


def get(url):
    """限速 + robots 检查的 GET。返回 bytes，被禁止时抛 PermissionError。"""
    if not _robots_allowed(url):
        raise PermissionError("robots.txt 不允许抓取: %s" % url)
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
    finally:
        _last_request_at[0] = time.monotonic()
    return data


def get_json(url):
    return json.loads(get(url).decode("utf-8", "replace"))


def get_text(url):
    return get(url).decode("utf-8", "replace")
