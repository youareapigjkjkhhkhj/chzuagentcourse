# ⚠ 本文件必须保存为「UTF-8 with BOM」。Windows PowerShell 5.1 在没有 BOM 时
#   按系统 ANSI(GBK) 解码，中文注释会变成乱码并吃掉引号，脚本直接语法报错。
#   （PowerShell 7 / pwsh 默认 UTF-8，两种都认 BOM，所以留着 BOM 最保险。）
# 一条命令拉起后端 :5000 与前端 :5173（P0-A1）。
#
#   .\scripts\dev.ps1
#   .\scripts\dev.ps1 -BackendPort 5001 -FrontendPort 5174
#
# 被执行策略挡住的话：
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#
# Git Bash / macOS / Linux 用 scripts/dev.sh。没装 GNU Make 也能验收 ——
# accept_p0.py 不依赖本脚本。
#
# Ctrl+C 会同时停掉两个服务：这里用 taskkill /T 收进程树，否则 python / node
# 的子进程会留着占端口，下次启动直接报「端口已被占用」。

[CmdletBinding()]
param(
    [int]$BackendPort = $(if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 5000 }),
    [int]$FrontendPort = $(if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 })
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'

# --- 前置检查：缺什么就直说，别让它快到一半才炸 ---

$Python = @(
    (Join-Path $Backend '.venv\Scripts\python.exe'),
    (Join-Path $Backend '.venv\bin\python')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) {
    Write-Error "找不到虚拟环境 $Backend\.venv —— 先按 README「5 分钟上手」建好：python -m venv backend\.venv"
    exit 1
}

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Write-Error "找不到前端依赖 $Frontend\node_modules —— 先在 frontend 下执行：npm install"
    exit 1
}

if (-not (Test-Path (Join-Path $Backend '.env'))) {
    # 不退出：没有 .env 也能起来（走 Mock Provider），但要不要配 Key 得用户知道
    Write-Host "提示：backend\.env 还不存在，现在跑的是 Mock Provider（无真实模型能力）" -ForegroundColor Yellow
    Write-Host "      照 backend\.env.example 建一个就能连真实模型。"
}

$Npm = (Get-Command npm.cmd, npm -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $Npm) {
    Write-Error "PATH 里找不到 npm —— 需要 Node.js 20+（https://nodejs.org）"
    exit 1
}

# --- 启动 ---

$started = @()
function Stop-Tree {
    foreach ($proc in $script:started) {
        if ($proc -and -not $proc.HasExited) {
            # /T 连子孙一起收：vite 会再起一个 esbuild 子进程
            & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null
        }
    }
    $script:started = @()
}

try {
    $started += Start-Process -FilePath $Python `
        -ArgumentList @('-m', 'flask', '--app', 'app:create_app()', 'run', '--port', "$BackendPort") `
        -WorkingDirectory $Backend -NoNewWindow -PassThru

    $started += Start-Process -FilePath $Npm `
        -ArgumentList @('run', 'dev', '--', '--port', "$FrontendPort", '--strictPort') `
        -WorkingDirectory $Frontend -NoNewWindow -PassThru

    Write-Host "后端 http://localhost:$BackendPort/api/health"
    Write-Host "前端 http://localhost:$FrontendPort"
    Write-Host "按 Ctrl+C 停止两个服务"
    Write-Host ""

    # 等**任意一个**退出就收摊（后端崩了、或用户关掉前端窗口，都不该留半个服务）。
    # 不能用 Wait-Process -Id a,b：它等的是「全部退出」，后端死了它还在等前端。
    while (-not ($started | Where-Object { $_.HasExited })) {
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Stop-Tree
}
