#!/usr/bin/env bash
# 人生重演 · Cloud Shell 一键部署
#
# 在谷歌云 Cloud Shell（console.cloud.google.com 右上角 >_ 图标）里运行：
#
#   curl -fsSL https://raw.githubusercontent.com/omglian/cpython/claude/life-simulation-game-framework-3pdrmb/life_sim/deploy/cloudshell.sh | bash
#
# 项目里有多台运行中实例时，在命令末尾指定一台：  ... | bash -s -- <实例名>
#
# 脚本做四件事：找到你的 VM → SSH 上去部署（含自动跟随更新 cron）→
# 放行 8080 端口 → 打印游戏访问地址。

set -euo pipefail

BRANCH="claude/life-simulation-game-framework-3pdrmb"
TARBALL="https://codeload.github.com/omglian/cpython/tar.gz/refs/heads/$BRANCH"

PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
    echo "!! 当前 Cloud Shell 未选定项目。先运行以下两条，再重跑本脚本："
    echo "   gcloud projects list"
    echo "   gcloud config set project <项目ID>"
    exit 1
fi
echo "==> 项目: $PROJECT"

WANT="${1:-}"
LIST=$(gcloud compute instances list --filter="status=RUNNING" \
       --format="value(name,zone)" 2>/dev/null || true)
if [ -z "$LIST" ]; then
    echo "!! 项目 $PROJECT 里没有运行中的 VM 实例。"
    echo "   如果你的 VM 在别的项目里: gcloud config set project <项目ID> 后重跑。"
    exit 1
fi

COUNT=$(printf '%s\n' "$LIST" | wc -l)
NAME=""; ZONE=""
if [ -n "$WANT" ]; then
    read -r NAME ZONE <<<"$(printf '%s\n' "$LIST" | awk -v w="$WANT" '$1==w{print; exit}')" || true
    if [ -z "$NAME" ]; then echo "!! 找不到运行中的实例: $WANT"; exit 1; fi
elif [ "$COUNT" -eq 1 ]; then
    read -r NAME ZONE <<<"$LIST"
else
    echo "!! 发现多台运行中的实例，请指定一台重跑："
    printf '%s\n' "$LIST" | awk '{print "   curl -fsSL <本脚本地址> | bash -s -- " $1}'
    exit 1
fi
echo "==> 目标实例: $NAME ($ZONE)"

echo "==> 通过 SSH 在实例上执行部署（首次运行会自动生成 SSH 密钥，稍等即可）"
gcloud compute ssh "$NAME" --zone="$ZONE" --quiet --command="
  set -e
  curl -fsSL '$TARBALL' -o /tmp/lifesim.tgz
  tar xzf /tmp/lifesim.tgz -C /tmp --wildcards '*/life_sim'
  sudo bash /tmp/cpython-*/life_sim/deploy/setup_gcp.sh /tmp/cpython-*/life_sim
"

echo "==> 放行 8080 端口（规则已存在则跳过）"
gcloud compute firewall-rules create allow-lifesim \
    --allow=tcp:8080 --direction=INGRESS >/dev/null 2>&1 \
    || echo "   (防火墙规则已存在，跳过)"

IP=$(gcloud compute instances describe "$NAME" --zone="$ZONE" \
     --format='value(networkInterfaces[0].accessConfigs[0].natIP)')

echo
echo "=================================================================="
echo "  部署完成！用浏览器访问:   http://$IP:8080/"
echo "  代码仓库每次更新后，这台机器会在 10 分钟内自动跟随部署。"
echo "  查看服务日志:  gcloud compute ssh $NAME --zone=$ZONE --command='sudo journalctl -u lifesim -n 50'"
echo "=================================================================="
