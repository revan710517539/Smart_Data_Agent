# Hermes 风格自学习改造验收记录

首次验收：2026-07-24
当前复核：2026-07-30

## 需求覆盖

| 需求 | 当前实现 | 验收证据 |
|---|---|---|
| 改造前先梳理功能与流程 | 固化页面、业务流、数据、API、测试及保护哈希 | `docs/current_version_functional_baseline.md` |
| 以 Hermes Agent 为主要参考 | 操作/分析轨迹、程序性 Skill、按需装载、使用反馈、受控写入 | `backend/platform/learning/service.py` |
| 以 self-evolution 为补充 | 重复轨迹触发候选、约束门禁、失败反思生成新版本、人工审核 | `SkillLearningLoopTest` |
| 页面结构不变 | 没有修改路由和导航文件 | 两个保护文件 SHA-256 与基线一致 |
| 原功能和内容保持 | 原 API 数、业务库、CSV 文件集合和核心实体计数不变 | 不变性与临时迁移副本检查 |
| 用户操作形成自学习 | API 审计事件和分析复核结果进入学习服务 | `observe_operation` / `observe_analysis_result` |
| 用户操作生成 Memory | 三次同类成功操作生成脱敏 `behavior_habit` 候选，审核前不召回 | HTTP 页面操作与 Memory 生命周期测试 |
| 生成 Skill 后下一轮应用 | 仅审核为 `active` 的用户级 Skill 在下次请求边界装载 | 完整分析工作流测试 |
| 生成 Memory 后下一轮应用 | 仅审核为 `active` 的用户级 Memory 在同类操作和后续分析中召回 | 操作闭环与分析召回测试 |
| 数据分析 Skill | `data.analysis.profile` | Skill Registry 健康检查和结果剖析测试 |
| 结论生成 Skill | `conclusion.generate` | 事实/解释/行动契约与证据哈希测试 |
| BI 报表 Skill | `bi.report.generate` | 可审计报告规格、默认不发布测试 |
| 数据治理 Skill | `data.governance.assess` | 完整性、重复、敏感字段、发布边界测试 |

## 学习闭环

```text
用户操作 / 分析结果
  -> 脱敏审计轨迹
  -> 重复模式识别
  -> behavior_habit Memory（candidate）+ analysis_skill（review）
  -> 四眼审核
  -> active Memory / Skill
  -> 下一轮请求按用户 + 意图 + 数据集匹配
  -> 页面操作记录应用 + 分析计划实际装载
  -> 最终复核反馈
  -> 失败时生成待审核改进版本，旧 active 版本继续服务
```

学习层不执行任意代码、不修改权限、不覆盖指标口径、不在会话中途切换 Skill。学习失败被隔离，不回滚原业务操作。

## 不变性结果

- 页面路由 `src/app/routes.ts`：`000cd9efdedf9e2a61f5ec8b34588147baf0920b912269c3cafa724f19284fd5`
- 导航结构 `src/app/components/Layout.tsx`：`2c703b41a7b926bba70d99106b21eab91b168bcde046533e11a760771414aea8`
- API 路由：122
- 正式 SQLite：`18d406aa9694fe64fbe5f0fd6edd958c78985d4c10bae62c2b199d9023548c01`
- `data/` 文件集合：`e0109dc99df7825bde1c79c4e8b7c7bdb281b5604ed591f52f75f3bb56d99469`
- 既有内容：原始表 4、主题表 8、分析 Skill 12、自动化任务 1、审计事件 123
- 既有 Memory：14 条候选记录；本轮测试均使用内存或临时数据库，正式库未新增学习候选
- 临时数据库升级前后计数：`4,8,12,1,123`，保持一致
- CSV 文件夹继续供数，定向爬取任务保持暂停

## 测试结果

- 后端全量：302 项通过，4 项按既有环境条件跳过
- 学习闭环：6 项通过；连同既有 Memory 生命周期共 10 项聚焦测试通过
- 真实 HTTP 页面操作：连续三次成功交互自动形成待审核 Memory 与 Skill，交互选择值未进入 Memory
- TypeScript：通过
- 前端组件体积：通过
- API 客户端生成契约：通过
- Vite 生产构建：通过
- 前端权限真实浏览器冒烟：通过
- 右侧分析栏契约：48 项通过
- `git diff --check`：通过
- 本轮临时测试服务已退出；当前 5173/8787 是改造前已运行的 `AI营销官/模拟器`，工作目录和健康服务均已回读确认，本任务未启动、停止或修改该运行实例
