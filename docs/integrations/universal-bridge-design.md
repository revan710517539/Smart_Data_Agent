# Universal Bridge 完整方案

## 目标与用户体验

WorkBuddy、Codex、QWork 分别只安装一次薄客户端。首次安装由工作台读取对应的
macOS 或 Windows 文档、执行安装器并打开一次浏览器授权；用户只点击“允许连接”，
不复制令牌、不配置 URL、租户、账号或 MCP。

以后管理员在 Bridge 服务端登记新系统，既有客户端在下一次任务执行 `systems`
时自动发现，不重新安装、不更新本地系统清单。用户只需自然语言说明系统和意图，
例如“读取业务画布平台的客户策略并分析”或“在业务画布平台新建一个周报画布”。
匹配不到或匹配多个系统时，工作台必须请用户明确选择，不能使用第一项或默认项。

## 架构与权威边界

```text
用户自然语言
  -> WorkBuddy / Codex / QWork 一次安装的薄 Skill/Plugin
  -> SDA Universal Bridge CLI（只保存平台绑定凭据）
  -> Bridge Manifest（服务端动态系统注册表）
  -> 精确 system_id + 四模块请求
  -> SDA 内置适配器 / 后台登记的 HTTP JSON 适配器
  -> 目标系统
```

- 客户端权威：仅保存 endpoint 和当前平台的设备绑定凭据。
- Bridge 权威：绑定用户、租户、工作台渠道、系统清单、能力、动作白名单、审计。
- 目标系统权威：自身业务数据、内容、策略、画布/配置和学习候选生命周期。
- 用户不能从请求体覆盖身份、租户、绑定、目标 URL 或凭据。
- 连接器配置文件只引用服务端环境变量名，绝不保存密钥值。

## 统一四模块协议

| 模块 | 文字意图 | Bridge 操作 | 约束 |
| --- | --- | --- | --- |
| `analysis_sync` | “把分析同步到某系统” | `sync` | 稳定 operation ID；目标系统幂等 |
| `configuration` | “新建画布/修改配置” | `action` | 只能调用 manifest 中的白名单 action |
| `read` | “读取数据/内容/策略并分析” | `context` + `read` | 精确 system/resource；有界结果 |
| `learning` | 分析、同步或配置后的自动回收 | `evidence` | 只形成待复核记忆/Skill 原材料 |

所有会改变状态的请求必须带稳定 `operation_id`。分析同步、配置动作和学习证据
使用同一 ID，便于目标系统幂等、审计和回滚。Bridge 不把候选自动晋升为 active。

## 服务端新增系统

部署管理员复制
`configs/integrations/bridge_connectors.example.json`，设置
`SMART_DATA_AGENT_BRIDGE_CONNECTORS_FILE` 指向实际文件。每个连接器必须完整声明
四个模块、三个允许渠道、HTTPS 地址、配置动作白名单和服务端凭据环境变量名。

注册表在每次 manifest/操作请求时重新读取，因此保存有效配置后，已安装客户端在
下一次任务即可发现。无效 JSON、缺少任一模块、重复 ID、非 HTTPS 外部地址、内嵌
凭据、未知渠道或未知 action 都失败关闭；旧的有效客户端不需要重装。

目标系统的 HTTP 适配器接收 `bridge_request_v1`：

```json
{
  "schema_version": "bridge_request_v1",
  "contract_version": "1.0",
  "system_id": "canvas-platform",
  "module": "configuration",
  "action": "canvas.create",
  "operation_id": "stable-operation-id",
  "identity": {
    "tenant_id": "服务端绑定",
    "user_id": "服务端绑定",
    "channel": "codex",
    "binding_id": "服务端绑定"
  },
  "input": {}
}
```

目标系统必须校验 Bridge 凭据、重复 operation ID、资源/动作权限、数据范围和响应
上限，并把配置变更保留自身审计与回滚记录。

## CLI 稳定入口

```sh
SDA bridge --channel <workbuddy|codex|qwork> systems --json
SDA bridge --channel <channel> context --system <system-id> --json
SDA bridge --channel <channel> read --system <system-id> --resource <resource> --input <json> --json
SDA bridge --channel <channel> action --system <system-id> --action <action> --operation-id <id> --input <json> --json
SDA bridge --channel <channel> sync --system <system-id> --operation-id <id> --input <json> --json
SDA bridge --channel <channel> evidence --system <system-id> --operation-id <id> --input <json> --json
```

原有 `SDA publish`、`SDA workbuddy context/data/evidence` 和未带 `--system` 的 SDA
命令保留为兼容入口，但新工作流必须使用 manifest 和精确 system ID。

## 安全、失败与回滚

- 每个平台使用独立设备绑定和独立 Keychain/DPAPI 槽位，不能交叉复用。
- macOS 使用 Keychain；Windows 使用当前用户 DPAPI 密文。
- 数据读取、外部响应和证据均有硬上限；禁止对话全文、原文件、凭据和原始未用行。
- 系统不存在、渠道不允许、动作不在白名单、schema 变化、依赖不可用时失败关闭。
- 回滚新系统只需从服务端注册表禁用或移除该连接器；客户端无需卸载。
- 回滚 Bridge 客户端时删除对应 Skill/Plugin、CLI 链接和本地绑定凭据；不影响目标
  系统业务数据。

## 验收矩阵

1. 六个安装文档：三工作台 × macOS/Windows，每个含一段可粘贴安装指令。
2. 一次设备授权后，manifest、SDA context/read/sync/evidence 均可用。
3. 在临时服务端注册表加入第二个系统后，同一 CLI 不重装即可发现并调用四模块。
4. 配置动作白名单、渠道隔离、错误 system/action、缺 operation ID 和内嵌凭据均被拒绝。
5. SDA 分析与配置证据仅生成 review-only 候选；不产生 active 记忆或 Skill。
6. macOS Shell、Windows PowerShell/DPAPI 契约、WorkBuddy 插件、Python、API、类型和
   构建验证全部通过后才能关闭任务。
