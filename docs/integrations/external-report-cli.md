# 外部分析报告 CLI

`SDA` 把本机办公软件的结构化分析结果同步到部署在另一台服务器上的 Smart Data Agent。它只传递报告负载，不依赖本机运行 Smart Data Agent。

## 服务端配置

在 Smart Data Agent 部署服务器创建一个仅服务账户可读的 JSON 文件，例如 `/run/secrets/smart-data-agent-report-ingress.json`（权限 `0600`）：

```json
{
  "bindings": [
    {
      "id": "workbuddy-revan",
      "token": "替换为高强度随机值",
      "channel": "workbuddy",
      "label": "WorkBuddy",
      "tenant_id": "tenant_demo",
      "user_id": "u_admin",
      "visibility": "private"
    }
  ]
}
```

将该文件路径配置给服务进程：

```sh
export SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_FILE=/run/secrets/smart-data-agent-report-ingress.json
```

每一个 binding 固定渠道、租户和报告所有者。CLI 传入的内容不能改变这些归属。为飞书、钉钉等新渠道追加独立 binding 即可。

## 本机 CLI 配置

将 `scripts/SDA` 放入 `PATH`，例如：

```sh
ln -sf /path/to/Smart_Data_Agent/scripts/SDA ~/.local/bin/SDA
mkdir -p ~/.config/smart-data-agent
printf '%s\n' '{"endpoint":"https://your-smart-data-agent.example.com"}' > ~/.config/smart-data-agent/report-cli.json
export SMART_DATA_AGENT_REPORT_TOKEN='与 workbuddy-revan binding 相同的 token'
```

Token 不应写入 JSON 配置、Shell 历史或项目仓库。macOS 上推荐保存到 Keychain；`SDA` 会在未找到环境变量时自动读取这个服务，因此 WorkBuddy 桌面端不需要继承终端环境变量：

```sh
security add-generic-password -U -a "$USER" -s smart-data-agent-report-token -w
```

该命令会安全提示输入 Token；不要把 Token 贴到聊天、脚本或报告 JSON 中。非 macOS 客户端继续使用环境变量或其系统的秘密管理器。

## 发布格式

```json
{
  "source": {"channel": "workbuddy", "run_id": "wb-run-20260806-001"},
  "report": {
    "title": "8月客户流失风险分析",
    "query": "识别高价值客群的流失风险",
    "plan": "按客群、近90天活跃度和AUM变化分层",
    "summary": "高AUM且近30天未互动客群风险最高，应优先进入客户经理跟进名单。",
    "visual_types": {"primary": "bar", "secondary": "table"},
    "rows": [{"客群": "高AUM低活跃", "客户数": 42, "风险分": 86}]
  }
}
```

发布：

```sh
SDA publish --channel workbuddy --input ./workbuddy-report.json
```

重复使用相同 `run_id` 和 `report_id` 会更新同一份报告和其当前数据快照，不会在“我的报告”中创建重复条目。

## WorkBuddy 接入

先用 WorkBuddy 随附 CLI 验证本地插件；它不会修改已安装的插件或读取既有对话：

```sh
WORKBUDDY_CLI="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy"
"$WORKBUDDY_CLI" plugin validate /path/to/Smart_Data_Agent/integrations/workbuddy-smart-data-report
"$WORKBUDDY_CLI" --plugin-dir /path/to/Smart_Data_Agent/integrations/workbuddy-smart-data-report
```

插件的 `bin/SDA` 会自动转发到同一项目中的 CLI；若将插件单独打包，设置 `SMART_DATA_AGENT_REPORT_CLI` 指向已安装 `SDA` 的绝对路径。在该 CLI 会话中使用 `/smart-data-agent-report:publish-analysis`，或在分析请求中明确说“分析完成后同步到 Smart Data Agent”。插件 Skill 会生成受控报告负载并调用 `SDA`；Stop Hook 只检查发布动作是否完成，不读取或上传聊天转录。验证通过后，再通过 WorkBuddy 的插件市场/企业市场发布该插件，供桌面端持续安装和自动更新。

旧命令 `sda-report` 保留为兼容别名；新接入统一使用 `SDA`。

“我的报告”会按 `channel` 显示来源标签，并支持按来源筛选。WorkBuddy 是第一个 adapter；后续办公软件只需生成相同 JSON 契约，并使用其各自的 binding 与 `--channel`。
