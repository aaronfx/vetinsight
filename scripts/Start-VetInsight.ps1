[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$backendPath = Join-Path $projectPath 'backend'
$frontendPath = Join-Path $projectPath 'frontend'
$logPath = Join-Path $projectPath 'logs'
New-Item -ItemType Directory -Path $logPath -Force | Out-Null
$runName = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$launcherLog = Join-Path $logPath "$runName-launcher.log"
$lockStream = $null

function Write-Status([string]$Message) {
    Write-Host $Message
    Add-Content -LiteralPath $launcherLog -Value "$(Get-Date -Format s) $Message"
}

function Get-LocalResponse([string]$Url) {
    # Bypass proxies for local services, including machines with proxy env vars.
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Proxy = $null
    $request.Timeout = 2000
    $response = $request.GetResponse()
    try {
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $response.Dispose() }
}

function Test-Service([string]$Service) {
    try {
        if ($Service -eq 'backend') {
            $health = Get-LocalResponse 'http://127.0.0.1:8000/health' | ConvertFrom-Json
            $identity = Get-LocalResponse 'http://127.0.0.1:8000/auth/status' | ConvertFrom-Json
            return ($health.status -eq 'ok' -and $health.database -eq 'ok' -and $identity.service -eq 'VetInsight Case API')
        }
        $page = Get-LocalResponse 'http://127.0.0.1:5173/'
        $source = Get-LocalResponse 'http://127.0.0.1:5173/src/App.tsx'
        return ($page -match '/src/main.tsx' -and $source -match 'VetInsight' -and $source -match 'Workspace dashboard')
    } catch { return $false }
}

function Start-ServiceIfNeeded([string]$Service, [int]$Port, [string]$Executable, [string[]]$Arguments, [string]$Directory) {
    if (Test-Service $Service) {
        Write-Status "$Service is already healthy on port $Port; reusing it."
        return
    }
    $listeners = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $Port })
    if ($listeners.Count -gt 0) {
        throw "Port $Port is occupied, but $Service did not pass its health check. No process was stopped. See the existing service logs or close the conflicting application."
    }
    $stdoutPath = Join-Path $logPath "$runName-$Service.stdout.log"
    $stderrPath = Join-Path $logPath "$runName-$Service.stderr.log"
    Write-Status "Starting $Service. Logs: $stdoutPath and $stderrPath"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
    $deadline = (Get-Date).AddSeconds(30)
    do {
        if (Test-Service $Service) {
            Write-Status "$Service is ready on port $Port."
            return
        }
        $process.Refresh()
        if ($process.HasExited) {
            $tail = (Get-Content -LiteralPath $stderrPath -Tail 15 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            throw "$Service exited before becoming ready (exit $($process.ExitCode)). $tail"
        }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    throw "$Service did not become healthy within 30 seconds. Inspect $stderrPath. It may still be starting; this launcher has not killed it."
}

try {
    # Prevent two double-clicks from racing to start the same services.
    $lockStream = [System.IO.File]::Open((Join-Path $logPath 'startup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Write-Status 'Checking VetInsight prerequisites...'
    $pythonPath = Join-Path $backendPath '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Backend virtual environment is missing. Follow the fresh setup steps in README.md.' }
    $nodePath = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    if (-not $nodePath) { throw 'Node.js is missing from PATH. Install Node.js, then run npm.cmd install in frontend.' }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules\vite\bin\vite.js'))) { throw 'Frontend dependencies are missing. Run npm.cmd install in frontend.' }
    if ($env:VETINSIGHT_DATA_DIR) { Write-Status "Using configured storage: $env:VETINSIGHT_DATA_DIR" }
    Start-ServiceIfNeeded 'backend' 8000 $pythonPath @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') $backendPath
    Start-ServiceIfNeeded 'frontend' 5173 $nodePath @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1') $frontendPath
    # Case routes now require sign-in; readiness does not bypass authentication.
    Write-Status 'VetInsight is ready: http://localhost:5173/'
    if (-not $NoBrowser) {
        try { Start-Process 'http://localhost:5173/' }
        catch { Write-Status "Services are healthy, but Windows could not open the browser: $($_.Exception.Message) Open http://localhost:5173/ manually." }
    }
} catch {
    Write-Status "STARTUP FAILED: $($_.Exception.Message)"
    Write-Host "Details: $launcherLog" -ForegroundColor Yellow
    exit 1
} finally {
    if ($lockStream) { $lockStream.Dispose() }
}

