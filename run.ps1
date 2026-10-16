param(
    [switch] $BackendOnly,
    [switch] $FrontendOnly
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$healthUrl = 'http://127.0.0.1:8000/health'
$frontendUrl = 'http://127.0.0.1:5173'

if ($BackendOnly) {
    $env:SUPABASE_DB_URL = ' '
    $env:DATABASE_URL = 'sqlite:///./enterprise_rag.db'
    $env:PYTHONPATH = $backendPath
    Set-Location -LiteralPath $backendPath
    Write-Host 'Starting backend with local SQLite. AI provider settings remain loaded from the project .env.'
    & $pythonPath -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    exit $LASTEXITCODE
}

if ($FrontendOnly) {
    Set-Location -LiteralPath $frontendPath
    Write-Host 'Starting frontend development server.'
    npm.cmd run dev -- --host 127.0.0.1 --strictPort
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found at $pythonPath. Create it and install backend\requirements.txt first."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules'))) {
    throw "Frontend dependencies not found. Run 'npm install' from the frontend folder first."
}

function Test-HttpEndpoint([string] $Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-PortListening([int] $Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-HttpEndpoint $healthUrl) {
    Write-Host 'Backend is already responding at http://127.0.0.1:8000.'
}
else {
    if (Test-PortListening 8000) {
        throw 'Port 8000 is already in use, but the backend health check failed. Close the conflicting application and run this command again.'
    }

    $backendArguments = "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`" -BackendOnly"
    $null = Start-Process -FilePath 'powershell.exe' -ArgumentList $backendArguments -WorkingDirectory $projectRoot

    $backendReady = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-HttpEndpoint $healthUrl) {
            $backendReady = $true
            break
        }
    }
    if (-not $backendReady) {
        throw 'Backend did not become healthy within 45 seconds. Check the backend PowerShell window for its startup error.'
    }
    Write-Host 'Backend is healthy at http://127.0.0.1:8000.'
}

if (Test-HttpEndpoint $frontendUrl) {
    Write-Host 'Frontend is already responding at http://127.0.0.1:5173.'
}
else {
    if (Test-PortListening 5173) {
        throw 'Port 5173 is already in use, but the frontend did not respond. Close the conflicting application and run this command again.'
    }

    $frontendArguments = "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`" -FrontendOnly"
    $null = Start-Process -FilePath 'powershell.exe' -ArgumentList $frontendArguments -WorkingDirectory $projectRoot

    $frontendReady = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-HttpEndpoint $frontendUrl) {
            $frontendReady = $true
            break
        }
    }
    if (-not $frontendReady) {
        throw 'Frontend did not become ready within 45 seconds. Check the frontend PowerShell window for its startup error.'
    }
    Write-Host 'Frontend is ready at http://127.0.0.1:5173.'
}

Start-Process $frontendUrl
Write-Host 'Both services are running. Keep their PowerShell windows open; press Ctrl+C in each window to stop them.'
