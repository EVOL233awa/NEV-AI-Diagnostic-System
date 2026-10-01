# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-10-02

RAG 检索质量优化小版本：云端重排接入 + 修改config默认项 + superadmin调试后台增加更多配置项

### Added

- **云端重排**：知识库检索在向量召回后新增重排环节——云端重排模型对召回结果按与问题的相关性重新排序，让最相关的资料排在最前面，诊断回答的依据更准；重排服务不可用时自动保持原有顺序，检索不中断。
- **小模型槽位**：会话标题与诊断状态卡抽取改为独立配置的云端小模型，不配置时自动回退主聊天模型，云服务器部署不再依赖本地模型；小模型默认关闭思考模式，响应更快。
- **superadmin 调试后台新增配置项**：重排开关与重排模型、小模型槽位的地址、模型、Key 及温度、输出上限等参数全部支持在线配置，保存即生效，并新增重排与小模型的「测试连接」。

### Changed

- config 默认配置指向硅基流动云端（嵌入与重排均有免费模型，检索链路 API 账单为 0），并推荐用户注册接入；本地 llama-server 部署降为可选形态说明。

## [2.0.0] - 2026-09-28

从 1.0 纯前端原型迭代至 2.0 全栈系统：整体重构为前后端一体架构，诊断引擎升级为服务端 Agentic RAG，新增三级角色业务闭环。完整介绍见 [README](README.md)。

### Added

- **FastAPI 后端**：单进程同时提供 `/api/*` 与前端静态托管（SPA fallback），SQLite 持久化，`main.py` 一条命令启动。
- **三端前端与调试后台**：重写为 Vue 3 + TypeScript + Element Plus，车主 / 店员 / 管理员三端一体，PWA、手机/桌面自适应；另附部署者专属 `superadmin` 调试后台（`/superadmin` 配置页在线修改模型供应商槽位与 Agent 运行参数，保存即热生效，Key 单向掩码、对 admin 完全隔离；首次启动自动建号，随机密码打印到后端终端）。
- **三层记忆**：上下文自动压缩、会话诊断状态卡（主模型经 `update_case_notes` 工具自主维护，本地小模型异步抽取初稿、生成会话标题，不可用时自动跳过）、跨会话车辆档案、案例自动入库并纳入检索。
- **预约工单闭环**：诊断卡一键预约 → 店员接单/改约 → 回填维修结果 → 沉淀案例 → HTML 打印报告，全流程状态机约束。
- **商用基础**：JWT 四角色接口级鉴权（owner / staff / admin / superadmin）、成员管理、统计看板、审计日志、多租户数据隔离。
- **受控追问**：AI 信息不足时以卡片列出问题（选项点选 + 自由输入 + 「不知道」兜底），未答提问随会话保存、离线续答。
- **联网核实**：Tavily 检索工具（Key 缺失自动禁用，不影响其余功能）。
- **测试**：pytest 回归 84 例（临时数据库离线运行）+ 前端 vue-tsc 严格类型检查。

### Changed

- 知识库嵌入支持远端 OpenAI 兼容 API：`local_models.embedding_key` 非空时嵌入请求携带 Bearer 认证（`embedding_url` 不含 `/v1`，误配尾缀自动去除）。默认配置切换为硅基流动 `BAAI/bge-m3`（实测 1024 维、单条 P50 约 150-190ms、batch=64 均摊约 25ms/条）；嵌入服务不可达时仍自动退化为纯关键词检索，行为不变。
- **诊断引擎**：场景识别 + 规则引擎 + 浏览器内置知识库 → 服务端 Agentic RAG：知识按文档结构分段入库，检索以 bge-m3 向量为主路、jieba/BM25 关键词路降级保底（内置知识库 300+ 条，附检索质量红绿闸门自检脚本）；模型通过 function calling 自主决定工具调用（知识检索 / 故障码 / 联网核实 / 车辆档案 / 向用户追问，最多 6 轮），SSE 流式输出结构化诊断卡（严重度 + 可能原因 + 检修步骤 + 待确认项）。
- **联网检索来源治理**：可信域加权上浮、内容农场下沉、零价值域（财经行情/搜索结果页/文档农场）硬剔除；仅联网单源支撑的判断降格为「待确认项」，不进诊断结论。

### Removed

- 浏览器 localStorage 明文 API Key。
- 前端内置静态知识库与规则引擎。
- 纯前端「预约检修引导」占位入口（由真实预约工单闭环取代）。

## [1.0.0] - 2026-09-25

纯前端原型：单页应用（HTML/CSS/Vanilla JS）在浏览器内直接调用 LLM API，API Key 与会话记录存于 localStorage；内置静态知识库 + 场景识别 + 规则引擎提供检索问答；含「预约检修引导」占位入口。

[2.0.1]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/compare/v1.0...v2.0.0
[1.0.0]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/releases/tag/v1.0
