---
name: smart-data-agent-bridge
displayName: 通用系统 Bridge
description: 通过一次安装的通用 Bridge 动态发现后台系统，读取授权数据/内容/策略，同步分析结果，执行白名单配置动作，并自动回传待复核记忆与 Skill 原材料。
qwork_local_created: true
---

# QWork 通用系统 Bridge

macOS 使用 `$HOME/.local/bin/SDA`，Windows 使用
`%LOCALAPPDATA%\SmartDataAgentBridge\bin\SDA.cmd`；所有命令传入
`--token-keychain-service smart-data-agent-bridge-qwork`。

Bridge 只安装一次。每个涉及后台系统的任务开始时，先执行
`SDA bridge --channel qwork systems --json`，根据 `id`、`label` 或
`aliases` 精确匹配系统。不得选择第一项、默认系统、猜测租户/URL/路径/凭据；没有
匹配或匹配多个系统时必须请用户明确选择。

所有系统统一使用四个模块：

1. 分析同步：完成分析后，以稳定运行 ID 调用
   `sync --system <id> --operation-id <id> --input <file>`。
2. 后台配置：新建画布、更新配置等只允许调用清单中登记的 action，使用
   `action --system <id> --action <name> --operation-id <id> --input <file>`。
3. 读取使用：先执行 `context --system <id>`，再通过
   `read --system <id> --resource <name> --input <file>` 读取授权的数据、内容和策略。
   SDA 原始表必须使用准确 `source_key`、必要字段且单次不超过 500 行。
4. 学习回收：分析、同步或配置成功后，自动使用相同 operation ID 执行
   `evidence --system <id> --operation-id <id> --input <file>`。回传内容只能成为待复核
   记忆/Skill 候选，不能自动激活。

回传可包含准确引用、实际使用字段、问题、方法、逻辑步骤、发现、假设和限制；禁止
包含对话全文、原始/未使用数据行、原文件、凭据、本地路径或身份覆盖字段。成功后
删除临时包，只反馈目标系统、结果 ID 和候选接收状态。

管理员以后在服务端 Bridge 注册新系统时，本 Skill 会在下一次任务自动发现；不得
要求用户重装或修改 Bridge。
