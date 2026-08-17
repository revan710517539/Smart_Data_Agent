[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('codex', 'qwork')]
    [string]$Channel,
    [Parameter(Mandatory = $true)]
    [Alias('Endpoint')]
    [string]$ServerUrl,
    [string]$AppUrl = '',
    [Alias('ProjectRoot')]
    [string]$BundleRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
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
    if (-not [Uri]::TryCreate($trimmed, [UriKind]::Absolute, [ref]$uri)) {
        throw "$Label 必须是完整的 HTTPS URL。"
    }
    $isLocal = $uri.Scheme -eq 'http' -and $uri.Host -in @('127.0.0.1', 'localhost')
    if ($uri.Scheme -ne 'https' -and -not ($AllowLocalDev -and $isLocal)) {
        throw "$Label 必须使用 HTTPS；localhost 仅可与 -AllowLocalDev 一起使用。"
    }
    if ($uri.AbsolutePath -notin @('', '/') -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
        throw "$Label 只接受 SDA 根地址，不能包含凭据、API 路径、查询或片段。"
    }
    return $trimmed
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Install-Skill([string]$Source, [string]$Target) {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination (Join-Path $Target 'SKILL.md') -Force
}

function Resolve-Python3 {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)'
        if ($LASTEXITCODE -eq 0) { return @{ Path = $py.Source; Prefix = @('-3') } }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)'
        if ($LASTEXITCODE -eq 0) { return @{ Path = $python.Source; Prefix = @() } }
    }
    throw '需要 Python 3.10+。请先从 python.org 或公司软件中心按当前用户安装，再重新运行；安装器不会静默提升权限。'
}

$ServerUrl = Resolve-SdaUrl '-ServerUrl' $ServerUrl
if ($AppUrl) {
    $AppUrl = Resolve-SdaUrl '-AppUrl' $AppUrl
} else {
    $AppUrl = $ServerUrl
}
$Python = Resolve-Python3

if ($SkipServerCheck -and -not $AllowLocalDev) {
    throw '-SkipServerCheck 只允许用于显式本地开发。'
}
if (-not $SkipServerCheck) {
    $distribution = Invoke-RestMethod -Method Get -Uri "$ServerUrl/api/integrations/bridge/distribution/manifest" -TimeoutSec 20 -MaximumRedirection 0
    if ($distribution.schema_version -ne 'sda_bridge_distribution_v1') {
        throw 'SDA 服务端未提供预期的 Bridge 分发契约。'
    }
    $channels = @($distribution.channels | Sort-Object)
    if (($channels -join ',') -ne 'codex,qwork,workbuddy') {
        throw 'SDA 服务端 Bridge 渠道契约不完整。'
    }
}

$BundleRoot = (Resolve-Path -LiteralPath $BundleRoot).Path
$SourceCli = Join-Path $BundleRoot 'integrations\workbuddy-smart-data-report\bin\sda_report.py'
$SourceLauncher = Join-Path $BundleRoot 'integrations\workbuddy-smart-data-report\bin\SDA.cmd'
$SourceSkill = Join-Path $BundleRoot "integrations\$Channel-smart-data-agent-bridge\smart-data-agent-bridge\SKILL.md"
foreach ($required in @($SourceCli, $SourceLauncher, $SourceSkill)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Bridge 安装包不完整：$required" }
}

$BridgeRoot = Join-Path $env:LOCALAPPDATA 'SmartDataAgentBridge\bin'
$ConfigDir = Join-Path $env:APPDATA 'smart-data-agent'
New-Item -ItemType Directory -Path $BridgeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
Copy-Item -LiteralPath $SourceCli -Destination (Join-Path $BridgeRoot 'sda_report.py') -Force
Copy-Item -LiteralPath $SourceLauncher -Destination (Join-Path $BridgeRoot 'SDA.cmd') -Force
Write-Utf8NoBom (Join-Path $ConfigDir 'report-cli.json') (@{ endpoint = $ServerUrl; app_url = $AppUrl } | ConvertTo-Json -Compress)

if ($Channel -eq 'codex') {
    $CodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
    Install-Skill $SourceSkill (Join-Path $CodexRoot 'skills\smart-data-agent-bridge')
} else {
    $DeepbankRoot = if ($env:DEEPBANK_HOME) { $env:DEEPBANK_HOME } else { Join-Path $HOME '.deepbank' }
    Install-Skill $SourceSkill (Join-Path $DeepbankRoot '.agents\skills\smart-data-agent-bridge')
    Install-Skill $SourceSkill (Join-Path $DeepbankRoot '.claude\skills\smart-data-agent-bridge')
}

$TokenFile = Join-Path $ConfigDir "report-cli-$Channel.token"
if (-not $SkipTokenPrompt -and -not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) {
    & (Join-Path $BridgeRoot 'SDA.cmd') connect --channel $Channel --endpoint $ServerUrl --app-url $AppUrl --token-keychain-service "smart-data-agent-bridge-$Channel"
    if ($LASTEXITCODE -ne 0) { throw 'SDA Bridge 浏览器授权失败。' }
}

if (-not $SkipConnectionTest) {
    & (Join-Path $BridgeRoot 'SDA.cmd') bridge --channel $Channel systems --token-keychain-service "smart-data-agent-bridge-$Channel" --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Universal Bridge 系统发现检查失败。' }
    & (Join-Path $BridgeRoot 'SDA.cmd') bridge --channel $Channel context --system sda --token-keychain-service "smart-data-agent-bridge-$Channel" --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Universal Bridge SDA 连通性检查失败。' }
}

Write-Host "Universal Bridge ready: channel=$Channel server=$ServerUrl"
Write-Host "请重启或新建 $Channel 任务加载 Skill。"
