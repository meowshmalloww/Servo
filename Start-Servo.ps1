[CmdletBinding()]
param(
    [string] $ApiUrl = "http://127.0.0.1:8000",
    [string] $CampaignRoot = "",
    [string] $ReconstructionRoot = "",
    [string] $SimulationRoot = "",
    [string] $CarlaRoot = "",
    [switch] $NoApp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$appPath = Join-Path $repoRoot "build\appServo.exe"
if (-not (Test-Path -LiteralPath $appPath)) {
    throw "Servo is not built. Expected: $appPath"
}

function Resolve-WinDeployQt {
    $fromPath = Get-Command windeployqt.exe -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source -First 1
    if ($fromPath) {
        return $fromPath
    }

    $cachePath = Join-Path $repoRoot "build\CMakeCache.txt"
    if (-not (Test-Path -LiteralPath $cachePath -PathType Leaf)) {
        return $null
    }
    $qtDirectoryLine = Get-Content -LiteralPath $cachePath |
        Where-Object { $_ -match '^Qt6_DIR:PATH=' } |
        Select-Object -First 1
    if (-not $qtDirectoryLine) {
        return $null
    }
    $qtCmakeDirectory = $qtDirectoryLine.Substring('Qt6_DIR:PATH='.Length)
    $qtPrefix = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $qtCmakeDirectory))
    $candidate = Join-Path $qtPrefix "bin\windeployqt.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return $candidate
    }
    return $null
}

# A configured build tree can link successfully while still being impossible
# to launch outside Qt Creator.  Deploy only when the required Quick 3D import
# is absent; this is local packaging, not a package installation.
$appDirectory = Split-Path -Parent $appPath
$quick3dRuntime = Join-Path $appDirectory "Qt6Quick3D.dll"
$quick3dPlugin = Join-Path $appDirectory "qml\QtQuick3D\qquick3dplugin.dll"
if (-not (Test-Path -LiteralPath $quick3dRuntime -PathType Leaf) -or
    -not (Test-Path -LiteralPath $quick3dPlugin -PathType Leaf)) {
    $winDeployQt = Resolve-WinDeployQt
    if (-not $winDeployQt) {
        throw "Qt Quick 3D runtime is missing and windeployqt.exe could not be resolved from the configured build."
    }
    & $winDeployQt `
        --qmldir (Join-Path $repoRoot "src\ui") `
        --no-translations `
        --compiler-runtime `
        $appPath
    if ($LASTEXITCODE -ne 0) {
        throw "Qt runtime deployment failed with exit code $LASTEXITCODE."
    }
}

if ([string]::IsNullOrWhiteSpace($CampaignRoot)) {
    $CampaignRoot = Join-Path $repoRoot "campaigns"
}
New-Item -ItemType Directory -Force -Path $CampaignRoot | Out-Null

if ([string]::IsNullOrWhiteSpace($ReconstructionRoot)) {
    $ReconstructionRoot = Join-Path $repoRoot "runtime\reconstruction"
}
New-Item -ItemType Directory -Force -Path $ReconstructionRoot | Out-Null
$env:SERVO_RECONSTRUCTION_ROOT = (Resolve-Path -LiteralPath $ReconstructionRoot).Path

if ([string]::IsNullOrWhiteSpace($SimulationRoot)) {
    # Keep the desktop client, control API, and CARLA worker on the repository's
    # single durable session store. A nested simulations\runtime default made
    # verified runs invisible to the UI even though the API had completed them.
    $SimulationRoot = Join-Path $repoRoot "simulations"
}
New-Item -ItemType Directory -Force -Path $SimulationRoot | Out-Null
$env:SERVO_SIMULATION_ROOT = (Resolve-Path -LiteralPath $SimulationRoot).Path

# The control API needs Google ADK, while physical Gaussian simulation needs
# Servo's pinned CUDA/gsplat runtime. Keep those interpreters explicit instead
# of allowing the worker to fall back to an unrelated system Python.
$simulationPythonCandidates = @(
    @(
        $env:SERVO_SIMULATION_PYTHON,
        (Join-Path $env:LOCALAPPDATA "Servo\reconstruction\venv-py311-cu128\Scripts\python.exe"),
        (Join-Path $repoRoot ".venv-realityci\Scripts\python.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -Unique
)
if ($simulationPythonCandidates.Count -eq 0) {
    throw "Servo's CUDA simulation Python runtime was not found."
}
$env:SERVO_SIMULATION_PYTHON = (Resolve-Path -LiteralPath $simulationPythonCandidates[0]).Path

if (-not [string]::IsNullOrWhiteSpace($CarlaRoot)) {
    if (-not (Test-Path -LiteralPath $CarlaRoot -PathType Container)) {
        throw "CarlaRoot is not a directory: $CarlaRoot"
    }
    $env:SERVO_CARLA_ROOT = (Resolve-Path -LiteralPath $CarlaRoot).Path
}

$uri = [Uri] $ApiUrl
if ($uri.Scheme -notin @("http", "https")) {
    throw "ApiUrl must use http or https."
}

function Test-ControlApi {
    try {
        $health = Invoke-RestMethod -Uri "$ApiUrl/healthz" -TimeoutSec 2
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

$logRoot = Join-Path $repoRoot "tmp\local-control-api"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$pidPath = Join-Path $logRoot "api.pid"
$apiProcess = $null
if (-not (Test-ControlApi)) {
    if (Test-Path -LiteralPath $pidPath) {
        $recordedPid = 0
        if ([int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref] $recordedPid)) {
            $recorded = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
            if ($recorded) {
                throw "A recorded RealityCI API process ($recordedPid) exists but is not healthy. Stop it or inspect $logRoot\stderr.log before starting another instance."
            }
        }
        Remove-Item -LiteralPath $pidPath -Force
    }
    $pythonCandidates = @(
        @(
            (Join-Path $repoRoot ".venv-realityci\Scripts\python.exe"),
            $env:SERVO_PYTHON,
            (Join-Path $env:LOCALAPPDATA "Servo\reconstruction\venv-py311-cu128\Scripts\python.exe"),
            (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    )

    if ($pythonCandidates.Count -eq 0) {
        throw "Python 3.11 was not found. Set SERVO_PYTHON to the existing Servo runtime."
    }

    $python = $pythonCandidates[0]
    & $python -c "import google.adk, uvicorn, fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "The selected Python runtime does not contain Google ADK, FastAPI, and Uvicorn: $python"
    }

    $env:SERVO_CAMPAIGN_ROOT = $CampaignRoot
    $apiProcess = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "cloud.control_api.app.main:app",
                        "--host", $uri.Host, "--port", [string] $uri.Port) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "stderr.log") `
        -PassThru
    Set-Content -LiteralPath $pidPath -Value ([string] $apiProcess.Id) -NoNewline

    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-ControlApi) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-ControlApi)) {
        if ($apiProcess -and -not $apiProcess.HasExited) {
            Stop-Process -Id $apiProcess.Id
        }
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
        throw "RealityCI control API did not become healthy. See $logRoot\stderr.log"
    }
}

$appProcess = $null
if (-not $NoApp) {
    $appProcess = Start-Process -FilePath $appPath -WorkingDirectory $repoRoot -PassThru
}

[pscustomobject]@{
    ApiUrl = $ApiUrl
    ApiStatus = "ok"
    ApiProcessId = if ($apiProcess) { $apiProcess.Id } else { $null }
    AppProcessId = if ($appProcess) { $appProcess.Id } else { $null }
    CampaignRoot = (Resolve-Path -LiteralPath $CampaignRoot).Path
    ReconstructionRoot = $env:SERVO_RECONSTRUCTION_ROOT
    SimulationRoot = $env:SERVO_SIMULATION_ROOT
    CarlaRoot = $env:SERVO_CARLA_ROOT
}
