# -*- coding: utf-8 -*-
"""来源适配器：每个适配器返回原始文本条目的迭代器 (source_tag, text)。

只包含合规来源：
* hackernews — Hacker News 官方公开 API (Firebase)，含 Ask HN 帖与评论
* rss        — 任意 RSS 2.0 / Atom 订阅源（标题 + 摘要）
* hitokoto   — 一言开源句子库（GitHub 公开仓库，含网易云热评等）
* local      — 本地文件导入 (.txt 每行一条 / .csv / .jsonl)，
               用来喂你自己有权导出的任何平台数据
"""

import csv
import json
import os
import re
import xml.etree.ElementTree as ET

from . import fetch

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text):
    text = text.replace("&quot;", '"').replace("&#x27;", "'") \
               .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
               .replace("<p>", " ")
    return _TAG_RE.sub(" ", text)


# ---------------------------------------------------------------------------
# Hacker News 官方 API
# ---------------------------------------------------------------------------

_HN_BASE = "https://hacker-news.firebaseio.com/v0"


def hackernews(limit=30, with_comments=True):
    """抓取 Ask HN / 热帖标题及部分高层评论。"""
    yielded = 0
    ids = fetch.get_json("%s/askstories.json" % _HN_BASE) or []
    ids += fetch.get_json("%s/topstories.json" % _HN_BASE) or []
    for item_id in ids:
        if yielded >= limit:
            return
        try:
            item = fetch.get_json("%s/item/%d.json" % (_HN_BASE, item_id))
        except Exception:
            continue
        if not item or item.get("dead") or item.get("deleted"):
            continue
        title = item.get("title") or ""
        if title:
            yield "hn", _strip_html(title)
            yielded += 1
        if with_comments:
            for kid in (item.get("kids") or [])[:3]:
                if yielded >= limit:
                    return
                try:
                    c = fetch.get_json("%s/item/%d.json" % (_HN_BASE, kid))
                except Exception:
                    continue
                if c and c.get("text") and not c.get("dead"):
                    yield "hn", _strip_html(c["text"])
                    yielded += 1


# ---------------------------------------------------------------------------
# 通用 RSS / Atom
# ---------------------------------------------------------------------------

def rss(url, limit=50):
    """解析 RSS 2.0 或 Atom，产出 标题 + 描述/摘要。"""
    root = ET.fromstring(fetch.get_text(url))
    count = 0
    # RSS 2.0
    for item in root.iter("item"):
        if count >= limit:
            return
        for tag in ("title", "description"):
            el = item.find(tag)
            if el is not None and el.text:
                yield "rss", _strip_html(el.text)
        count += 1
    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(ns + "entry"):
        if count >= limit:
            return
        for tag in ("title", "summary", "content"):
            el = entry.find(ns + tag)
            if el is not None and el.text:
                yield "rss", _strip_html(el.text)
        count += 1


# ---------------------------------------------------------------------------
# 一言开源句子库 (hitokoto-osc/sentences-bundle)
# ---------------------------------------------------------------------------

# 只取贴近"真实生活留言"语感的类目；动画/漫画/游戏/诗词等与本作氛围不符
HITOKOTO_CATEGORIES = {
    "j": "ncm",         # 网易云音乐热评
    "f": "net",         # 来自网络
    "e": "original",    # 原创
    "k": "philosophy",  # 哲学
    "l": "funny",       # 抖机灵
    "d": "literature",  # 现代文学：小说、散文
}

HITOKOTO_REPO = "https://github.com/hitokoto-osc/sentences-bundle"


def hitokoto(path, categories=None):
    """读取本地克隆的一言句子库。

    path: 仓库根目录（需先 git clone HITOKOTO_REPO）
    categories: 可选的类目字母集合，默认取 HITOKOTO_CATEGORIES 全部
    """
    wanted = categories or HITOKOTO_CATEGORIES.keys()
    sent_dir = os.path.join(path, "sentences")
    for letter in sorted(wanted):
        tag = HITOKOTO_CATEGORIES.get(letter, "hitokoto")
        fname = os.path.join(sent_dir, "%s.json" % letter)
        if not os.path.exists(fname):
            continue
        with open(fname, encoding="utf-8", errors="replace") as f:
            try:
                data = json.load(f)
            except ValueError:
                continue
        for item in data:
            text = item.get("hitokoto") if isinstance(item, dict) else None
            if text:
                yield tag, text


# ---------------------------------------------------------------------------
# 本地导入
# ---------------------------------------------------------------------------

def local(path):
    """导入本地文件：.txt(每行一条) / .csv(text列或首列) / .jsonl({"text":...})。"""
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        if ext == ".csv":
            reader = csv.reader(f)
            header = next(reader, [])
            try:
                col = [h.strip().lower() for h in header].index("text")
            except ValueError:
                col = 0
                if header and header[col].strip():
                    yield "local", header[col]
            for row in reader:
                if row and len(row) > col and row[col].strip():
                    yield "local", row[col]
        elif ext in (".jsonl", ".ndjson"):
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                text = obj.get("text") if isinstance(obj, dict) else None
                if text:
                    yield "local", str(text)
        else:  # .txt 及其它按行处理
            for line in f:
                if line.strip():
                    yield "local", line.strip()
