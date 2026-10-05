$ErrorActionPreference = 'Stop'
$record = Join-Path $PSScriptRoot 'data/server-process.json'
if (-not (Test-Path -LiteralPath $record)) { Write-Output 'No managed server record.'; exit }
$saved = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
$listener = Get-NetTCPConnection -LocalPort $saved.port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$targetPid = if ($listener) { $listener.OwningProcess } else { $saved.pid }
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$targetPid"
if (-not $process) { Write-Output 'Server already stopped.'; exit }
if ($process.CommandLine -notlike '*backend.app:app*' -or $process.CommandLine -notlike ('*'+$PSScriptRoot+'*')) { throw 'PID does not match this project. Refusing to stop.' }
Stop-Process -Id $targetPid
Write-Output "Stopped project server PID $targetPid."
