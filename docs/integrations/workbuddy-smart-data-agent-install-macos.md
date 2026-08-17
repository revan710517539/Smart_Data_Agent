# WorkBuddy macOS 接入 SDA Universal Bridge

## 管理员分享前只做一次

把 `https://SDA_SERVER` 替换为本组织真实、可登录、证书有效的 SDA HTTPS 根地址，再把下面整段交给用户。安装来源、授权页、数据服务必须同域；不得分发维护者源码路径或 localhost 地址。

## 直接粘贴给 WorkBuddy 的一段话

```text
请为当前 macOS 用户安装一次 Smart Data Agent Universal Bridge，渠道必须是 workbuddy，服务端根地址是 https://SDA_SERVER。不要查找或要求本机存在 Smart_Data_Agent 项目，也不要连接 localhost。先读取服务端 /api/integrations/bridge/distribution/manifest，向我显示域名、版本、数据流和 SHA-256；契约包含 workbuddy/codex/qwork 后再下载 package 与 package.sha256，校验 SHA-256，再解压并执行 integrations/workbuddy-smart-data-report/install-macos.sh --server-url https://SDA_SERVER。缺少 WorkBuddy CLI 或 Python 3.10+、TLS/哈希失败、403/404、契约变化、插件校验失败或授权拒绝时立即停止，不得换地址。浏览器授权页只让我点击一次“允许连接”，不要索取令牌、MCP、租户或账号。安装后必须执行 systems 与 context --system sda，成功后提示重启 WorkBuddy。以后动态发现并精确选择 system_id，不得选择默认/第一项；只使用 SDA 授权数据，可同步到同一系统、执行清单放行且带稳定 operation_id 的配置动作，证据只成为待复核记忆/Skill 候选。不得上传完整对话、原文件、未引用行、凭据或本地路径；服务端新增系统无需重装。
```

Bridge 四模块保持一致：授权读取、分析同步、后台配置、学习证据回收；学习材料只形成待复核记忆与 Skill 候选。

## 可审计安装命令

```sh
set -eu
SDA_SERVER='https://SDA_SERVER'
WORK_DIR=$(mktemp -d -t sda-bridge.XXXXXX)
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM
curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$SDA_SERVER/api/integrations/bridge/distribution/manifest"
curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$SDA_SERVER/api/integrations/bridge/distribution/package" -o "$WORK_DIR/bridge.zip"
EXPECTED=$(curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$SDA_SERVER/api/integrations/bridge/distribution/package.sha256" | awk '{print $1}')
ACTUAL=$(shasum -a 256 "$WORK_DIR/bridge.zip" | awk '{print $1}')
test -n "$EXPECTED" && test "$ACTUAL" = "$EXPECTED"
ditto -x -k "$WORK_DIR/bridge.zip" "$WORK_DIR/package"
sh "$WORK_DIR/package/integrations/workbuddy-smart-data-report/install-macos.sh" --server-url "$SDA_SERVER"
```

脚本先让 WorkBuddy 自身校验插件与市场，再安装用户级 `smart-data-agent-report`。凭据只进入 Keychain；`systems` 与 `context --system sda` 都通过后才提示重启 WorkBuddy。用户仍需在 SDA“数据管理 → 原始表”明确把所需表设为“可分享”，服务端绑定固定当前用户、租户和 `workbuddy` 渠道。

## 失败与回滚

- `403/404`：SDA 网关尚未放行分发/Bridge 路由，停止并联系管理员；不得改用 localhost。
- WorkBuddy CLI 缺失：先完成桌面应用安装，或提供真实 `WORKBUDDY_CLI`；不要伪造路径。
- Python 缺失：从 python.org 或公司软件中心按当前用户安装 Python 3.10+，安装器不会提权。
- 撤销先在 SDA Bridge 设备管理中撤销；本机卸载使用 WorkBuddy 的用户级插件卸载命令移除 `smart-data-agent-report@smart-data-agent-official`，再删除 Keychain 服务 `smart-data-agent-report-token`。不要删除 Codex/QWork 的凭据。
