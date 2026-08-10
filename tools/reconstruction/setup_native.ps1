[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$InstallCudaToolkit
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "Servo's setup_native.ps1 supports native Windows only."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeRoot = Join-Path $env:LOCALAPPDATA "Servo\reconstruction"
$toolchainRoot = Join-Path $runtimeRoot "toolchain"
$colmapRoot = Join-Path $toolchainRoot "colmap-4.1.1"
$vocabularyRoot = Join-Path $toolchainRoot "colmap-vocab"
$vocabularyPath = Join-Path $vocabularyRoot "vocab_tree_faiss_flickr100K_words32K.bin"
$environmentRoot = Join-Path $runtimeRoot "venv-py311-cu128"
$cudaNvcc = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvcc.exe"

New-Item -ItemType Directory -Force -Path $toolchainRoot | Out-Null

if ($InstallCudaToolkit -and -not (Test-Path -LiteralPath $cudaNvcc)) {
    winget install --id Nvidia.CUDA --exact --version 12.8 --silent `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install NVIDIA CUDA Toolkit 12.8."
    }
}

if (-not (Test-Path -LiteralPath $cudaNvcc)) {
    throw "CUDA Toolkit 12.8 is missing. Re-run with -InstallCudaToolkit or install Nvidia.CUDA version 12.8 with winget."
}

if (-not (Test-Path -LiteralPath $colmapRoot)) {
    $downloadPath = Join-Path ([System.IO.Path]::GetTempPath()) "servo-colmap-4.1.1-$([guid]::NewGuid().ToString('N')).zip"
    $extractRoot = Join-Path $toolchainRoot ".colmap-4.1.1-$([guid]::NewGuid().ToString('N')).tmp"
    try {
        Invoke-WebRequest `
            -Uri "https://github.com/colmap/colmap/releases/download/4.1.1/colmap-x64-windows-cuda.zip" `
            -OutFile $downloadPath
        $digest = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $expected = "b06064e7e4bd34f5b4ef71b442d3537d95d57c666dbec5a3b475902ccd832b9b"
        if ($digest -ne $expected) {
            throw "COLMAP archive checksum mismatch. Expected $expected; received $digest."
        }
        New-Item -ItemType Directory -Path $extractRoot | Out-Null
        Expand-Archive -LiteralPath $downloadPath -DestinationPath $extractRoot
        $entries = @(Get-ChildItem -LiteralPath $extractRoot -Force)
        if ($entries.Count -eq 1 -and $entries[0].PSIsContainer) {
            Move-Item -LiteralPath $entries[0].FullName -Destination $colmapRoot
            Remove-Item -LiteralPath $extractRoot
        } else {
            Move-Item -LiteralPath $extractRoot -Destination $colmapRoot
        }
    } finally {
        if (Test-Path -LiteralPath $downloadPath) {
            Remove-Item -LiteralPath $downloadPath
        }
        if (Test-Path -LiteralPath $extractRoot) {
            $resolvedExtract = (Resolve-Path -LiteralPath $extractRoot).Path
            $resolvedToolchain = (Resolve-Path -LiteralPath $toolchainRoot).Path
            if ($resolvedExtract.StartsWith($resolvedToolchain, [System.StringComparison]::OrdinalIgnoreCase)) {
                Remove-Item -LiteralPath $resolvedExtract -Recurse -Force
            }
        }
    }
}

if (-not (Test-Path -LiteralPath $vocabularyPath)) {
    New-Item -ItemType Directory -Force -Path $vocabularyRoot | Out-Null
    $vocabularyDownload = Join-Path ([System.IO.Path]::GetTempPath()) "servo-colmap-vocab-$([guid]::NewGuid().ToString('N')).bin"
    try {
        Invoke-WebRequest `
            -Uri "https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_faiss_flickr100K_words32K.bin" `
            -OutFile $vocabularyDownload
        $vocabularyDigest = (Get-FileHash -LiteralPath $vocabularyDownload -Algorithm SHA256).Hash.ToLowerInvariant()
        $expectedVocabularyDigest = "921e894b7d81f5cf223df824a02b9932660cddf00a815c93fc7c0bd690fc639e"
        if ($vocabularyDigest -ne $expectedVocabularyDigest) {
            throw "COLMAP vocabulary checksum mismatch. Expected $expectedVocabularyDigest; received $vocabularyDigest."
        }
        Move-Item -LiteralPath $vocabularyDownload -Destination $vocabularyPath
    } finally {
        if (Test-Path -LiteralPath $vocabularyDownload) {
            Remove-Item -LiteralPath $vocabularyDownload
        }
    }
}

if (-not (Test-Path -LiteralPath $environmentRoot)) {
    & $Python -m venv --system-site-packages $environmentRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the native Servo Python environment."
    }
}

$environmentPython = Join-Path $environmentRoot "Scripts\python.exe"
& $environmentPython -m pip install --upgrade pip
& $environmentPython -m pip install --requirement (Join-Path $scriptRoot "requirements-native.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to install the pinned native reconstruction packages."
}

& $environmentPython -c "import torch; assert torch.__version__ == '2.11.0+cu128', torch.__version__; assert torch.cuda.is_available(); print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) {
    throw "The native environment cannot reuse the required PyTorch 2.11.0+cu128 CUDA runtime."
}

$worker = Join-Path $scriptRoot "servo_worker.py"
& $environmentPython $worker provision-gsplat `
    --requirement (Join-Path $scriptRoot "requirements-gsplat-source.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to build Servo's pinned native gsplat extension."
}

$env:SERVO_COLMAP = Join-Path $colmapRoot "COLMAP.bat"
$env:SERVO_COLMAP_VOCAB_TREE = $vocabularyPath
& $environmentPython $worker preflight --verify-kernel
if ($LASTEXITCODE -ne 0) {
    throw "Servo's native reconstruction preflight or gsplat CUDA kernel verification failed."
}

Write-Host "Native Servo reconstruction worker is ready."
Write-Host "Python: $environmentPython"
Write-Host "COLMAP: $env:SERVO_COLMAP"
