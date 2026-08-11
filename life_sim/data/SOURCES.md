# 语料来源与许可

| 文件 | 来源 | 许可/说明 |
|------|------|-----------|
| `events.json` | 本项目手工创作（种子事件） | 随本项目 |
| `events_extra.json` | 本项目手工创作（小事件扩充） | 随本项目 |
| `events_imported.json` | [hitokoto-osc/sentences-bundle](https://github.com/hitokoto-osc/sentences-bundle)（一言社区句子库，选用 网易云热评/网络/原创/哲学/抖机灵 五类） | 上游仓库以 AGPL-3.0 发布；句子为社区收集。已经过蒸馏管线：去隐私、内容过滤、人称改写/包装。如需移除该来源，删除此文件即可（加载器自动热更新）。 |

所有导入语料在入库前强制通过 `crawler/distill.py`：
清除 @用户名/链接/邮箱/手机号/微信QQ号，过滤自我伤害类内容，
并改写为第二人称叙事或包装为"刷到留言"氛围事件。
