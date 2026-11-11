# start-all.ps1 —— 一键启动 Loop Engineering 本地工作台（Windows / PowerShell）
#
# 用法：在仓库根目录执行
#   .\start-all.ps1
# 若提示禁止运行脚本，先执行：
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# 会打开 3 个独立窗口：API(8002)、Worker、前端(3000)。
# 关掉对应窗口即停止对应进程。

$ErrorActionPreference = 'Stop'

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiDir = Join-Path $root 'services\api'
$webDir = Join-Path $root 'apps\web'
$python = Join-Path $apiDir '.venv\Scripts\python.exe'

$mysqld = $env:LOOP_MYSQLD_PATH
$myIni  = $env:LOOP_MYSQL_INI_PATH

function Test-Port([int]$port) {
    return (Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded
}

function Test-CurrentApi {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8002/health' -TimeoutSec 3
        $schema = Invoke-RestMethod 'http://127.0.0.1:8002/openapi.json' -TimeoutSec 3
        return ($health.status -eq 'ok' -and
            $null -ne $schema.paths.'/projects/setup'.post -and
            $null -ne $schema.paths.'/projects/{project_id}/workflow'.get)
    } catch { return $false }
}

Write-Host '=== Loop Engineering 启动器 ===' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $python)) {
    throw "找不到虚拟环境：$python`n请先执行： cd services/api; uv sync --extra dev"
}
if (-not (Test-Path -LiteralPath (Join-Path $webDir 'node_modules\next'))) {
    throw "前端依赖缺失。请先执行： npm --prefix apps/web install"
}

# 0) MySQL
if (Test-Port 3306) {
    Write-Host '[0/3] MySQL 已在运行 (3306)' -ForegroundColor Green
} else {
    if (-not $mysqld) {
        throw "MySQL 未监听 3306，且未设置 LOOP_MYSQLD_PATH。`n请先启动 MySQL，或设置 LOOP_MYSQLD_PATH（可选 LOOP_MYSQL_INI_PATH）后重试。"
    }
    if (-not (Test-Path -LiteralPath $mysqld)) {
        throw "找不到 mysqld：$mysqld"
    }
    Write-Host '[0/3] 启动 MySQL ...' -ForegroundColor Yellow
    $arguments = if ($myIni) { @("--defaults-file=$myIni") } else { @() }
    Start-Process -FilePath $mysqld -ArgumentList $arguments -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Port 3306) { $ready = $true; break }
    }
    if (-not $ready) { throw 'MySQL 30 秒内未监听 3306，请检查启动参数或手动启动 MySQL。' }
    Write-Host '      MySQL 已就绪' -ForegroundColor Green
}

# 1) API
if (Test-Port 8002) {
    if (-not (Test-CurrentApi)) {
        throw 'Port 8002 is running an outdated or incompatible API. Run .\restart-all.ps1 -BackendOnly to load the new workflow without closing your browser form.'
    }
    Write-Host '[1/3] 8002 已被占用，跳过 API 启动' -ForegroundColor Yellow
} else {
    Write-Host '[1/3] 启动 API  http://127.0.0.1:8002' -ForegroundColor Green
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit -Command `"Set-Location '$apiDir'; `$env:PYTHONIOENCODING='utf-8'; & '$python' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002`""
}

# 2) Worker
Write-Host '[2/3] 启动 Worker (queue=default)' -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit -Command `"Set-Location '$apiDir'; `$env:PYTHONPATH='.'; `$env:PYTHONIOENCODING='utf-8'; & '$python' -m app.workers.worker_service --queue default --poll-interval 2`""

# 3) Web
if (Test-Port 3000) {
    Write-Host '[3/3] 3000 已被占用，跳过前端启动' -ForegroundColor Yellow
} else {
    Write-Host '[3/3] 启动前端 http://127.0.0.1:3000/projects' -ForegroundColor Green
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit -Command `"Set-Location '$webDir'; npm run dev -- --hostname 127.0.0.1 --port 3000`""
}

Write-Host ''
Write-Host '等待 API 就绪 ...' -ForegroundColor Cyan
$apiReady = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 1000
    if (Test-CurrentApi) {
        $apiReady = $true
        Write-Host 'API and automatic workflow endpoints are ready.' -ForegroundColor Green
        break
    }
}
if (-not $apiReady) { throw 'API did not load the current workflow endpoints. Check API logs or run .\restart-all.ps1 -BackendOnly.' }

Write-Host ''
Write-Host '打开工作台： http://127.0.0.1:3000/projects' -ForegroundColor Cyan
Write-Host '前端首次编译需要十几秒，稍等再刷新。' -ForegroundColor DarkGray
