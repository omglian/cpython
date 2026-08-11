# -*- coding: utf-8 -*-
"""采集管线命令行入口。在 life_sim 目录下运行：

    python3 -m crawler.run hn --limit 50            # Hacker News 官方 API
    python3 -m crawler.run rss --url <feed地址>      # 任意 RSS/Atom 源
    python3 -m crawler.run import --file 留言.txt    # 本地导入(txt/csv/jsonl)
    python3 -m crawler.run stats                     # 查看语料库统计

所有子命令默认合并写入 data/events.json（按内容哈希去重，重复跑安全）。
服务器会自动热加载更新后的语料，无需重启。
"""

import argparse
import json
import os
import sys

from . import distill, sources

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "events.json")


def load_corpus_file(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def merge_and_save(path, new_events):
    corpus = load_corpus_file(path)
    seen = {ev.get("id") for ev in corpus}
    added = 0
    for ev in new_events:
        if ev["id"] not in seen:
            corpus.append(ev)
            seen.add(ev["id"])
            added += 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)  # 原子替换，服务器热加载时不会读到半个文件
    return added, len(corpus)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crawler.run", description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="语料库文件路径 (默认 data/events.json)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hn = sub.add_parser("hn", help="Hacker News 官方公开 API")
    p_hn.add_argument("--limit", type=int, default=30)
    p_hn.add_argument("--no-comments", action="store_true")

    p_rss = sub.add_parser("rss", help="RSS/Atom 订阅源")
    p_rss.add_argument("--url", required=True)
    p_rss.add_argument("--limit", type=int, default=50)

    p_hito = sub.add_parser("hitokoto", help="一言开源句子库（需先 git clone）")
    p_hito.add_argument("--path", required=True,
                        help="hitokoto-osc/sentences-bundle 本地克隆路径")
    p_hito.add_argument("--categories", default=None,
                        help="类目字母，如 jfe（默认取全部合适类目）")

    p_imp = sub.add_parser("import", help="本地文件导入")
    p_imp.add_argument("--file", required=True)
    p_imp.add_argument("--source", default=None,
                       help="来源标签(默认 local)，用于区分语料出处")

    sub.add_parser("stats", help="语料库统计")

    args = parser.parse_args(argv)

    if args.cmd == "stats":
        corpus = load_corpus_file(args.out)
        by_domain, by_source = {}, {}
        for ev in corpus:
            by_domain[ev.get("domain", "?")] = by_domain.get(ev.get("domain", "?"), 0) + 1
            by_source[ev.get("source", "?")] = by_source.get(ev.get("source", "?"), 0) + 1
        print("语料库: %s\n事件总数: %d" % (args.out, len(corpus)))
        print("按领域:", json.dumps(by_domain, ensure_ascii=False))
        print("按来源:", json.dumps(by_source, ensure_ascii=False))
        return 0

    if args.cmd == "hn":
        items = sources.hackernews(limit=args.limit,
                                   with_comments=not args.no_comments)
    elif args.cmd == "rss":
        items = sources.rss(args.url, limit=args.limit)
    elif args.cmd == "hitokoto":
        cats = set(args.categories) if args.categories else None
        items = sources.hitokoto(args.path, categories=cats)
    else:
        items = sources.local(args.file)
        if args.source:
            items = ((args.source, text) for _tag, text in items)

    # 语录/句子类来源只产出氛围事件，不冒充玩家亲历经历
    events = distill.distill_all(items,
                                 allow_narrative=(args.cmd != "hitokoto"))
    added, total = merge_and_save(args.out, events)
    print("蒸馏出 %d 条事件，新增 %d 条（去重后），语料库现有 %d 条。"
          % (len(events), added, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
