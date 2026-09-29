# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-28

从 1.0 纯前端原型迭代至 2.0 全栈系统：整体重构为前后端一体架构，诊断引擎升级为服务端 Agentic RAG，新增三级角色业务闭环。完整介绍见 [README](README.md)。

### Added

- **FastAPI 后端**：单进程同时提供 `/api/*` 与前端静态托管（SPA fallback），SQLite 持久化，`main.py` 一条命令启动。
- **三端前端**：重写为 Vue 3 + TypeScript + Element Plus（车主 / 店员 / 管理员），PWA、手机/桌面自适应。
- **三层记忆**：上下文自动压缩、会话诊断状态卡（本地小模型异步抽取初稿、生成会话标题，不可用时自动跳过）、跨会话车辆档案、案例自动入库并纳入检索。
- **预约工单闭环**：诊断卡一键预约 → 店员接单/改约 → 回填维修结果 → 沉淀案例 → HTML 打印报告，全流程状态机约束。
- **商用基础**：JWT 四角色接口级鉴权（owner / staff / admin / superadmin）、成员管理、统计看板、审计日志、多租户数据隔离。
- **受控追问**：AI 信息不足时以卡片列出问题（选项点选 + 自由输入 + 「不知道」兜底），未答提问随会话保存、离线续答。
- **联网核实**：Tavily 检索工具（Key 缺失自动禁用，不影响其余功能）。
- **superadmin 调试后台**：新增第四种角色 `superadmin`（仅部署者），首次启动自动建号，20 位随机字母数字密码**每次启动后端进程都打印到该进程的终端窗口**（明文仅存服务器本机 config.json 的 superadmin 节，与 API Key 同一密钥宿主，不进仓库/数据库/接口响应）；`python main.py --reset-superadmin` 可随时重新生成。`/superadmin` 配置页在线修改模型供应商（主对话 / 后台 / 嵌入槽位的地址、模型、Key，Tavily Key，本地小模型/重排地址，Key 单向掩码、留空不改）与 Agent 运行参数（单轮工具轮数、追问上限、max_tokens、temperature、工具结果截断、压缩双阀门四参数、首轮 `tool_choice` 硬强制检索），除网络配置外保存即热生效；admin 成员管理对 superadmin 完全隔离。
- **测试**：pytest 回归 84 例（临时数据库离线运行）+ 前端 vue-tsc 严格类型检查。

### Changed

- 知识库嵌入支持远端 OpenAI 兼容 API：`local_models.embedding_key` 非空时嵌入请求携带 Bearer 认证（`embedding_url` 不含 `/v1`，误配尾缀自动去除）。默认配置切换为硅基流动 `BAAI/bge-m3`（实测 1024 维、单条 P50 约 150-190ms、batch=64 均摊约 25ms/条）；嵌入服务不可达时仍自动退化为纯关键词检索，行为不变。
- **诊断引擎**：场景识别 + 规则引擎 + 浏览器内置知识库 → 服务端 Agentic RAG：知识按文档结构分段入库，检索时 bge-m3 向量与 jieba/BM25 关键词双路融合排序（内置知识库 300+ 条，附检索质量自检脚本）；模型通过 function calling 自主决定工具调用（知识检索 / 故障码 / 联网核实 / 车辆档案 / 向用户追问，最多 6 轮），SSE 流式输出结构化诊断卡（严重度 + 可能原因 + 检修步骤 + 待确认项）。
- **联网检索来源治理**：可信域加权上浮、内容农场下沉、零价值域（财经行情/搜索结果页/文档农场）硬剔除；仅联网单源支撑的判断降格为「待确认项」，不进诊断结论。

### Removed

- 浏览器 localStorage 明文 API Key。
- 前端内置静态知识库与规则引擎。
- 纯前端「预约检修引导」占位入口（由真实预约工单闭环取代）。

### Fixed

- 联网检索结果排序反转：内容农场被错误上浮至结果首位（排序键逻辑与意图相反）。
- 店员端与管理员端无法自助修改密码（此前仅车主端菜单可达）：店员端首页补「设置」入口；管理员端成员与角色管理新增「改密码」，可对任意成员（含自己）直接设置新密码，原有「重置为账号名」保留。

### Security

- 全部密钥（DeepSeek / Tavily / JWT secret）移入服务端 `data/config.json`，不进仓库、不下发前端、不写日志。
- PBKDF2-SHA256 密码哈希；登录失败限速锁定；跨账号资源一律按 404 处理不泄露存在性；对话原文仅在车主开启分享开关后随工单可见（后端 403 强制）。

## [1.0.0] - 2026-09-25

纯前端原型：单页应用（HTML/CSS/Vanilla JS）在浏览器内直接调用 LLM API，API Key 与会话记录存于 localStorage；内置静态知识库 + 场景识别 + 规则引擎提供检索问答；含「预约检修引导」占位入口。

[2.0.0]: https://github.com/EVOL233awa/AI-powered-New-Energy-Vehicle-Diagnostic-Assistant/compare/v1.0...v2.0.0
[1.0.0]: https://github.com/EVOL233awa/AI-powered-New-Energy-Vehicle-Diagnostic-Assistant/releases/tag/v1.0
