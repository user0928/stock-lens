param([int]$Port = 8765, [switch]$Lan)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = [IO.Path]::GetFullPath((Join-Path $projectRoot '../../work/venv/Scripts/python.exe')) }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run Setup.ps1 first to create the project environment.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'dist/index.html'))) { throw 'Missing dist. Run npm.cmd ci and npm.cmd run build.' }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Port $Port is already in use. No existing process was changed." }
$bindAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$dataDir = Join-Path $projectRoot 'data'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$arguments = @('-m','uvicorn','backend.app:app','--app-dir',('"' + $projectRoot + '"'),'--host',$bindAddress,'--port',"$Port")
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDir 'server.log') -RedirectStandardError (Join-Path $dataDir 'server-error.log') -PassThru
$serverPid = $process.Id
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 300
    $activeListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($activeListener) {
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$($activeListener.OwningProcess)"
        if ($candidate.CommandLine -like '*backend.app:app*' -and $candidate.CommandLine -like ('*'+$projectRoot+'*')) { $serverPid = $candidate.ProcessId; break }
    }
}
@{pid=$serverPid;launcherPid=$process.Id;port=$Port;started=(Get-Date).ToString('o');project=$projectRoot} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataDir 'server-process.json') -Encoding utf8
if (-not $activeListener) { throw 'Server did not become ready. See data/server-error.log.' }
Write-Output "Stock Lens ready: http://127.0.0.1:$Port (PID $serverPid)"
if ($Lan) { Write-Output 'LAN mode enabled. Use this PC local IP on your phone. Do not expose this unauthenticated personal service to the Internet.' }
