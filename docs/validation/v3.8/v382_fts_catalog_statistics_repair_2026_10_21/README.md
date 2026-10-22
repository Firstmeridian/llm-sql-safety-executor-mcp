# DRR-137／138／139 补修证据

2026-10-21，版本3.8.2，当前原生验收待维护者一次重启。

- [最终核验](final-checks.json)：3340通过／4跳过，新增90回归，源码／正常wheel各488应用调用一致、77资源及三份私有配置核对；57旧封存／1828记录保持。
- [成本](cost-summary.json)：串行暖adapter A/B/A，保留显著基线漂移、完整索引核验开销及部分统计1→1500的非等价结果。原始cost-*.json.gz含全部分组。
- source-final.json.gz／installed-final.json.gz记录22场景，两模式进程内与独立stdio。应用文本／structured content不是完整协议帧或通知；无模型／token声明。
- rowid-cold-before.json.gz为批前冻结源码；8/15冷态误拒，rowid-before.json.gz可信预热15/15成功。rowid-cold-after.json.gz补修后15/15通过。current为中间阶段观察，不另冒充已封存版本。
- [过程说明](preparation_notes.json)、相应初轮失败／被中断日志保留；完整回归以regression-completed.log.gz为准，regression-final.log.gz是被中止的沙盒运行。
- [原生计划](native_plan.json)：10次既有别名调用；2次独立只读SQLite真值不算原生验收。特殊碰撞／统计／默认rowid夹具保持源码／安装归属。

脚本压缩文件供核对过程；复用时解压相关helpers并选择新的输出及源路径，不覆盖记录。normal-wheel为离线缓存后端构建、正常安装到独立解释器，显式复用冻结依赖；不是editable或全新依赖解析。manifest同时记录gzip存储和解压内容SHA-256。
