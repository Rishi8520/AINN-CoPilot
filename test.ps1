param(
    [switch]$Fast,
    [switch]$WithSmoke,
    [switch]$WithE2E,
    [switch]$StaticOnly,
    [switch]$List,
    [ValidateSet("auto", "local", "docker")]
    [string]$ExecutionMode = "auto",
    [string]$OutputDir = "test-results",
    [string]$Python,
    [string]$DockerImage = "telcomind/test-runner:batch8"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$ArgsList = @("--execution-mode", $ExecutionMode, "--output-dir", $OutputDir, "--docker-image", $DockerImage)
if ($Fast) { $ArgsList += "--fast" }
if ($WithSmoke) { $ArgsList += "--with-smoke" }
if ($StaticOnly) { $ArgsList += "--static-only" }
if ($List) { $ArgsList += "--list" }
if ($Python) {
    $ArgsList += @("--python", $Python)
}

$ContainerArgs = @()
if ($Fast) { $ContainerArgs += "--fast" }
if ($WithSmoke) { $ContainerArgs += "--with-smoke" }
if ($StaticOnly) { $ContainerArgs += "--static-only" }
if ($List) { $ContainerArgs += "--list" }

function Test-RunningStack {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }
    $Rows = docker compose --project-directory $Root ps --format json
    if ($LASTEXITCODE -ne 0 -or -not $Rows) {
        return $false
    }
    $Healthy = $true
    foreach ($Line in $Rows) {
        if (-not $Line.Trim()) { continue }
        $Obj = $Line | ConvertFrom-Json
        if ($Obj.State -ne "running") { $Healthy = $false }
        if ($Obj.Health -and $Obj.Health -ne "healthy") { $Healthy = $false }
    }
    return $Healthy
}

function Invoke-DemoRunner {
    param([string]$PythonExe)
    if (-not (Test-RunningStack)) {
        Write-Error "test.ps1 -WithE2E requires an already running healthy stack. It will not start the stack."
        return 2
    }

    if ($PythonExe) {
        & $PythonExe (Join-Path $Root "scripts/run_demo_scenarios.py") --output-dir "e2e-results"
        return $LASTEXITCODE
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "test.ps1 -WithE2E requires local Python or Docker."
        return 2
    }

    $E2EResults = Join-Path $Root "e2e-results"
    New-Item -ItemType Directory -Force -Path $E2EResults | Out-Null
    docker run --rm `
        --add-host=host.docker.internal:host-gateway `
        -v "${Root}:/repo:ro" `
        -v "${E2EResults}:/e2e-results" `
        -w /repo `
        python:3.11.10-slim-bookworm `
        python scripts/run_demo_scenarios.py --base-url http://host.docker.internal:8888 --output-dir /e2e-results
    return $LASTEXITCODE
}

function Find-Python {
    if ($Python) {
        return $Python
    }
    if ($env:TEST_PYTHON) {
        return $env:TEST_PYTHON
    }
    foreach ($Name in @("python", "python3", "py")) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }
    return $null
}

$PythonExe = Find-Python
if ($PythonExe) {
    & $PythonExe -m pytest --version *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "test.ps1: using local Python: $PythonExe"
        & $PythonExe (Join-Path $Root "scripts/run_test_matrix.py") @ArgsList
        $MatrixExit = $LASTEXITCODE
        if ($MatrixExit -ne 0 -or -not $WithE2E) {
            exit $MatrixExit
        }
        exit (Invoke-DemoRunner -PythonExe $PythonExe)
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "test.ps1: no usable local Python and Docker is unavailable."
    exit 2
}

Write-Host "test.ps1: using Docker fallback image: $DockerImage"
docker build -f Dockerfile.test -t $DockerImage $Root
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$Results = Join-Path $Root "test-results"
New-Item -ItemType Directory -Force -Path $Results | Out-Null
docker run --rm --network none `
    -v "${Root}:/repo:ro" `
    -v "${Results}:/test-results" `
    -w /repo `
    $DockerImage `
    python scripts/run_test_matrix.py --execution-mode local --output-dir /test-results @ContainerArgs
$MatrixExit = $LASTEXITCODE
if ($MatrixExit -ne 0 -or -not $WithE2E) {
    exit $MatrixExit
}
exit (Invoke-DemoRunner -PythonExe $null)
