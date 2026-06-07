[CmdletBinding()]
param(
    [ValidateSet("up", "down", "stop", "restart", "status", "logs")]
    [string]$Action = "up",
    [switch]$NoBuild,
    [switch]$FollowLogs,
    [switch]$SkipDockerDesktop,
    [int]$StartupTimeoutSeconds = 240
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$ServicesToWaitFor = @("postgres", "redis", "api", "worker", "web")

function Write-Step {
    param([string]$Message)

    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Invoke-DockerCommand {
    param(
        [string[]]$Arguments,
        [switch]$Quiet
    )

    Push-Location $ProjectRoot
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Quiet) {
            $stdout = & docker @Arguments 2>$null
            return [pscustomobject]@{
                ExitCode = $LASTEXITCODE
                StdOut = ($stdout -join [Environment]::NewLine)
            }
        }

        & docker @Arguments
        return [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            StdOut = ""
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
}

function Invoke-Compose {
    param([string[]]$Arguments)

    $result = Invoke-DockerCommand -Arguments (@("compose") + $Arguments)
    if ($result.ExitCode -ne 0) {
        throw "docker compose $($Arguments -join ' ') failed with exit code $($result.ExitCode)."
    }
}

function Test-DockerDaemon {
    $result = Invoke-DockerCommand -Arguments @("info") -Quiet
    return $result.ExitCode -eq 0
}

function Start-DockerDesktopIfNeeded {
    if ($SkipDockerDesktop) {
        return
    }

    $dockerDesktop = Join-Path $Env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktop)) {
        return
    }

    Write-Step "Starting Docker Desktop"
    Start-Process -FilePath $dockerDesktop | Out-Null
}

function Ensure-DockerReady {
    Assert-Command "docker"

    if (Test-DockerDaemon) {
        return
    }

    Start-DockerDesktopIfNeeded

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 4
        if (Test-DockerDaemon) {
            Write-Step "Docker daemon is ready"
            return
        }
    }

    throw "Docker daemon is not available. Start Docker Desktop and rerun the script."
}

function Ensure-EnvFile {
    $envPath = Join-Path $ProjectRoot ".env"
    if (Test-Path $envPath) {
        return
    }

    $examplePath = Join-Path $ProjectRoot ".env.example"
    if (-not (Test-Path $examplePath)) {
        throw "Missing .env.example. Cannot create a default .env file."
    }

    Copy-Item -Path $examplePath -Destination $envPath
    Write-Warning "Created .env from .env.example. Update secrets and model settings before real use."
}

function Get-ComposeStatus {
    $result = Invoke-DockerCommand -Arguments @("compose", "ps", "--format", "json") -Quiet
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.StdOut)) {
        return @()
    }

    $parsed = $result.StdOut | ConvertFrom-Json
    if ($parsed -is [System.Array]) {
        return $parsed
    }

    return @($parsed)
}

function Wait-ForServices {
    param(
        [string[]]$ServiceNames,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $services = @(Get-ComposeStatus)
        if ($services.Count -eq 0) {
            Start-Sleep -Seconds 3
            continue
        }

        $pending = @()
        $statusText = @()

        foreach ($serviceName in $ServiceNames) {
            $service = $services | Where-Object { $_.Service -eq $serviceName } | Select-Object -First 1
            if (-not $service) {
                $pending += $serviceName
                $statusText += "${serviceName}=missing"
                continue
            }

            $serviceStatus = if ($service.Health) { $service.Health } else { $service.State }
            $statusText += "${serviceName}=$serviceStatus"

            if ($service.State -ne "running") {
                $pending += $serviceName
                continue
            }

            if ($service.Health -and $service.Health -ne "healthy") {
                $pending += $serviceName
            }
        }

        if ($pending.Count -eq 0) {
            Write-Step "All services are healthy"
            return
        }

        Write-Host ("Waiting for services: " + ($statusText -join ", "))
        Start-Sleep -Seconds 5
    }

    Invoke-Compose @("ps")
    throw "Timed out waiting for services to become healthy."
}

function Show-AccessInfo {
    Write-Host ""
    Write-Host "Project is ready:" -ForegroundColor Green
    Write-Host "  Web UI:  http://localhost:3000"
    Write-Host ""
    Write-Host "Useful commands:"
    Write-Host "  .\dev.ps1 logs"
    Write-Host "  .\dev.ps1 status"
    Write-Host "  .\dev.ps1 down"
}

switch ($Action) {
    "up" {
        Ensure-DockerReady
        Ensure-EnvFile
        Write-Step "Validating docker compose configuration"
        Invoke-Compose @("config", "-q")

        $composeArgs = @("up", "-d")
        if (-not $NoBuild) {
            $composeArgs += "--build"
        }

        Write-Step "Starting project stack"
        Invoke-Compose $composeArgs
        Wait-ForServices -ServiceNames $ServicesToWaitFor -TimeoutSeconds $StartupTimeoutSeconds
        Show-AccessInfo

        if ($FollowLogs) {
            Invoke-Compose @("logs", "-f", "--tail", "200")
        }
    }
    "down" {
        Ensure-DockerReady
        Write-Step "Stopping project stack"
        Invoke-Compose @("down", "--remove-orphans")
    }
    "stop" {
        Ensure-DockerReady
        Write-Step "Stopping containers"
        Invoke-Compose @("stop")
    }
    "restart" {
        Ensure-DockerReady
        Write-Step "Restarting containers"
        Invoke-Compose @("restart")
        Wait-ForServices -ServiceNames $ServicesToWaitFor -TimeoutSeconds $StartupTimeoutSeconds
        Show-AccessInfo
    }
    "status" {
        Ensure-DockerReady
        Invoke-Compose @("ps")
    }
    "logs" {
        Ensure-DockerReady
        Invoke-Compose @("logs", "-f", "--tail", "200")
    }
}
