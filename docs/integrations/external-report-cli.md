# 外部分析报告 CLI

`SDA` 把本机办公软件的结构化分析结果同步到部署在另一台服务器上的 Smart Data Agent。它只传递报告负载，不依赖本机运行 Smart Data Agent。

## 默认：浏览器一次点击绑定

客户端执行 `SDA connect --channel <workbuddy|codex|qwork>` 后，服务端生成十分钟有效的设备授权码。CLI 自动打开 SDA 授权页；当前登录用户点击一次“允许连接”，CLI 随即一次性领取渠道绑定并写入 Keychain 或 DPAPI。服务端只保存令牌 SHA-256，不返回或显示给浏览器；授权码过期、重复领取、校验器不匹配、跨渠道使用都会失败关闭。绑定固定当前用户、当前租户、渠道和设备名，可由该用户撤销。

```sh
SDA connect --channel workbuddy
SDA connect --channel codex
SDA connect --channel qwork
```

## 可选：管理员静态绑定兼容模式

离线设备或禁止浏览器授权的环境仍可在部署服务器创建仅服务账户可读的 JSON 文件，例如 `/run/secrets/smart-data-agent-report-ingress.json`（权限 `0600`）：

```json
{
  "bindings": [
    {
      "id": "workbuddy-revan",
      "token": "替换为独立高强度随机值-1",
      "channel": "workbuddy",
      "label": "WorkBuddy",
      "tenant_id": "tenant_demo",
      "user_id": "u_super_admin",
      "visibility": "private"
    },
    {
      "id": "codex-revan",
      "token": "替换为独立高强度随机值-2",
      "channel": "codex",
      "label": "Codex",
      "tenant_id": "tenant_demo",
      "user_id": "u_super_admin",
      "visibility": "private"
    },
    {
      "id": "qwork-revan",
      "token": "替换为独立高强度随机值-3",
      "channel": "qwork",
      "label": "QWork",
      "tenant_id": "tenant_demo",
      "user_id": "u_super_admin",
      "visibility": "private"
    }
  ]
}
```

将该文件路径配置给服务进程：

```sh
export SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_FILE=/run/secrets/smart-data-agent-report-ingress.json
```

每一个静态 binding 同样固定渠道、租户和报告所有者，且三个渠道使用不同令牌。CLI 传入的内容不能改变这些归属。静态模式不是六份一键接入文档的默认用户流程。

## 本机 CLI 配置

将 `scripts/SDA` 放入 `PATH`，例如：

```sh
ln -sf /path/to/Smart_Data_Agent/scripts/SDA ~/.local/bin/SDA
mkdir -p ~/.config/smart-data-agent
printf '%s\n' '{"endpoint":"https://your-smart-data-agent.example.com"}' > ~/.config/smart-data-agent/report-cli.json
```

Token 不应写入 JSON 配置、Shell 历史或项目仓库。`SDA connect` 在 macOS 自动写入渠道专用 Keychain 项，在 Windows 自动写入当前用户 DPAPI 密文；用户不会看到、复制或输入 Token。WorkBuddy、Codex、QWork 的六份安装文档都调用这条流程。

## SDA 与 WorkBuddy、Codex、QWork 的受控双向数据引用

原始 CSV 仍由 Data Crawler 管理，SDA 和三个 Bridge 客户端都不会编辑 CSV。SDA 的“数据管理 → 原始表”在每条数据表的操作按钮前提供“外部引用”下拉框：默认`单独使用`；选择`可分享`后，SDA 才为该租户、该逻辑数据源授权 WorkBuddy、Codex 或 QWork 读取。授权保存在 SDA 策略库，不会写入 CSV；如果 CSV 字段结构改变，授权自动失效并回到单独使用，需重新确认。

每个客户端只可通过自己的 channel binding 调用下列命令。下面以 WorkBuddy 兼容命令为例；Codex/QWork 使用 `SDA bridge --channel <codex|qwork> ...`：

```sh
# 获得当前绑定账户可用的共享表元数据、已生效记忆和已生效 Skill
SDA workbuddy context --json

# 按 sourceKey 读取最多 500 行和最多 50 列的受控数据投影
SDA workbuddy data --source-key <sourceKey> --columns "机构,金额" --limit 200 --json

# 将去标识化的分析摘要回传为“待复核”记忆/Skill 学习材料
SDA workbuddy evidence --source-key <sourceKey> --input ./workbuddy-evidence.json
```

`evidence` 需要绑定当前 `schema_fingerprint`、稳定 `run_id`、摘要、方法和可选指标/维度。SDA 自动保存候选记忆并在重复、同类的受控证据达到既有阈值后生成待复核 Skill 候选；候选永不自动生效。

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

插件的 `bin/SDA`（Windows 为 `bin/SDA.cmd`）会调用插件内置的 Python CLI，因此从 WorkBuddy 的版本化缓存加载时也可工作。`SMART_DATA_AGENT_REPORT_CLI` 仍可用于显式覆盖为受控的绝对路径。在该 CLI 会话中使用 `/smart-data-agent-report:publish-analysis`，或在分析请求中明确说“分析完成后同步到 Smart Data Agent”。插件 Skill 会生成受控报告负载并调用 `SDA`；Stop Hook 只检查发布动作是否完成，不读取或上传聊天转录。验证通过后，再通过 WorkBuddy 的插件市场/企业市场发布该插件，供桌面端持续安装和自动更新。

旧命令 `sda-report` 保留为兼容别名；新接入统一使用 `SDA`。

“我的报告”会按 `channel` 显示来源标签，并支持按来源筛选。WorkBuddy、Codex、QWork 使用同一份报告和证据契约，但各自使用独立 binding 与 `--channel`，不能交叉复用凭据。
