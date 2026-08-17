# QWork macOS 接入 SDA Universal Bridge

## 管理员分享前只做一次

把 `https://SDA_SERVER` 替换为本组织真实、可登录、证书有效的 SDA HTTPS 根地址后再分享。安装来源、授权页和数据服务必须同域；不得发送维护者源码路径或 localhost 地址。

## 直接粘贴给 QWork 的一段话

```text
请为当前 macOS 用户安装一次 Smart Data Agent Universal Bridge 双投影 Skill，渠道必须是 qwork，服务端根地址是 https://SDA_SERVER。不要查找或要求本机存在 Smart_Data_Agent 项目，也不要连接 localhost。先读取服务端 /api/integrations/bridge/distribution/manifest 并显示域名、版本、数据流和 SHA-256；契约包含三个渠道后再下载 package 与 package.sha256，校验后解压并执行 integrations/smart-data-agent-bridge/install-macos.sh --channel qwork --server-url https://SDA_SERVER。缺少 Python 3.10+、TLS/哈希失败、403/404、契约变化或授权拒绝时停止，不得换地址。浏览器只让我点击一次“允许连接”，不要索取令牌、MCP、租户或账号。安装后检查两个 QWork Skill 投影，并真实执行 systems 与 context --system sda；成功后提示刷新技能列表或新建任务。以后动态发现并精确选择 system_id，不得选择默认/第一项；只使用授权数据、清单动作和稳定 operation_id，回传证据只成为待复核记忆/Skill 候选。不得上传完整对话、原文件、未引用行、凭据或本地路径；服务端新增系统无需重装。
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
sh "$WORK_DIR/package/integrations/smart-data-agent-bridge/install-macos.sh" --channel qwork --server-url "$SDA_SERVER"
```

安装器把相同 Skill 安装到 `${DEEPBANK_HOME:-$HOME/.deepbank}/.agents/skills/smart-data-agent-bridge` 和 `.claude/skills/smart-data-agent-bridge`，CLI 位于 `$HOME/.local/bin/SDA`，凭据只进入 Keychain。两个投影、`systems`、`context --system sda` 全部成功才算完成。

`403/404` 代表 SDA 网关尚未放行分发/Bridge 路由，停止并联系管理员。撤销先在 SDA Bridge 设备管理中撤销；卸载只删除两个 QWork Skill 目录、仅在无其他渠道使用时删除公共 CLI，并删除 Keychain 服务 `smart-data-agent-bridge-qwork`。
