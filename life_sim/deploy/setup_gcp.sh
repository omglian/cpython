#!/usr/bin/env bash
# 谷歌云 (GCP) 一键部署脚本 —— 在你的 VM 实例上执行。
#
# 用法（在 VM 的 SSH 终端里）：
#   git clone <你的仓库地址> ~/cpython-src   # 或用 scp 只上传 life_sim 目录
#   sudo bash ~/cpython-src/life_sim/deploy/setup_gcp.sh ~/cpython-src/life_sim
#
# 之后浏览器访问  http://<VM外网IP>:8080/
# 别忘了在 GCP 控制台放行 8080 端口（见脚本末尾提示）。

set -euo pipefail

SRC_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
DEST_DIR=/opt/life_sim

if [ ! -f "$SRC_DIR/server.py" ]; then
    echo "错误: 在 $SRC_DIR 找不到 server.py，请把 life_sim 目录路径作为第一个参数传入" >&2
    exit 1
fi

echo "==> 复制项目到 $DEST_DIR"
mkdir -p "$DEST_DIR"
cp -r "$SRC_DIR/server.py" "$SRC_DIR/engine" "$SRC_DIR/static" \
      "$SRC_DIR/crawler" "$DEST_DIR/"
# 语料库只在首次部署时初始化，之后由爬虫持续追加，更新部署不覆盖
if [ ! -f "$DEST_DIR/data/events.json" ]; then
    cp -r "$SRC_DIR/data" "$DEST_DIR/"
fi
chown -R www-data:www-data "$DEST_DIR"

echo "==> 安装部署脚本与自动跟随更新"
mkdir -p "$DEST_DIR/deploy"
cp "$SRC_DIR/deploy/setup_gcp.sh" "$SRC_DIR/deploy/autoupdate.sh" \
   "$SRC_DIR/deploy/lifesim.service" "$DEST_DIR/deploy/"
chmod +x "$DEST_DIR/deploy/setup_gcp.sh" "$DEST_DIR/deploy/autoupdate.sh"
cat > /etc/cron.d/lifesim-autoupdate <<'CRON'
*/10 * * * * root /bin/bash /opt/life_sim/deploy/autoupdate.sh >> /var/log/lifesim-autoupdate.log 2>&1
CRON

echo "==> 安装 systemd 服务"
cp "$SRC_DIR/deploy/lifesim.service" /etc/systemd/system/lifesim.service
systemctl daemon-reload
systemctl enable lifesim
systemctl restart lifesim
sleep 1
systemctl --no-pager status lifesim || true

echo
echo "==> 本机自检"
curl -fsS http://127.0.0.1:8080/api/health && echo

cat <<'EOF'

部署完成！最后一步：在 GCP 放行 8080 端口（只需做一次）。
在你自己电脑上装了 gcloud 的话：

  gcloud compute firewall-rules create allow-lifesim \
      --allow=tcp:8080 --direction=INGRESS --target-tags=lifesim
  gcloud compute instances add-tags <你的实例名> --tags=lifesim --zone=<你的可用区>

或者在网页控制台: VPC 网络 → 防火墙 → 创建规则 → 允许 tcp:8080。

然后访问  http://<VM外网IP>:8080/
日志查看:  sudo journalctl -u lifesim -f
更新代码:  重新执行本脚本即可

可选：开启事件语料自动采集（每天从合规来源补充游戏事件，服务器热加载）:

  sudo tee /etc/cron.d/lifesim-crawler >/dev/null <<'CRON'
0 3 * * * www-data cd /opt/life_sim && python3 -m crawler.run hn --limit 60 >> /var/log/lifesim-crawler.log 2>&1
CRON

导入你自己导出的平台留言(txt/csv/jsonl):
  cd /opt/life_sim && sudo -u www-data python3 -m crawler.run import --file 你的文件.txt
EOF
