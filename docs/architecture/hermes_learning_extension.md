# Hermes 风格自学习与 Skill 演化扩展

## 定位

本项目不嵌入或复制 Hermes Agent 运行时，而是在现有 Smart Data Agent 架构上复用其核心设计：

- 参考 `NousResearch/hermes-agent`：会话/操作经验、程序性 Skill、后台学习、按需装载、使用记录、受控写入和可恢复生命周期。
- 参考 `NousResearch/hermes-agent-self-evolution`：候选变体、执行轨迹评测、约束门禁、最佳候选和人工审核。

Smart Data Agent 的页面、业务模块、数据资产和 API 仍是主系统。学习层只是增量控制面。

Hermes 主仓当前内置的数据科学能力以通用 Jupyter Live Kernel 为主，并没有可直接复制到本项目的数据治理、银行分析结论或 BI 报表 Skill。为保持现有数据契约和权限边界，本项目复用 Hermes 的 Skill 机制、按需装载和学习生命周期，四个数据产品 Skill 则按 Smart Data Agent 的受治理查询结果重新实现；不把可执行任意 Python 的 Notebook 运行时引入生产分析链。

## 目标架构

```text
现有页面与 API
    │
    ├── 原业务 Service / Store / Workflow（保持）
    │
    └── 已脱敏用户操作与分析结果
             │
             ▼
       Learning Service
       ├── 操作模式观察
       ├── 分析轨迹聚合
       ├── Memory / Skill 候选生成
       ├── 约束与语义门禁
       └── 使用/效果反馈
             │
             ├───────────────┐
             ▼               ▼
       现有 MemoryService   现有 Data Asset Store
       ├── behavior_habit    ├── analysis_skill / review
       ├── candidate         ├── 版本记录
       ├── 四眼审核          ├── 四眼审核
       └── active 才召回     └── active / rejected / archived
             │
             ▼
       下一轮 Analysis Workflow
       ├── 只读取 active Memory / Skill
       ├── 自动匹配用户、意图与数据集
       ├── 装载程序性指导
       └── 输出 applied Memory / Skill 证据
```

## 安全边界

1. 学习失败不得影响原业务请求。
2. 学习事件只保存审计级脱敏元数据，不复制凭证、SQL 正文、客户明细或大块业务内容。
3. 自动生成的 Memory 必须先成为 `candidate`，Skill 必须先进入 `review`，均不得直接成为 `active`。
4. 生成者不能审核自己的 Memory 或 Skill，沿用现有四眼审核。
5. 只有 `active` Memory 和 `active + enabled` Skill 才能进入下一轮操作或分析。
6. 操作 Memory 只保存动作编码、目标类型和不可逆哈希，不保存交互正文、选择值或客户标识。
7. 自学习 Skill 只提供分析步骤、展示偏好和观点约束，不直接执行任意代码、不放宽权限、不替换指标口径。
8. 内置基础 Skill 固定在代码与配置中；学习层只能创建用户级 Memory 和租户级分析 Skill，不修改页面和核心执行器。

## Skill 演化门禁

候选或优化版本必须同时满足：

- 至少两次同类成功分析或三次同类用户操作作为证据；
- 完整内容不超过 15KB；
- 必填字段、触发条件和来源轨迹齐全；
- 不包含凭证、危险命令、任意代码或越权指令；
- 保留原始意图、数据集和风险边界；
- 以新版本进入审核，不在会话中途替换已加载版本；
- 审核通过后才供下一轮请求使用。

## 内置数据能力 Skill

- `data.analysis.profile`：对受治理查询结果做描述性分析与结构化剖析。
- `conclusion.generate`：根据证据、指标、维度和治理结果形成事实/解释/行动分层结论。
- `bi.report.generate`：生成可审计的 BI 报告规格，不直接伪造页面或发布状态。
- `data.governance.assess`：检查完整性、重复、敏感字段、执行模式和证据可发布条件。

上述 Skill 均经过现有 `SkillExecutor` 的权限、输入输出校验、超时和追踪边界执行。
