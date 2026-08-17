[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias('Endpoint')]
    [string]$ServerUrl,
    [string]$AppUrl = '',
    [Alias('ProjectRoot')]
    [string]$BundleRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$WorkBuddyCli = $env:WORKBUDDY_CLI,
    [switch]$AllowLocalDev,
    [switch]$SkipServerCheck,
    [switch]$SkipTokenPrompt,
    [switch]$SkipConnectionTest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-SdaUrl([string]$Label, [string]$Value) {
    $trimmed = $Value.Trim().TrimEnd('/')
    $uri = $null
    if (-not [Uri]::TryCreate($trimmed, [UriKind]::Absolute, [ref]$uri)) { throw "$Label 必须是完整的 HTTPS URL。" }
    $isLocal = $uri.Scheme -eq 'http' -and $uri.Host -in @('127.0.0.1', 'localhost')
    if ($uri.Scheme -ne 'https' -and -not ($AllowLocalDev -and $isLocal)) {
        throw "$Label 必须使用 HTTPS；localhost 仅可与 -AllowLocalDev 一起使用。"
    }
    if ($uri.AbsolutePath -notin @('', '/') -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) { throw "$Label 只接受 SDA 根地址，不能包含凭据、API 路径、查询或片段。" }
    return $trimmed
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Resolve-WorkBuddyCli([string]$ConfiguredPath) {
    if ($ConfiguredPath) {
        if (-not (Test-Path -LiteralPath $ConfiguredPath -PathType Leaf)) { throw "WORKBUDDY_CLI 不存在：$ConfiguredPath" }
        return (Resolve-Path -LiteralPath $ConfiguredPath).Path
    }
    $command = Get-Command codebuddy -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy.exe'),
        (Join-Path $env:LOCALAPPDATA 'WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy.exe'),
        (Join-Path $env:ProgramFiles 'WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    if ($candidates.Count -gt 0) { return (Resolve-Path -LiteralPath $candidates[0]).Path }
    throw '未找到 WorkBuddy CLI。请先安装 WorkBuddy，或设置 WORKBUDDY_CLI 为 codebuddy.exe 的完整路径。'
}

function Assert-Python3 {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)'
        if ($LASTEXITCODE -eq 0) { return }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)'
        if ($LASTEXITCODE -eq 0) { return }
    }
    throw '需要 Python 3.10+。请先从 python.org 或公司软件中心按当前用户安装，再重新运行；安装器不会静默提升权限。'
}

$ServerUrl = Resolve-SdaUrl '-ServerUrl' $ServerUrl
if ($AppUrl) { $AppUrl = Resolve-SdaUrl '-AppUrl' $AppUrl } else { $AppUrl = $ServerUrl }
Assert-Python3
if ($SkipServerCheck -and -not $AllowLocalDev) { throw '-SkipServerCheck 只允许用于显式本地开发。' }
if (-not $SkipServerCheck) {
    $distribution = Invoke-RestMethod -Method Get -Uri "$ServerUrl/api/integrations/bridge/distribution/manifest" -TimeoutSec 20 -MaximumRedirection 0
    if ($distribution.schema_version -ne 'sda_bridge_distribution_v1' -or 'workbuddy' -notin @($distribution.channels)) {
        throw 'SDA 服务端未提供预期的 WorkBuddy Bridge 分发契约。'
    }
}

$BundleRoot = (Resolve-Path -LiteralPath $BundleRoot).Path
$PluginRoot = Join-Path $BundleRoot 'integrations\workbuddy-smart-data-report'
$MarketplaceDir = Join-Path $BundleRoot 'integrations\workbuddy-smart-data-report-marketplace'
$PluginName = 'smart-data-agent-report'
$MarketplaceName = 'smart-data-agent-official'
$WorkBuddyCli = Resolve-WorkBuddyCli $WorkBuddyCli

if (-not (Test-Path -LiteralPath (Join-Path $PluginRoot '.codebuddy-plugin\plugin.json') -PathType Leaf)) { throw "Bridge 安装包不完整：$PluginRoot" }
if (-not (Test-Path -LiteralPath (Join-Path $MarketplaceDir '.codebuddy-plugin\marketplace.json') -PathType Leaf)) { throw "Bridge 安装包不完整：$MarketplaceDir" }

& $WorkBuddyCli plugin validate $PluginRoot
if ($LASTEXITCODE -ne 0) { throw 'WorkBuddy 插件校验失败。' }
& $WorkBuddyCli plugin validate $MarketplaceDir
if ($LASTEXITCODE -ne 0) { throw 'WorkBuddy 插件市场校验失败。' }
$marketplaces = (& $WorkBuddyCli plugin marketplace list | Out-String)
if ($marketplaces -notmatch [regex]::Escape($MarketplaceName)) {
    & $WorkBuddyCli plugin marketplace add $MarketplaceDir --name $MarketplaceName
    if ($LASTEXITCODE -ne 0) { throw 'WorkBuddy 插件市场注册失败。' }
}
& $WorkBuddyCli plugin install "$PluginName@$MarketplaceName" --scope user
if ($LASTEXITCODE -ne 0) {
    & $WorkBuddyCli plugin enable "$PluginName@$MarketplaceName" --scope user
    if ($LASTEXITCODE -ne 0) { throw 'WorkBuddy 插件安装或启用失败。' }
}

$ConfigDir = Join-Path $env:APPDATA 'smart-data-agent'
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
Write-Utf8NoBom (Join-Path $ConfigDir 'report-cli.json') (@{ endpoint = $ServerUrl; app_url = $AppUrl } | ConvertTo-Json -Compress)

$TokenFile = Join-Path $ConfigDir 'report-cli.token'
if (-not $SkipTokenPrompt -and -not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) {
    & (Join-Path $PluginRoot 'bin\SDA.cmd') connect --channel workbuddy --endpoint $ServerUrl --app-url $AppUrl --token-keychain-service smart-data-agent-report-token
    if ($LASTEXITCODE -ne 0) { throw 'SDA WorkBuddy Bridge 浏览器授权失败。' }
}

if (-not $SkipConnectionTest) {
    & (Join-Path $PluginRoot 'bin\SDA.cmd') bridge --channel workbuddy systems --token-keychain-service smart-data-agent-report-token --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Universal Bridge 系统发现检查失败。' }
    & (Join-Path $PluginRoot 'bin\SDA.cmd') bridge --channel workbuddy context --system sda --token-keychain-service smart-data-agent-report-token --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Universal Bridge SDA 连通性检查失败。' }
}
Write-Host "安装完成。请重启 WorkBuddy；server=$ServerUrl"
