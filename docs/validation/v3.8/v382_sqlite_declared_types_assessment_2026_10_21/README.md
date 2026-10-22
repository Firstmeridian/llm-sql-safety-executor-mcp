# SQLite声明类型P3评估证据

2026-10-21。DRR-140仅确认及建议，未修改生产代码／测试／配置／grant或写入配置库。前批137／138／139维持原限定验收。

- [评估结论](assessment.json)：当前184 Client调用（进程内／stdio的auto／legacy各46）、36列组件观察、旧2c0a9e7 32调用、原生2项。调用成功但空类型元数据错误按预期复现，不是“问题已修”。
- [当前应用记录](source-final.json.gz)、[旧版应用记录](baseline-2c0a9e7-final.json.gz)、[原生应用记录](native.json.gz)。原生空类型真值沿用前批封存元数据并核对配置库文件摘要不变。
- [评估脚本](assess.py.gz)、[核验脚本](verify.py.gz)、[准备过程](preparation_notes.json)。本地另保留首次stdio初始化失败、旧版夹具授权差异及其输出，不冒充最终矩阵或新增产品问题。
- [正式分析及建议](../V3_8_2_SQLITE_DECLARED_TYPES_ASSESSMENT_2026_10_21_ZH.md)。compact9→11组为直接保留原生类型后的纯签名方案计算，未补丁生产工具；后续需实施并验证才能声称修复。

77运行资源、三份私有TOML及配置SQLite文件保持，61旧manifest／2020记录的存储及已声明解压摘要一致。无新wheel、全量回归、完整Luna、token或性能结果，不需重启。应用内容不等于完整协议帧／通知；外部额外37个rowid变体不计入本批独立实测。文件使用无损gzip，manifest分别记录存储及解压SHA-256。
