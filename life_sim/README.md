# 人生重演 · Life Replay

一个**真实模拟、符合逻辑**的人生模拟游戏框架。

玩家在页面输入自己的详细经历和故事——**写得越详细，模拟出的人生就越像
他本人**。系统运用人物侧写与心理学知识（大五人格、Schwartz 价值观理论、
成人依恋理论等）构建心理画像，再以画像驱动一场逐年推演的人生模拟。

当前版本是路线图的第一步：**纯文字版页面**（无像素风、无 2D），
零第三方依赖，可直接部署到谷歌云 VM。

---

## 总体框架宗旨

1. **真实** —— 事件概率参考现实规律：死亡率随年龄按 Gompertz 曲线指数
   上升、25~33 岁的婚恋高峰、40 岁后健康缓慢下滑、尽责性是职业成就
   最强的人格预测因子（工业组织心理学结论）等。
2. **符合逻辑** —— 每个重大事件都有前置条件和因果解释。叙事会直接说明
   "为什么"：*高开放性(72)让你做出了旁人意外的决定：转行……*
3. **像他本人** —— 人生岔路口（考研/跳槽/创业/买房/婚姻）不掷硬币，
   而是由侧写出的人格与价值观自动做出"他会做的选择"。
4. **写得越详细越像** —— 侧写引擎逐句记录证据（哪句话→哪个维度→多少
   权重），并根据文本长度与细节密度给出置信度；细节越多，画像越个人化。
5. **可复现的命运** —— 随机种子取自经历文本哈希：同一段人生经历总是
   重演出同一条轨迹；点"平行世界"换种子，看同样的你在不同运气下的人生。

## 目录结构

```
life_sim/
├── server.py            # 零依赖 HTTP 服务器（标准库 http.server）
├── engine/
│   ├── lexicon.py       # 心理学词典：语言信号 → 量表维度
│   ├── profiler.py      # 人物侧写引擎：文本 → 心理画像(JSON)
│   └── simulation.py    # 人生模拟引擎：画像 → 逐年人生轨迹
├── static/index.html    # 文字版页面（终端风格）
├── deploy/
│   ├── setup_gcp.sh     # 谷歌云一键部署脚本
│   └── lifesim.service  # systemd 服务
└── tests.py             # 冒烟测试（python3 tests.py）
```

## 本地运行

```bash
cd life_sim
python3 tests.py      # 跑测试（可选）
python3 server.py     # 打开 http://127.0.0.1:8080/
```

只需要 Python 3.8+，**不需要 pip install 任何东西**。

## 部署到谷歌云

在你的 GCP VM 实例（Debian/Ubuntu 均可）的 SSH 终端里：

```bash
# 1. 把代码弄上去（二选一）
git clone <本仓库地址> ~/src && cd ~/src
#   或者在本机: gcloud compute scp --recurse life_sim <实例名>:~/

# 2. 一键部署（复制到 /opt/life_sim + 注册 systemd 开机自启）
sudo bash life_sim/deploy/setup_gcp.sh life_sim

# 3. 放行 8080 端口（本机 gcloud 或网页控制台，只需一次）
gcloud compute firewall-rules create allow-lifesim \
    --allow=tcp:8080 --direction=INGRESS --target-tags=lifesim
gcloud compute instances add-tags <实例名> --tags=lifesim --zone=<可用区>
```

然后访问 `http://<VM外网IP>:8080/`。
日志：`sudo journalctl -u lifesim -f`；更新代码后重跑部署脚本即可。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/` | 文字版页面 |
| POST | `/api/profile` | `{"story", "age"?, "gender"?}` → 心理侧写 |
| POST | `/api/simulate` | 同上 + `"seed_offset"?` → 侧写 + 完整人生模拟 |
| GET  | `/api/health` | 健康检查 |

## 心理学模型（当前实现）

* **大五人格 OCEAN**：中文关键词词典加权评分，tanh 压缩防单词刷分，
  短文本向均值回归（信息不足不妄下判断）。每一分都附带证据句。
* **Schwartz 价值观**（简化五类）：成就 / 安全 / 享乐 / 利他 / 自主，
  归一化为相对强度，直接决定模拟中的取舍（如安全↑抑制创业、驱动买房）。
* **成人依恋**（Hazan & Shaver）：安全 / 焦虑 / 回避三型，
  调制恋爱建立、分手与离婚概率及其叙事。
* **生平事实抽取**：年龄/出生年、学历、职业、婚育等硬事实决定模拟起点。

## 路线图

- [x] v0.1 文字版页面 + 规则侧写 + 逐年模拟（本版本）
- [ ] v0.2 LLM 侧写器（同一 `build_profile` 接口，深度理解长篇自传）
- [ ] v0.3 交互式决策点（岔路口暂停，玩家可选"顺着我的性格"或亲自选）
- [ ] v0.4 像素风 2D 渲染层（文字引擎不变，前端替换为 2D 场景）
- [ ] v0.5 账号系统与人生档案存储
