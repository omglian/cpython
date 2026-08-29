#!/usr/bin/env bash
# 自动跟随部署：定时检查 GitHub 分支是否有新提交，有则自动重新部署。
# 由 setup_gcp.sh 安装为 /etc/cron.d/lifesim-autoupdate（每 10 分钟一次）。
# 效果：开发侧每次 push 代码，服务器在 10 分钟内自动更新并重启服务，
# 语料库 data/ 目录的增长不会被覆盖（setup_gcp.sh 只在首次部署时初始化它）。

set -euo pipefail

REPO="omglian/cpython"
BRANCH="claude/life-simulation-game-framework-3pdrmb"
DEST=/opt/life_sim
STATE="$DEST/.deployed_sha"

sha=$(curl -fsSL -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/$REPO/commits/$BRANCH" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
[ -n "$sha" ] || exit 0

if [ -f "$STATE" ] && [ "$(cat "$STATE")" = "$sha" ]; then
    exit 0  # 已是最新，静默退出
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" -o "$tmp/src.tgz"
tar xzf "$tmp/src.tgz" -C "$tmp" --wildcards '*/life_sim'
srcdir=$(echo "$tmp"/*/life_sim)

bash "$srcdir/deploy/setup_gcp.sh" "$srcdir"
echo "$sha" > "$STATE"
echo "$(date -Is) 已自动部署 $sha"
