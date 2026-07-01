# dev-chunteng 分支交接说明

这份文档用于 AgentCore 架构分支的 merge / handoff。后续如果要把产品原型分支的功能合进来，或者让另一个 Codex session 读取上下文后做 merge，应该先读这份文档。

## 分支目的

`dev-chunteng` 是 3D-RAMS 的 AgentCore-centered 架构分支。

这个分支的目标不是继续维护旧的 standalone FastAPI backend，而是把产品 demo 迁到已经确定的 ASI/ASI:ONE + AgentCore 拓扑：

```text
ASI / AgentVerse entry
  -> asi_one_entry_agent
  -> rams_supervisor_runtime
  -> Harness subagents / shared tool packages
  -> run + structuredReport + delivery
  -> 按 caseId 关联的报告持久化
  -> 前端 visualization / report lookup
```

Evan 可以继续独立推进产品原型。这个分支应该持续吸收稳定下来的产品能力，但不应该把 prototype-only backend route 形状保留成长期 canonical contract。

## 这个分支已经完成了什么

- 从旧的 standalone FastAPI backend 方向，迁到 AgentCore-centered 项目结构。
- 新增 `app/asi_one_entry_agent`，作为 ASI/AgentVerse 风格的 entry runtime。
- 新增 `app/rams_supervisor_runtime`，作为 supervisor runtime，负责 orchestration、structured report、evidence/trace、review boundary 和 persistence。
- 将可复用 tool logic 整理到 AgentCore/Harness 更合适的位置。
- 建立 geospatial、planning、hazard、annotation、briefing、review 等 Harness/subagent 结构。
- 加入 supervisor planning 层。planner 可以是 deterministic/mock-backed，但不能被省略。
- 统一报告 payload 到 `run`、`structuredReport`、`delivery`、`caseId`。
- 加入通过 entry/proxy 路径进行的 case-correlated report lookup。
- 在 `agentverse/` 下加入 AgentVerse/ASI adapter 和 signed proxy。
- 前端通过 `VITE_CLOUD_ENTRY_PROXY_URL` 走云端 entry proxy。
- 前端加入 Bedrock 开关；显式 debug FieldBrief 路径现在默认 `useBedrock: true`，仍可通过开关跑 no-Bedrock smoke。
- 新增/整理 AgentCore/ASI 相关 ADR，到 ADR 0016。
- 修复 hosted proxy 的 CORS 问题：Lambda Function URL 已配置 CORS 时，Lambda response 不再重复写 CORS header。
- 已验证 hosted no-Bedrock path 可以到 entry runtime，启动 supervisor runtime，调用 Harness subagents，存储 report，并渲染 case page。

## 当前重要状态

当前 cloud demo 适合证明 workflow shape，不代表最终报告质量已经完成。

已知当前行为：

- 前端 FieldBrief ASI simulation 是 ASI/ASI:ONE entry 的 development/debug substitute，不是生产用户入口。
- Hosted demo 默认应保持 `Use Bedrock` 关闭，除非专门测试 Bedrock path。
- Supervisor 可以在 `agentcore-harness` 模式下运行，并返回 visualization-ready payload。
- Fixture-backed 和 fallback-normalized 数据仍然可以用于第一阶段 smoke。
- 部分 Harness 输出还没有完全归一化成理想的一等 report 字段。
- Risk Review 面板目前读取 `run.hazards`。如果 Harness run 把可展示的风险信息放在 `structuredReport.findings`、evidence、annotations 或 normalized briefing output 里，而 `run.hazards` 为空，UI 就会显示空态。这应当视为字段映射/归一化缺口，而不是 orchestration 没跑。

## 还没有完成的事项

- LLM-first entry-agent 对话体验还没有完整完成。
- AgentVerse 普通 chat 体验需要更干净，不能在正常用户回复里暴露 raw JSON。
- ASI/ASI:ONE identity-bound report access 现在已有初始 `reportAccess` contract、hashed store binding，以及 denied/expired/wrong-user lookup 覆盖；真实 ASI-issued identity artifact 仍需集成。
- Material ingestion 目前仍主要是 metadata/reference 方向；真实 authorized material retrieval 和 extraction 还要补。
- Report persistence 已支持 report lookup，并存储 report-access binding metadata；evidence summaries、material citations 和长期 authorization records 还要扩展。
- Harness subagent 输出需要更严格的 schema，避免 supervisor 对常见字段做 fallback normalization。
- Risk Review UI 需要从 `run.hazards`、`structuredReport.findings`、annotations、evidence-backed candidate findings 做稳健映射。
- Bedrock-enabled path 还需要 hardening；在 Bedrock smoke 稳定前，稳定 demo path 应保持 no-Bedrock。
- Hosted smoke 应 formalize 成脚本，验证 AgentCore + ASI 拓扑，而不是旧 FastAPI route names。
- Tavily/open-web subagent 仍是计划扩展，不是默认完成路径。

## 核心边界

Canonical product architecture 是：

- ASI/AgentVerse 是真实用户入口。
- 前端 FieldBrief ASI simulation 是 development/debug ASI entry surface。
- `asi_one_entry_agent` 负责 intake、clarification、user confirmation、supervisor launch、delivery summary 和 report lookup coordination。
- `rams_supervisor_runtime` 负责 planning、orchestration、Harness/subagent dispatch、evidence/trace assembly、structured report generation、review/safety boundary 和 persistence。
- Harness subagents 负责各自专业角色的分析步骤，并应向 supervisor 输出 schema-stable payload。
- 如果 tools 会被多个 subagent/Harness 使用，就不应该被限制在 supervisor runtime 内部。
- Signed proxy 只负责 transport：签名和转发 AgentCore runtime invocation；它不能变成产品 orchestration backend。

## Hard Rules

- 不要恢复旧 `backend/` FastAPI service 作为 product runtime。
- 不要把 `/api/chat`、`/api/run`、`/api/session/start`、`/api/upload-url` 做成 canonical contracts。
- 不要绕过 `asi_one_entry_agent` 做 intake，也不要绕过 `rams_supervisor_runtime` 做 report generation。
- 不要把前端 FieldBrief ASI simulation 变成第二套生产入口。
- 不要把 `caseId` 当 secret access token。它只是 correlation id；report access 后续必须绑定 identity/case authorization。
- 不要让 3D-RAMS 长期拥有 raw product upload storage。Materials 应由 ASI/ASI:ONE 拥有；3D-RAMS 接收 authorized material references，并只在授权边界内 retrieve/extract。
- 不要提交 AWS credentials、runtime ARNs、access keys、AgentVerse secrets、private client material 或 private planning notes。
- 不要声明 certified RAMS、emergency guidance、legal approval 或 approval-to-work。
- 不要移除 no-AWS local verification path。Demo1 必须在没有 cloud credentials 的情况下仍可运行。
- 不要让 planner 变成可选项。它可以 deterministic/mock-backed，但 supervisor path 仍然必须经过 planning。

## Evan 原型协作方式

Evan 可以继续快速推进产品原型、UX、功能验证和 demo polish。原型开发不需要等 AgentCore 迁移。

当 Evan 增加或修改产品能力时，最有用的 handoff 是说明：

- 支持什么用户动作或 workflow；
- intended request payload 形状；
- intended response payload 形状；
- 值得保留的 frontend state 和 copy；
- 哪些数据应该进入 `run`、`structuredReport`、`delivery`、persistence 或 evidence/material records；
- 这个功能是 fixture-only、fallback、live 还是 cloud-required。

AgentCore 分支应该迁移产品意图和稳定 UX 行为，不一定迁移临时 backend route 形状。

建议协作流程：

1. Evan 先在产品原型线上快速验证 UX/capability。
2. Evan 给出 intended payload、result 和 state model。
3. Chunteng 把行为映射进 AgentCore entry/supervisor/report contracts。
4. AgentCore 等价能力完成后，旧 prototype-only backend assumptions 可以标记 obsolete 或删除。

## Merge 指引

从其他分支合并到 `dev-chunteng` 时：

- 保留 AgentCore 目录结构和 ownership boundaries；
- 把有价值的 frontend/report UI 改进迁移到当前 frontend，但不要重新引入 FastAPI dependency；
- 把 chat/session/upload 概念映射到 ASI/AgentVerse entry contract 和 material-reference contract；
- route-level compatibility 只能作为明确标记的 local/debug adapter；
- 优先做 capability-level smoke，不要依赖旧 endpoint name smoke；
- 如果架构决策改变，应同步更新 ADR 或 handoff doc。

## 验证要求

在分享、demo 或 merge 前：

- practical 时运行 `bash scripts/check-demo.sh`；
- 对改动过的 runtime packages 跑 focused tests；
- UI 变化需要跑 frontend build；
- cloud wiring 变化需要 smoke hosted proxy 和 frontend；
- 明确标注哪些组件是真实、mocked、fixture-backed、fallback-normalized 或 future work；
- 确认没有加入 secrets 或 private material。
