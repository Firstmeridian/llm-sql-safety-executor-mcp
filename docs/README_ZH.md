# 文档索引

[English](README.md) | 中文

项目动机、设计理念、快速开始与工具示例见根目录 [README](../README_ZH.md)。本索引按用途整理详细指南、设计决策与验收证据。

## 配置与使用

- [配置示例说明](../config/examples/README_ZH.md)：SQLite、MySQL、多连接与受控写入。
- [TOML 配置与迁移](guides/CONFIGURATION_ZH.md)：字段、默认值、密钥来源、权限、扩展导入及切换/回退。
- [MCP 客户端指南](guides/TEST_MCP_CLIENT_GUIDE.md)：离线检查、协议检查与 preview/MRTR 审批示例。
- [AutoGen 示例](../examples/autogen/README.md)：独立依赖环境与验证范围。

## 设计与可复用指南

- [重构日志](../REFACTORING_LOG_ZH.md) / [English](../REFACTORING_LOG.md)：持续维护变更、决策、取舍和验证记录，包含 v3.8。
- [v3.8 实施决策](architecture/V3_8_IMPLEMENTATION_ZH.md)：包结构、实例状态与参考稿评审。
- [工具契约与评估方法](guides/PROMPT_ENGINEERING_BEST_PRACTICES.md)：参数 schema、工具说明、提示词与行为检查。
- [Agent 编排行为验证方法](guides/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md)：可复用的路由、渐进披露和成本评估方法。
- [命名连接、Skills 与批准流程（v3.5–v3.7）](guides/V3_5-V3_7_SKILLS_GUIDE_ZH.md)。
- [统一连接诊断设计](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN_ZH.md) / [English](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN.md)。
- [连接范围与参数示例修复方案（v3.7.3）](guides/V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md)。
- [此前的客户端指南（v3.7）](guides/TEST_MCP_CLIENT_GUIDE_v3_7.md)：保留该版本的响应示例与检查方式。
- 架构背景：[Skills 设计](architecture/MCP_AGENTS_SKILLS_DESIGN.md)、[SQLite 适配器](architecture/SQLITE_ADAPTER_DESIGN.md)、[LLM 转 MCP 可行性](architecture/LLM_TO_MCP_FEASIBILITY_ANALYSIS.md)。

指南统一放在 `docs/guides/`，文件名中的旧版本号不影响其作为设计和使用参考的价值。适用范围以文首说明与分日期记录为准；旧脚本、环境配置及测试数量不能直接当作当前部署说明。使用 v3.8 安装包时，请同时参考当前配置与客户端指南。

## 安全

- [v3.8 安全边界](security/V3_8_SECURITY.md)：可信 Python/Host、MRTR、单进程状态、审计与不确定结果。
- [设计风险登记](security/DESIGN_RISK_REGISTER_ZH.md) / [English](security/DESIGN_RISK_REGISTER.md)。
- [Skills 安全策略](security/SAFETY.md)：原扩展治理约定；适用版本和当前契约入口见文首。

## 发布与验收

- [v3.8 本地 live Review](validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md)：Host 入口修复、真实数据库检查、9 次 Luna CLI 试验，以及后续原生重连和三组六轮代理测试；保留失败与验收边界。
- [v3.8 发布说明](releases/RELEASE_NOTES_v3_8.md)及[验收与实际 Host 限制](validation/V3_8_VALIDATION_ZH.md)。
- [v3.7 发布说明](releases/RELEASE_NOTES_v3_7.md)、[v3.6](releases/RELEASE_NOTES_v3_6.md)、[v3.5](releases/RELEASE_NOTES_v3_5.md)。
- [v3.7 实测记录](validation/v3.7/)与 [v3.8 证据](validation/v3.8/)。保留原版本、失败试验和结论，不把旧版通过当成 v3.8 已验收。

## 归档快照

- [v3.7 README 中文版](history/README_v3.7_ZH.md) / [English](history/README_v3.7.md)。
- [旧公开环境配置模板](history/config/)：仅作迁移参考，服务不再加载 `.env`。

根目录 README 和重构日志继续维护。SQL 与业务 Skill 定义仍放在根目录 `skills/`，框架 SDK 位于 `src/sql_safety_executor/skills/`。
