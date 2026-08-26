[CmdletBinding()]
param(
    [string] $ApiUrl = "http://127.0.0.1:8000",
    [string] $CampaignRoot = "",
    [switch] $NoApp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$appPath = Join-Path $repoRoot "build\appServo.exe"
if (-not (Test-Path -LiteralPath $appPath)) {
    throw "Servo is not built. Expected: $appPath"
}

if ([string]::IsNullOrWhiteSpace($CampaignRoot)) {
    $CampaignRoot = Join-Path $repoRoot "campaigns"
}
New-Item -ItemType Directory -Force -Path $CampaignRoot | Out-Null

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

$apiProcess = $null
if (-not (Test-ControlApi)) {
    $pythonCandidates = @(
        @(
            $env:SERVO_PYTHON,
            (Join-Path $env:LOCALAPPDATA "Servo\reconstruction\venv-py311-cu128\Scripts\python.exe"),
            (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    )

    if ($pythonCandidates.Count -eq 0) {
        throw "Python 3.11 was not found. Set SERVO_PYTHON to the existing Servo runtime."
    }

    $python = $pythonCandidates[0]
    & $python -c "import uvicorn, fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "The selected Python runtime does not contain FastAPI and Uvicorn: $python"
    }

    $logRoot = Join-Path $repoRoot "tmp\local-control-api"
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    $env:SERVO_CAMPAIGN_ROOT = $CampaignRoot
    $apiProcess = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "cloud.control_api.app.main:app",
                        "--host", $uri.Host, "--port", [string] $uri.Port) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "stderr.log") `
        -PassThru

    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-ControlApi) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-ControlApi)) {
        if ($apiProcess -and -not $apiProcess.HasExited) {
            Stop-Process -Id $apiProcess.Id
        }
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
}
