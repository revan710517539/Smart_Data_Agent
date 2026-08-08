# WorkBuddy 本机安装与 Smart Data Agent 连通说明

此文档用于将 `smart-data-agent-report` 插件安装到本机 WorkBuddy，并把
WorkBuddy 的结构化分析结果同步到 Smart Data Agent 的“我的报告”。

## 安全边界

- 仅允许传递报告标题、问题、分析方法、结论和图表所需汇总行；不得上传完整对话、原始文件或凭据。
- 报告令牌只从 macOS Keychain 的 `smart-data-agent-report-token` 服务读取；不得打印、复制、写入 JSON、Shell 历史或聊天内容。
- 本机测试使用 `http://127.0.0.1:18787`。服务器部署后必须改为正式 HTTPS 地址。
- 服务器端必须已有固定 `workbuddy` binding；该 binding 决定租户、报告所有者和可见性，客户端不得传入或改写这些归属。

## 让 WorkBuddy 执行的安装步骤

以下命令只安装本机插件和非敏感的服务地址。WorkBuddy 在执行前应先检查命令、路径和插件状态；若某一步失败，停止并报告错误，不要猜测令牌或创建替代凭据。

```sh
set -eu

WORKBUDDY_CLI="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy"
PROJECT_ROOT="/Users/revan/Documents/Smart_Data_Agent"
MARKETPLACE_DIR="$PROJECT_ROOT/integrations/workbuddy-smart-data-report-marketplace"
PLUGIN_NAME="smart-data-agent-report"
MARKETPLACE_NAME="smart-data-agent-local"

"$WORKBUDDY_CLI" plugin validate "$PROJECT_ROOT/integrations/workbuddy-smart-data-report"
"$WORKBUDDY_CLI" plugin validate "$MARKETPLACE_DIR"

if ! "$WORKBUDDY_CLI" plugin marketplace list | grep -q "$MARKETPLACE_NAME"; then
  "$WORKBUDDY_CLI" plugin marketplace add "$MARKETPLACE_DIR" --name "$MARKETPLACE_NAME"
fi

if ! "$WORKBUDDY_CLI" plugin install "$PLUGIN_NAME@$MARKETPLACE_NAME" --scope user; then
  "$WORKBUDDY_CLI" plugin enable "$PLUGIN_NAME"
fi

mkdir -p "$HOME/.config/smart-data-agent"
printf '%s\n' '{"endpoint":"http://127.0.0.1:18787"}' > "$HOME/.config/smart-data-agent/report-cli.json"

security find-generic-password -a "$USER" -s smart-data-agent-report-token >/dev/null
"$WORKBUDDY_CLI" plugin marketplace list
```

安装完成后，需要**重启 WorkBuddy**，让桌面端加载新插件。

## 连通性检查

重启后打开一个 WorkBuddy 分析会话，执行：

```text
/smart-data-agent-report:publish-analysis
```

或直接说明：

```text
完成当前分析后，同步到 Smart Data Agent。只同步标题、问题、方法、结论和用于图表的汇总行，不上传完整对话或原始文件。
```

插件会调用系统 CLI `SDA`：

```sh
SDA publish --channel workbuddy --input <受控报告JSON路径>
```

成功时只反馈报告标题和报告 ID；打开 Smart Data Agent 的“智能分析 → 我的报告”，应出现来源为 `WorkBuddy` 的报告。

## 服务器部署后的替换项

将本机配置中的 endpoint 改为正式服务地址（示例）：

```json
{"endpoint":"https://smart-data-agent.example.com"}
```

部署服务器必须为服务进程配置 `SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_FILE`，其中包含与 Keychain 令牌匹配的 `workbuddy` binding。若缺少 binding、令牌或地址，客户端必须失败关闭，不得伪造报告成功。

## 常见失败

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| WorkBuddy 不认识同步命令 | 插件未安装或未重启 | 重新执行安装步骤并重启 WorkBuddy |
| `endpoint_required` | 缺少 `report-cli.json` | 写入正确的本机或正式服务地址 |
| `token_missing` | Keychain 中没有服务令牌 | 由管理员将令牌安全写入 Keychain |
| 401/403 | 令牌或服务器 binding 不匹配 | 检查服务器 `workbuddy` binding，勿在聊天中暴露令牌 |
| 报告未出现 | 服务端未写入、机构/账号绑定不一致 | 先查看 CLI 返回的报告 ID，再检查“我的报告”的 WorkBuddy 来源筛选 |
