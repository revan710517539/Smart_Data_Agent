# QWork Windows 接入 SDA Universal Bridge

## 管理员分享前只做一次

把 `https://SDA_SERVER` 替换为本组织真实、证书有效的 SDA HTTPS 根地址后再分享。不得要求接收者拥有 SDA 源码或访问 localhost。

## 直接粘贴给 Windows QWork 的一段话

```text
请为当前 Windows 用户安装一次 Smart Data Agent Universal Bridge 双投影 Skill，渠道必须是 qwork，服务端根地址是 https://SDA_SERVER。不要查找本地 Smart_Data_Agent 项目，也不要连接 localhost。先读取 /api/integrations/bridge/distribution/manifest，显示服务域名、版本、数据流和 SHA-256；契约完整后下载 package 与 package.sha256，用 Get-FileHash 校验，再解压运行 integrations\smart-data-agent-bridge\install-windows.ps1 -Channel qwork -ServerUrl https://SDA_SERVER。缺少 Python 3.10+、TLS/哈希失败、403/404、契约变化或授权拒绝时停止，不得换地址。浏览器只让我点击一次“允许连接”，不要索取令牌、MCP、租户或账号。安装后检查两个 Skill 投影并执行 systems 与 context --system sda；成功后提示刷新技能或新建任务。以后动态发现并精确选择 system_id，不得选择默认/第一项；只使用授权数据、清单动作与稳定 operation_id，证据只作为待复核候选。不得上传完整对话、原文件、未引用行、凭据或本地路径；服务端新增系统无需重装。
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
  & "$WorkDir\package\integrations\smart-data-agent-bridge\install-windows.ps1" -Channel qwork -ServerUrl $SdaServer
} finally {
  Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

CLI 位于 `%LOCALAPPDATA%\SmartDataAgentBridge\bin`；Skill 同时安装到 `%USERPROFILE%\.deepbank\.agents\skills\smart-data-agent-bridge` 和 `.claude\skills\smart-data-agent-bridge`；凭据只以当前用户 DPAPI 密文保存。两个投影和两次服务回读必须全部通过。

`403/404` 表示 SDA 网关未放行，不能回退 localhost。撤销先在 SDA Bridge 设备管理中撤销绑定；卸载仅删除两个 QWork Skill 目录与 `report-cli-qwork.token`，公共 CLI 仅在没有其他渠道使用时删除。
