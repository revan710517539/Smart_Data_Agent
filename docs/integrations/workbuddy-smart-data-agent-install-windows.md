# WorkBuddy Windows 接入 SDA Universal Bridge

## 管理员分享前只做一次

把 `https://SDA_SERVER` 替换为本组织真实、证书有效的 SDA HTTPS 根地址后再分享。不得要求接收者拥有 SDA 源码或访问 localhost。

## 直接粘贴给 Windows WorkBuddy 的一段话

```text
请为当前 Windows 用户安装一次 Smart Data Agent Universal Bridge，渠道必须是 workbuddy，服务端根地址是 https://SDA_SERVER。不要查找本地 Smart_Data_Agent 项目，也不要连接 localhost。先读取 /api/integrations/bridge/distribution/manifest，显示域名、版本、数据流和 SHA-256；契约完整后下载 package 与 package.sha256，用 Get-FileHash 校验，再解压执行 integrations\workbuddy-smart-data-report\install-windows.ps1 -ServerUrl https://SDA_SERVER。缺少 WorkBuddy CLI 或 Python 3.10+、TLS/哈希失败、403/404、契约变化、插件校验失败或授权拒绝时停止，不得换地址。浏览器只让我点击一次“允许连接”，不要索取令牌、MCP、租户或账号。安装后必须执行 systems 与 context --system sda，成功后提示重启 WorkBuddy。以后动态发现并精确选择 system_id，不得选择默认/第一项；只使用授权数据、清单动作和稳定 operation_id，证据只作为待复核候选。不得上传完整对话、原文件、未引用行、凭据或本地路径；服务端新增系统无需重装。
```

Bridge 四模块保持一致：授权读取、分析同步、后台配置、学习证据回收；学习材料只形成待复核记忆与 Skill 候选。

## 可审计安装命令

```powershell
$ErrorActionPreference = 'Stop'
$SdaServer = 'https://SDA_SERVER'
$WorkDir = Join-Path $env:TEMP ("sda-bridge-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $WorkDir | Out-Null
try {
  Invoke-RestMethod -Method Get -Uri "$SdaServer/api/integrations/bridge/distribution/manifest" -MaximumRedirection 0
  Invoke-WebRequest -UseBasicParsing -Uri "$SdaServer/api/integrations/bridge/distribution/package" -MaximumRedirection 0 -OutFile "$WorkDir\bridge.zip"
  $Expected = ((Invoke-WebRequest -UseBasicParsing -Uri "$SdaServer/api/integrations/bridge/distribution/package.sha256" -MaximumRedirection 0).Content -split '\s+')[0].ToLowerInvariant()
  $Actual = (Get-FileHash -Algorithm SHA256 "$WorkDir\bridge.zip").Hash.ToLowerInvariant()
  if (-not $Expected -or $Actual -ne $Expected) { throw 'SDA Bridge package SHA-256 mismatch' }
  Expand-Archive -LiteralPath "$WorkDir\bridge.zip" -DestinationPath "$WorkDir\package"
  Set-ExecutionPolicy -Scope Process Bypass -Force
  & "$WorkDir\package\integrations\workbuddy-smart-data-report\install-windows.ps1" -ServerUrl $SdaServer
} finally {
  Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

脚本由 WorkBuddy CLI 校验并安装用户级插件；一次性令牌只以当前用户 DPAPI 密文保存。`systems` 与 `context --system sda` 都通过才算完成。非默认 WorkBuddy 安装位置可显式传入 `-WorkBuddyCli 'C:\准确路径\codebuddy.exe'`，不能猜路径。

`403/404` 表示 SDA 网关未放行，不能回退 localhost。撤销先在 SDA Bridge 设备管理中撤销；卸载用户级 `smart-data-agent-report@smart-data-agent-official` 并仅删除 `%APPDATA%\smart-data-agent\report-cli.token`，不要删除 Codex/QWork 的 DPAPI 文件。
