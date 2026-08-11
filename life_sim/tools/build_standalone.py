# -*- coding: utf-8 -*-
"""把 data/ 语料库打包进单机版页面 static/standalone.html。

爬虫更新语料后运行一次即可（服务器版是热加载，单机版需要重新内嵌）：

    cd life_sim && python3 tools/build_standalone.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.events import load_corpus  # noqa: E402

PAGE = os.path.join(ROOT, "static", "standalone.html")
START = "const CORPUS = "
END = ".sort((a, b) => a.id < b.id ? -1 : 1);"

# 单机版只需要抽取用得到的字段，去掉 valence/source 可省下可观体积
KEEP = ("id", "text", "domain", "min_age", "max_age", "weight")
OPTIONAL = ("kind", "trait_bias", "effects")

# 亲历事件全部内嵌；氛围金句只取一部分——一局人生也就抽到几条，
# 服务器版仍保有全部语料，单机版没必要让手机多下载 1MB。
AMBIENT_CAP = 1500


def main():
    corpus = load_corpus()
    # 按 id 排序后截断，保证每次构建取到同一批（可复现）
    ambient = [ev for ev in corpus if ev.get("kind") == "ambient"]
    keep_ids = {ev["id"] for ev in ambient[:AMBIENT_CAP]}
    dropped = len(ambient) - len(keep_ids)

    slim = []
    for ev in corpus:
        if ev.get("kind") == "ambient" and ev["id"] not in keep_ids:
            continue
        item = {k: ev[k] for k in KEEP if k in ev}
        item.setdefault("min_age", 0)
        item.setdefault("max_age", 100)
        item.setdefault("weight", 1.0)
        for k in OPTIONAL:
            if ev.get(k):
                item[k] = ev[k]
        slim.append(item)

    payload = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # 防止意外闭合 </script>

    with open(PAGE, encoding="utf-8") as f:
        src = f.read()
    start = src.index(START)
    end = src.index(END, start) + len(END)
    new = src[:start] + START + payload + END + src[end:]
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(new)

    print("已内嵌 %d 条事件到 standalone.html（%.0f KB）"
          % (len(slim), len(new.encode("utf-8")) / 1024))
    if dropped:
        print("  （氛围金句按上限 %d 截取，服务器版仍保有全部 %d 条）"
              % (AMBIENT_CAP, AMBIENT_CAP + dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
