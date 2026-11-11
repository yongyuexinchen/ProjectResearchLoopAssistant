[CmdletBinding(SupportsShouldProcess)]
param([switch]$BackendOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$apiDirectory = Join-Path $projectRoot 'services\api'
$webDirectory = Join-Path $projectRoot 'apps\web'
$pythonPath = Join-Path $apiDirectory '.venv\Scripts\python.exe'
$nodePath = if (-not $BackendOnly) { (Get-Command node.exe -ErrorAction Stop).Source } else { $null }
$logsDirectory = Join-Path $projectRoot '.tmp\service-logs'

if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python dependencies are missing. Run uv sync --extra dev in services/api first.' }
if (-not $BackendOnly -and -not (Test-Path -LiteralPath (Join-Path $webDirectory 'node_modules\next'))) { throw 'Web dependencies are missing. Run npm install in apps/web first.' }

# Only match this project's actual API, worker and Next commands; never kill by executable name.
$processSnapshot = @(Get-CimInstance Win32_Process)
$ownedIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($entry in $processSnapshot) {
    $command = [string]$entry.CommandLine
    if ($entry.ProcessId -ne $PID -and
        $command.IndexOf($projectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $entry.Name -match '^(python|node)(\.exe)?$' -and
        ($command -match 'uvicorn\s+app\.main:app|app\.workers\.worker_service' -or
         (-not $BackendOnly -and $command -match 'next.*(?:\sdev\b|\sstart\b|start-server\.js)'))) {
        [void]$ownedIds.Add([int]$entry.ProcessId)
    }
}
# A venv Python launcher may own a child whose command no longer includes the project path.
do {
    $added = $false
    foreach ($entry in $processSnapshot) {
        if ($entry.ProcessId -ne $PID -and $ownedIds.Contains([int]$entry.ParentProcessId)) {
            if ($ownedIds.Add([int]$entry.ProcessId)) { $added = $true }
        }
    }
} while ($added)

Write-Host ("Project: {0}" -f $projectRoot)
Write-Host ("Matched app processes: {0}" -f (($ownedIds | Sort-Object) -join ', '))
$restartDescription = if ($BackendOnly) { 'Restart this project API and worker; keep web and browser form running' } else { 'Restart this project API, worker, and web on ports 8002 and 3000' }
if (-not $PSCmdlet.ShouldProcess($projectRoot, $restartDescription)) { return }

foreach ($processId in $ownedIds) {
    # Recheck the process creation time to avoid acting on a reused process ID.
    $original = $processSnapshot | Where-Object { $_.ProcessId -eq $processId } | Select-Object -First 1
    $current = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $processId)
    if ($null -ne $current -and $null -ne $original -and $current.CreationDate -eq $original.CreationDate) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

New-Item -ItemType Directory -Path $logsDirectory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = '.'
$null = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8002') -WorkingDirectory $apiDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logsDirectory "$stamp-api.out.log") -RedirectStandardError (Join-Path $logsDirectory "$stamp-api.err.log") -PassThru
$null = Start-Process -FilePath $pythonPath -ArgumentList @('-m','app.workers.worker_service','--queue','default','--poll-interval','2') -WorkingDirectory $apiDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logsDirectory "$stamp-worker.out.log") -RedirectStandardError (Join-Path $logsDirectory "$stamp-worker.err.log") -PassThru
if (-not $BackendOnly) {
    $env:LOOP_API_ORIGIN = 'http://127.0.0.1:8002'
    $env:NEXT_PUBLIC_API_BASE_URL = 'http://127.0.0.1:8002'
    Remove-Item Env:LOOP_NEXT_DIST_DIR -ErrorAction SilentlyContinue
    $null = Start-Process -FilePath $nodePath -ArgumentList @('node_modules/next/dist/bin/next','dev','--hostname','127.0.0.1','--port','3000') -WorkingDirectory $webDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logsDirectory "$stamp-web.out.log") -RedirectStandardError (Join-Path $logsDirectory "$stamp-web.err.log") -PassThru
}

$apiReady = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8002/health' -TimeoutSec 2
        $schema = Invoke-RestMethod -Uri 'http://127.0.0.1:8002/openapi.json' -TimeoutSec 2
        if ($health.status -eq 'ok' -and $null -ne $schema.paths.'/projects/setup'.post -and
            $null -ne $schema.paths.'/projects/{project_id}/workflow'.get) { $apiReady = $true; break }
    } catch { }
}
if (-not $apiReady) { throw ("API did not become ready. Check logs: {0}" -f $logsDirectory) }
Write-Host 'Ready: http://127.0.0.1:3000/projects/new'
Write-Host ("Logs: {0}" -f $logsDirectory)
