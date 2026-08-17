# Codex macOS 接入 SDA Universal Bridge

## 管理员分享前只做一次

把下文中的 `https://SDA_SERVER` 替换为本组织真实、可登录、证书有效的 SDA HTTPS 根地址，再整段发给用户。安装来源、授权页和数据服务必须是同一个 SDA 域名；不要改成源码路径、网盘脚本或 `127.0.0.1`。

## 直接粘贴给 Codex 的一段话

```text
请为当前 macOS 用户安装一次 Smart Data Agent Universal Bridge，渠道必须是 codex，服务端根地址是 https://SDA_SERVER。不要查找或要求本机存在 Smart_Data_Agent 项目，也不要连接 localhost。先读取该服务的 /api/integrations/bridge/distribution/manifest，向我显示服务域名、Bridge 版本、数据流说明和 SHA-256；只有域名与我提供的一致且契约包含 workbuddy/codex/qwork 后，才下载 /api/integrations/bridge/distribution/package 和 package.sha256，校验 SHA-256，再解压并执行 integrations/smart-data-agent-bridge/install-macos.sh --channel codex --server-url https://SDA_SERVER。若缺少 Python 3.10+、证书/校验失败、服务返回 403/404、契约变化或浏览器授权被拒绝，立即停止并准确报告，不得换成本地地址或其他服务。浏览器出现 SDA 授权页时只让我点击一次“允许连接”，不得要求我复制令牌、配置 MCP、租户或账号。安装后必须真实执行 systems 和 context --system sda，成功后提示我新建 Codex 任务。以后每次先动态发现系统，按我的文字精确选择 system_id，不得使用默认系统或第一项；只读取授权数据，可向同一系统同步分析、执行清单明确放行且有 operation_id 的配置动作，并回传待复核证据。不得上传完整对话、原文件、未引用行、凭据或本地路径；后台新增系统无需重装。
```

Bridge 四模块保持一致：授权读取、分析同步、后台配置、学习证据回收；学习材料只形成待复核记忆与 Skill 候选。

## 可审计安装命令

以下命令不依赖 SDA 源码，只下载服务端公开的固定白名单安装包：

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
sh "$WORK_DIR/package/integrations/smart-data-agent-bridge/install-macos.sh" --channel codex --server-url "$SDA_SERVER"
```

安装器将 CLI 写入 `$HOME/.local/bin/SDA`、Skill 写入 `${CODEX_HOME:-$HOME/.codex}/skills/smart-data-agent-bridge`，凭据只进入 macOS Keychain。它最后真实执行 `systems` 与 `context --system sda`；任一步失败都不会报告成功。

## 验收、失败与回滚

- 成功：授权页域名与 `SDA_SERVER` 一致；`systems` 返回精确系统清单；`context --system sda` 返回当前绑定的授权上下文；新 Codex 任务能加载 Skill。
- `403/404`：服务端网关尚未放行分发/Bridge 路由，停止并交给 SDA 管理员；不要改用 localhost。
- `Python 3.10+ is required`：从 python.org 或公司软件中心按当前用户安装 Python 后重试，安装器不会提权。
- 撤销连接：在 SDA 的 Bridge 设备管理中撤销本设备；本机卸载可删除 `$HOME/.codex/skills/smart-data-agent-bridge`、`$HOME/.local/share/smart-data-agent-bridge` 和 `$HOME/.local/bin/SDA`，再删除 Keychain 服务 `smart-data-agent-bridge-codex`。不要删除其他渠道的配置或凭据。
