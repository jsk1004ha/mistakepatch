param(
    [ValidateSet('dev', 'test', 'help')]
    [string]$Mode = 'dev'
)

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$EvidenceDir = Join-Path $RepoRoot ".sisyphus\evidence"

if (-not (Test-Path $EvidenceDir)) {
    New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
}

function Show-Help {
    Write-Host "Usage: ./scripts/mistakepatch.ps1 -Mode [dev|test|help]"
    Write-Host ""
    Write-Host "Modes:"
    Write-Host "  dev  : Starts backend (8000) and frontend (3000) for development."
    Write-Host "  test : Runs lint, build, and e2e tests against running servers."
    Write-Host "  help : Shows this help message."
}

if ($Mode -eq 'help') {
    Show-Help
    exit 0
}

# Preconditions
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Backend virtual environment not found at $PythonExe."
    Write-Host "Please run 'python -m venv .venv' and 'pip install -r requirements.txt' in the backend directory."
    exit 1
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm not found. Please install Node.js."
    exit 1
}

# Environment variables for fallback mode
$env:OPENAI_API_KEY = ""
$env:USE_REDIS_QUEUE = "false"
$env:ENABLE_OCR_HINTS = "true"

$Processes = @()

try {
    Write-Host "Starting Backend..."
    $BackendOut = Join-Path $EvidenceDir "backend.out.log"
    $BackendErr = Join-Path $EvidenceDir "backend.err.log"
    $BackendProc = Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $BackendDir -PassThru -NoNewWindow -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr
    $Processes += $BackendProc

    if ($Mode -eq 'test') {
        Write-Host "Mode is 'test'. Running Lint and Build before starting Frontend server..."
        
        Write-Host "1. Running Lint..."
        pushd $FrontendDir
        npm run lint
        if ($LASTEXITCODE -ne 0) { throw "Lint failed" }
        popd

        Write-Host "2. Running Build..."
        pushd $FrontendDir
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Build failed" }
        popd

        Write-Host "Starting Frontend (Production)..."
        $FrontendOut = Join-Path $EvidenceDir "frontend.out.log"
        $FrontendErr = Join-Path $EvidenceDir "frontend.err.log"
        $FrontendProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run start" -WorkingDirectory $FrontendDir -PassThru -NoNewWindow -RedirectStandardOutput $FrontendOut -RedirectStandardError $FrontendErr
        $Processes += $FrontendProc
    }
    else {
        Write-Host "Starting Frontend (Development)..."
        $FrontendOut = Join-Path $EvidenceDir "frontend.out.log"
        $FrontendErr = Join-Path $EvidenceDir "frontend.err.log"
        $FrontendProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory $FrontendDir -PassThru -NoNewWindow -RedirectStandardOutput $FrontendOut -RedirectStandardError $FrontendErr
        $Processes += $FrontendProc
    }

    # Readiness checks
    Write-Host "Waiting for servers to be ready..."
    $Timeout = 60 # seconds
    $StartTime = Get-Date
    $BackendReady = $false
    $FrontendReady = $false

    while (((Get-Date) - $StartTime).TotalSeconds -lt $Timeout) {
        if (-not $BackendReady) {
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing -ErrorAction SilentlyContinue
                if ($resp.StatusCode -eq 200) { $BackendReady = $true; Write-Host "Backend ready!" }
            } catch {}
        }
        if (-not $FrontendReady) {
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -ErrorAction SilentlyContinue
                if ($resp.StatusCode -eq 200) { $FrontendReady = $true; Write-Host "Frontend ready!" }
            } catch {}
        }
        if ($BackendReady -and $FrontendReady) { break }
        Start-Sleep -Seconds 2
    }

    if (-not ($BackendReady -and $FrontendReady)) {
        Write-Error "Timeout waiting for servers."
        exit 1
    }

    if ($Mode -eq 'dev') {
        Write-Host "--------------------------------------------------"
        Write-Host "MistakePatch is running!"
        Write-Host "Frontend: http://localhost:3000"
        Write-Host "Backend : http://localhost:8000"
        Write-Host "Press Ctrl+C to stop servers."
        Write-Host "--------------------------------------------------"
        while ($true) { Start-Sleep -Seconds 1 }
    }
    elseif ($Mode -eq 'test') {
        Write-Host "Running tests..."
        
        Write-Host "3. Running E2E tests..."
        pushd $FrontendDir
        npm run test:e2e
        if ($LASTEXITCODE -ne 0) { throw "E2E tests failed" }
        popd

        Write-Host "Tests completed successfully!"
    }

}
catch {
    Write-Error "An error occurred: $_"
    exit 1
}
finally {
    Write-Host "Stopping servers..."
    foreach ($proc in $Processes) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    
    # Best effort to clean up ports if processes still linger
    $PortPids = Get-NetTCPConnection -LocalPort 8000, 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($p in $PortPids) {
        Write-Host "Found lingering process on port: $p. Terminating..."
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}
