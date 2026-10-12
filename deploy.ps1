param(
    [switch]$Status,
    [switch]$Logs,
    [switch]$Down,
    [switch]$Verify,
    [switch]$Replay,
    [switch]$Opea
)

$ErrorActionPreference = "Stop"
if ($Opea -and $Replay) { throw "OPEA deployment verification requires the live profile. Select replay per query in the UI." }
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = $null
if (Test-Path -LiteralPath (Join-Path $Root ".env") -PathType Leaf) {
    $EnvFile = Join-Path $Root ".env"
} elseif (Test-Path -LiteralPath (Join-Path $Root "CODE/.env") -PathType Leaf) {
    $EnvFile = Join-Path $Root "CODE/.env"
}
$Services = @("simulation", "rag", "agent", "gateway", "ui")
if ($Opea) { $Services = @("opea-reasoner") + $Services }
$StartedAt = Get-Date

function Write-Log {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"), $Message)
}

function Invoke-Compose {
    $Files = @("-f", (Join-Path $Root "docker-compose.yml"))
    if (-not $Replay) { $Files += @("-f", (Join-Path $Root "docker-compose.live.yml")) }
    if ($Opea) { $Files += @("-f", (Join-Path $Root "docker-compose.opea.yml")) }
    $EnvArgs = @()
    if ($EnvFile) { $EnvArgs = @("--env-file", $EnvFile) }
    docker compose --project-directory $Root @EnvArgs @Files @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
}

function Require-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is not installed."
    }
    docker version | Out-Null
    docker compose version | Out-Null
    Write-Log ("Docker: " + (docker version --format '{{.Client.Version}}'))
    Write-Log ("Compose: " + (docker compose version --short))
    if ($EnvFile) { Write-Log ("Using environment file: " + $EnvFile) }
    else { Write-Log "No .env or CODE/.env found; using Compose defaults and exported variables." }
    Invoke-Compose config --quiet
}

function Require-Files {
    $Files = @(
        "docker-compose.yml",
        "CODE/Simulation/Dockerfile.quickstart",
        "CODE/RAG/Dockerfile.quickstart",
        "CODE/Agent/Dockerfile.quickstart",
        "CODE/Agent/ui/Dockerfile.quickstart",
        "scripts/smoke_test.py",
        "docker-compose.live.yml",
        "scripts/smoke_live.py"
    )
    foreach ($File in $Files) {
        $Path = Join-Path $Root $File
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Required file is missing: $Path"
        }
    }
}

function Test-PortFree {
    param([int]$Port)
    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Result = $Client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $Connected = $Result.AsyncWaitHandle.WaitOne(250)
        if ($Connected -and $Client.Connected) {
            throw "Port $Port appears to be in use before deploy."
        }
    }
    finally {
        $Client.Close()
    }
}

function Check-Ports {
    if (Invoke-Compose ps -q) {
        Write-Log "Updating the existing project; Docker will retain its port bindings."
        return
    }
    $Config = Invoke-Compose config --format json | ConvertFrom-Json
    foreach ($Service in $Services) {
        foreach ($Port in $Config.services.$Service.ports) {
            Test-PortFree -Port ([int]$Port.published)
        }
    }
}

function Get-HostPort {
    param([string]$Service, [int]$InternalPort)
    $Binding = Invoke-Compose port $Service $InternalPort | Select-Object -Last 1
    return ($Binding -split ":")[-1]
}

function Get-HealthStatus {
    param([string]$Service)
    $ContainerId = Invoke-Compose ps -q $Service
    if (-not $ContainerId) {
        return ""
    }
    return docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $ContainerId
}

function Wait-Healthy {
    $Timeout = if ($env:DEPLOY_HEALTH_TIMEOUT_SECONDS) { [int]$env:DEPLOY_HEALTH_TIMEOUT_SECONDS } else { 180 }
    foreach ($Service in $Services) {
        Write-Log "Waiting for $Service health..."
        $Deadline = (Get-Date).AddSeconds($Timeout)
        do {
            $Health = Get-HealthStatus -Service $Service
            if ($Health -eq "healthy") {
                Write-Log "$Service is healthy."
                break
            }
            Start-Sleep -Seconds 3
        } while ((Get-Date) -lt $Deadline)
        $Health = Get-HealthStatus -Service $Service
        if ($Health -ne "healthy") {
            Write-Log "$Service did not become healthy; status=$Health"
            Invoke-Compose logs --tail=120 $Service
            exit 1
        }
    }
}

function Invoke-Smoke {
    $SmokeFile = if ($Replay) { "scripts/smoke_test.py" } else { "scripts/smoke_live.py" }
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Python) {
        $Python = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($Python) {
        & $Python.Source (Join-Path $Root $SmokeFile) `
            --simulation-url "http://localhost:$(Get-HostPort simulation 7000)" `
            --rag-url "http://localhost:$(Get-HostPort rag 7001)" `
            --agent-url "http://localhost:$(Get-HostPort agent 9090)" `
            --gateway-url "http://localhost:$(Get-HostPort gateway 8888)" `
            --ui-url "http://localhost:$(Get-HostPort ui 8501)"
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        return
    }

    Write-Log "Host Python is unavailable; running smoke test in a disposable Python container."
    $SmokePath = Join-Path $Root $SmokeFile
    $SimulationPort = if ($env:HOST_SIMULATION_PORT) { $env:HOST_SIMULATION_PORT } else { "7000" }
    $RagPort = if ($env:HOST_RAG_PORT) { $env:HOST_RAG_PORT } else { "7001" }
    $AgentPort = if ($env:HOST_AGENT_PORT) { $env:HOST_AGENT_PORT } else { "9090" }
    $GatewayPort = if ($env:HOST_GATEWAY_PORT) { $env:HOST_GATEWAY_PORT } else { "8888" }
    $UiPort = if ($env:HOST_UI_PORT) { $env:HOST_UI_PORT } else { "8501" }
    docker run --rm `
        --add-host=host.docker.internal:host-gateway `
        -v "${SmokePath}:/smoke_test.py:ro" `
        python:3.11.10-slim-bookworm `
        python /smoke_test.py `
        --simulation-url "http://host.docker.internal:$SimulationPort" `
        --rag-url "http://host.docker.internal:$RagPort" `
        --agent-url "http://host.docker.internal:$AgentPort" `
        --gateway-url "http://host.docker.internal:$GatewayPort" `
        --ui-url "http://host.docker.internal:$UiPort"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Show-Urls {
    $SimulationPort = if ($env:HOST_SIMULATION_PORT) { $env:HOST_SIMULATION_PORT } else { "7000" }
    $RagPort = if ($env:HOST_RAG_PORT) { $env:HOST_RAG_PORT } else { "7001" }
    $AgentPort = if ($env:HOST_AGENT_PORT) { $env:HOST_AGENT_PORT } else { "9090" }
    $GatewayPort = if ($env:HOST_GATEWAY_PORT) { $env:HOST_GATEWAY_PORT } else { "8888" }
    $UiPort = if ($env:HOST_UI_PORT) { $env:HOST_UI_PORT } else { "8501" }
    Write-Host "Simulation: http://localhost:$SimulationPort"
    Write-Host "RAG:        http://localhost:$RagPort"
    Write-Host "Agent:      http://localhost:$AgentPort"
    Write-Host "Gateway:    http://localhost:$GatewayPort"
    Write-Host "UI:         http://localhost:$UiPort"
}

Set-Location $Root

if ($Status) {
    Require-Docker
    Invoke-Compose ps
    exit 0
}
if ($Logs) {
    Require-Docker
    Invoke-Compose logs --tail=200
    exit 0
}
if ($Down) {
    Require-Docker
    Invoke-Compose down
    exit 0
}
if ($Verify) {
    Require-Docker
    Wait-Healthy
    Invoke-Smoke
    exit 0
}

Require-Docker
Require-Files
Check-Ports
Invoke-Compose up -d --build
Wait-Healthy
Invoke-Compose ps
Invoke-Smoke
Show-Urls
$Duration = [int]((Get-Date) - $StartedAt).TotalSeconds
Write-Log "Deployment verified in ${Duration}s."
