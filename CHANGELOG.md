# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026-11-17

**三模型与全站 HMI 重做**：三模型收敛 + 语音输入 + 诊断质控 + C HMI 17 路由

### Added

- **三模型收敛**：主模型（对话 + `aux_key` 辅助任务）、嵌入模型、重排模型三槽位；压缩/标题/抽取改走主模型，`deepseek.aux_key` 可独立限流；旧 `small_model` / `background_*` / `subagent_url` 配置自动迁移并备份。
- **联网检索供应商抽象**：DeepSeek 官方搜索（动态 `lang:`）、Tavily（basic/advanced）、自定义 OpenAI 兼容搜索；失败/空结果自动降级，来源与正文进入证据链。
- **语音输入**：浏览器 16 kHz 单声道 WAV 录音 → `/api/asr/transcribe` → 文本回填；支持 DeepSeek 官方 ASR 与 OpenAI 兼容接口；服务端校验时长与上传大小，不落盘、不记录识别文本；前端新增 VoiceButton、录音状态机与 WAV 编码测试。
- **诊断阶段与证据链**：接诊→假设→验证→结论阶段时间线，E1/E2… 证据编号与假设↔证据映射落库；管理员诊断质控页支持阶段/严重度筛选、证据关联率、原文受控查看并写审计。
- **DTC 故障码速查**：店员端精确码表查询 + 知识块兜底 + 厂商专有码提示。
- **车辆档案增强**：里程编辑、完整诊断历史分页（仅摘要/阶段，不含原文）。
- **用量与限额**：搜索/ASR 写 `usage_stats`（次数/时长/成本），支持每用户每日搜索次数、ASR 秒数、全局美元预算；默认三项 `null` 不限制；限额拒绝写审计。
- **superadmin 调试后台扩展**：搜索/ASR 供应商、限额、主模型 `aux_key`、固定密码来源展示与在线修改；配置 GET 全量掩码，PUT 留空保持、`__clear__` 清除。
- **C HMI 设计系统**：17 条路由统一 AppShell / SideNav / TopBar / MobileTabBar，五档宽度适配、打印浅色主题、`prefers-reduced-motion`、44px 触控目标、跳过链接与焦点轮廓。
- **安全加固**：CSP 与安全响应头、HSTS（HTTPS）、KB/ASR 上传体积与类型限制、案例沉淀隐私门槛、限额拒绝审计。

### Changed

- `data/config.json` 升级为 schema v2；启动时自动迁移、备份并原子写回。
- superadmin 密码仅首次生成时打印；env/config 来源不回显。
- 管理端诊断详情新增 `privacy_share_admin` 原文授权，默认仅显示脱敏内容。
- 前端浏览器标题/PWA manifest/包版本统一为 2.1；README / 技术架构 / 操作指南与操作截图同步本轮 UI。

### Fixed

- 零会话状态发送首条消息被静默丢弃；聊天流 401 未清理 token；SSE 内部异常原文回传客户端。
- 检索只召回已完成解析的文档；嵌入缓存按端点与模型隔离；agent 内知识库检索不再阻塞 SSE 事件循环。
- 案例沉淀改为先写入知识库再落案例，嵌入失败可重试；失败文档不再进入证据链。

### Removed

- 旧 `small_model` / `background_*` / `subagent_url` / 顶层 `tavily` 配置节移除，分别并入主模型、嵌入/重排与 `search` 配置。

## [2.0.2] - 2026-10-02

**RAG 检索降级链优化**：jieba 分词词典优化 + 嵌入缓存 + 检索档位日志

### Added

- **检索档位日志**：每次 RAG 检索在服务端日志记录当前降级档位（向量主路 / BM25 关键词降级）、重排是否生效、命中数与耗时，部署者直接看日志即可确认云端服务健康状况。
- **嵌入缓存（LRU）**：相同查询的 embedding 结果在进程内自动复用，追问与同题复查场景不再重复调用云端嵌入接口，检索更快。

### Changed

- **jieba 分词优化**：领域术语（动力电池组、快充口、充电枪、高压配电箱等）与语料中的全部 DTC 故障码加入 jieba 词典，并过滤无意义的虚词与疑问词，BM25 关键词降级路线对术语的字面匹配更准。

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

[2.1.0]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/compare/v2.0.2...v2.1.0
[2.0.2]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/compare/v1.0...v2.0.0
[1.0.0]: https://github.com/EVOL233awa/NEV-AI-Diagnostic-System/releases/tag/v1.0
