param(
    [switch]$Fast,
    [switch]$WithSmoke,
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
        exit $LASTEXITCODE
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
exit $LASTEXITCODE
