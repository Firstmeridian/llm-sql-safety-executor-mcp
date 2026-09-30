# v3.8 MCP Apps 支持：设计、来源评审与验证记录

状态：提案（PR），默认关闭。本文件只记录本次新增内容，不改写 v3.8 既有决策与实测证据。

## 目标与范围

在支持 MCP Apps（扩展标识 `io.modelcontextprotocol/ui`，SEP-1865，Stable 2026-01-26）的 Host 中，把 `query` 与 `execute_query_skill` 的表格结果以沙箱内的只读表格呈现；不支持的 Host 行为保持不变。

明确不做：

- 不把 View 作为审批界面，不提供任何写入、预览、确认或 MRTR 按钮。审批仍属于可信 Host（模式 A）与既有 preview/execute、MRTR 流程。
- View 不调用工具、不读资源、不发 `ui/message`、不打开链接、不写 `ui/update-model-context`。
- 不新增 app-only 工具，不引入 Prefab/React/CDN 等运行时依赖，不改变 `structuredContent` 载荷。

## 设计

| 项 | 决定 |
| --- | --- |
| 开关 | `server.toml` 顶层 `[apps] enabled = false`（严格布尔，未知字段报错）。与 MRTR 一致，默认关闭，需针对已验证 Host 显式开启 |
| UI 资源 | `ui://sql-safety-executor/result-viewer.html`，MIME `text/html;profile=mcp-app`，随包安装的单文件静态 HTML，内联脚本/样式 |
| 资源 `_meta.ui` | `csp: {}`（显式声明无外部 connect/resource/frame 源），`prefersBorder: true`；不请求 camera/microphone/geolocation/clipboard 权限，不声明 `domain` |
| 工具绑定 | 仅 `query`、`execute_query_skill` 声明 `_meta.ui.resourceUri` |
| 可见性 | 开启时全部网关工具（含 `execute_mutation_skill`、`request_mutation_approval`）声明 `visibility=["model"]`：View 无需调用工具，按规范 Host 必须拒绝 View 发起的这些 `tools/call` |
| 渲染 | 只用 `textContent`；null 显示为 `NULL`，对象 JSON 化；显示服务端 `row_count/total_rows/truncation_note`；View 自身最多渲染 1000 行防止 DOM 过大（服务端 `limits.result_rows` 仍是真实边界） |
| 文档内 CSP | `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`，只会比 Host 默认更严 |
| 协议 | 直接用 postMessage JSON-RPC：`ui/initialize` → `ui/notifications/initialized`；处理 `tool-input`、`tool-result`、`tool-cancelled`、`host-context-changed`、`ui/resource-teardown`、`ping`；发送 `ui/notifications/size-changed`；只接受 `event.source === window.parent` 的消息 |
| 主题 | 应用 `hostContext.theme` 与 `styles.variables` 中 `--` 开头的 CSS 自定义属性；不注入 Host 字体 CSS（文档 CSP 本就阻止外部字体） |
| 降级 | 结果仍由 FastMCP 序列化为文本 `content`；非 Apps Host 与关闭开关时行为不变 |

实现位于 `src/sql_safety_executor/mcp/apps.py` 与 `src/sql_safety_executor/mcp/ui/result_viewer.html`。`apps.py` 在 `server.py` 完成 `prepare_framework()` 之后才导入，保持 FastMCP dotenv 关闭的导入顺序约束。

## 来源评审与取舍

| 来源 | 采纳 | 评审/取舍 |
| --- | --- | --- |
| MCP Apps 规范 SEP-1865（modelcontextprotocol/ext-apps `specification/2026-01-26/apps.mdx`） | `ui://` 资源、MIME、`_meta.ui.resourceUri/visibility/csp/prefersBorder`、`ui/*` 生命周期、size-changed、降级要求 | 规范建议服务端在注册 UI 工具前检查客户端能力。FastMCP 静态注册无按会话变体；本实现以默认关闭 + 文本降级替代，未支持的 Host 忽略 `_meta.ui`。旧的扁平 `_meta["ui/resourceUri"]` 已废弃，不输出 |
| 规范 Threat Model（View 未授权调用工具、外泄、钓鱼） | 可见性收紧为 model-only；View 不发起任何 MCP 请求；无网络源 | 沙箱、CSP 和可见性过滤是 Host 义务，服务端无法验证；因此继续依赖服务端既有闸门，而不是把 View 当作安全边界 |
| FastMCP 4.0.10（已锁定依赖）`fastmcp.apps.AppConfig/ResourceCSP`、`resource(app=...)`、`tool(app=...)` | 使用 `AppConfig` 生成线上 `_meta.ui`，`ui://` 自动得到 MIME | 未采用 `FastMCPApp`/Prefab 生成式 UI：会引入额外渲染器与 CSP 源，且其 app 工具模式与“View 不调用工具”目标冲突。FastMCP 在 2026-07-28 协议下无条件声明 UI 扩展能力（2025-11-25 被 SDK 剥离），已在安全文档注明 |
| MCP Python SDK `mcp.server.apps`（低层 `Apps` 扩展） | 核对常量与字段命名一致 | 本项目以 FastMCP 为组合根，不混用低层 `MCPServer` 扩展注册 |
| OpenAI Apps SDK（ChatGPT） | 以标准 `_meta.ui.*` 与 `ui/*` 桥为主 | 不输出 `openai/outputTemplate`、`openai/widgetAccessible` 等厂商键，也不依赖 `window.openai`；是否需要兼容旧键应在对应 Host 实测后另行决定 |
| Anthropic（Claude / Claude Desktop）、Microsoft（VS Code GitHub Copilot） | 规范示例中的 `hostContext` 主题变量、`prefersBorder` 显式声明 | `domain` 格式因 Host 而异（规范示例含 `claudemcpcontent.com`、`oaiusercontent.com`），本 View 无外部访问需求，不声明 |
| Google（Gemini）、xAI/SpaceXAI（Grok） | — | 截至本文未找到可核实的一方 MCP Apps Host 文档；二手汇总文章的支持矩阵未作为依据 |
| 社区/二手文章（如 MCP Apps 解读博客） | 仅用于定位一手来源 | 其 Host 支持列表未经本项目实测，不作为兼容结论 |

## 验证

自动化（本 PR）：

- `tests/test_mcp_apps.py`：默认关闭时无 `_meta.ui`、无资源；开启时绑定与可见性（含 MRTR 与写工具）、`resources/read` 的 MIME 与 `_meta.ui`、文本降级与拒绝结果、配置严格性、HTML 静态安全不变式。
- 全量 `uv run pytest`、`uv run pyright`、`uv build`（wheel 包含 `mcp/ui/result_viewer.html`）。

本地浏览器冒烟（非 Host 实测）：在 headless Chromium 中以 `sandbox="allow-scripts"` + `srcdoc` 的最小测试宿主加载 View，完成 `ui/initialize` 握手，推送含 `<img onerror>` 与 `<script>` 字符串的行：内容按文本显示、无脚本执行、无额外元素，size-changed 正常发送。

尚未完成（合并或开启前需记录）：在真实 Host（例如 VS Code GitHub Copilot、Claude Desktop、ChatGPT 开发者模式）上的实测，需分别记录 Host 版本、协商协议版本、是否渲染、可见性拒绝行为与降级表现。缺少实测不应被表述为兼容通过。
