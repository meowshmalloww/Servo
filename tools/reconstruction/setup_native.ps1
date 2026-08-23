[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$InstallCudaToolkit,
    [switch]$Offline,
    [switch]$ProvisionPriorsOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "Servo's setup_native.ps1 supports native Windows only."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeRoot = Join-Path $env:LOCALAPPDATA "Servo\reconstruction"
$toolchainRoot = Join-Path $runtimeRoot "toolchain"
$archiveRoot = Join-Path $toolchainRoot "archives"
$modelsRoot = Join-Path $runtimeRoot "models"
$colmapRoot = Join-Path $toolchainRoot "colmap-4.1.1"
$vocabularyRoot = Join-Path $toolchainRoot "colmap-vocab"
$vocabularyPath = Join-Path $vocabularyRoot "vocab_tree_faiss_flickr100K_words32K.bin"
$environmentRoot = Join-Path $runtimeRoot "venv-py311-cu128"
$cudaNvcc = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvcc.exe"
$videoDepthCommit = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
$videoDepthSourceRoot = Join-Path $toolchainRoot "video-depth-anything-$videoDepthCommit"
$videoDepthArchivePath = Join-Path $archiveRoot "video-depth-anything-$videoDepthCommit.zip"
$videoDepthCheckpointRoot = Join-Path $modelsRoot "video-depth-anything-small"
$videoDepthCheckpointPath = Join-Path $videoDepthCheckpointRoot "video_depth_anything_vits.pth"
$oneFormerCommit = "05f2812b1eccf9909b3897777450f8d68148cafc"
$oneFormerRoot = Join-Path $modelsRoot "oneformer-ade20k-swin-tiny-$oneFormerCommit"

function Test-VerifiedFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][long]$ExpectedBytes,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        return $false
    }
    $item = Get-Item -LiteralPath $LiteralPath
    if ($item.Length -ne $ExpectedBytes) {
        return $false
    }
    $digest = (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToLowerInvariant()
    return $digest -eq $ExpectedSha256.ToLowerInvariant()
}

function Get-PythonSourceManifestSha256 {
    param([Parameter(Mandatory = $true)][string]$SourceRoot)

    $pythonRoot = Join-Path $SourceRoot "video_depth_anything"
    $utilityRoot = Join-Path $SourceRoot "utils"
    if (-not (Test-Path -LiteralPath $pythonRoot -PathType Container) `
        -or -not (Test-Path -LiteralPath $utilityRoot -PathType Container)) {
        return ""
    }
    $resolvedRoot = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd('\')
    $manifest = [ordered]@{}
    @(
        Get-ChildItem -LiteralPath $pythonRoot -Filter "*.py" -Recurse -File
        Get-ChildItem -LiteralPath $utilityRoot -Filter "*.py" -Recurse -File
    ) |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($resolvedRoot.Length + 1).Replace('\', '/')
            $manifest[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    $canonicalJson = $manifest | ConvertTo-Json -Compress
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($canonicalJson)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        return -join ($algorithm.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    } finally {
        $algorithm.Dispose()
    }
}

function Install-VerifiedFile {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][long]$ExpectedBytes,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [string[]]$CacheCandidates = @()
    )

    if (Test-VerifiedFile -LiteralPath $Destination -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256) {
        Write-Host "${Name}: verified"
        return
    }

    $destinationParent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
    $temporary = Join-Path $destinationParent ".$([System.IO.Path]::GetFileName($Destination)).$([guid]::NewGuid().ToString('N')).tmp"
    try {
        $cacheSource = $null
        foreach ($candidate in $CacheCandidates) {
            if (Test-VerifiedFile -LiteralPath $candidate -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256) {
                $cacheSource = $candidate
                break
            }
        }

        if ($null -ne $cacheSource) {
            Copy-Item -LiteralPath $cacheSource -Destination $temporary
            Write-Host "${Name}: copied from verified local cache"
        } elseif ($Offline) {
            throw "$Name is not present in a verified local cache and -Offline forbids downloading it."
        } else {
            Write-Host "${Name}: downloading pinned artifact"
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $temporary
        }

        if (-not (Test-VerifiedFile -LiteralPath $temporary -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256)) {
            $receivedBytes = if (Test-Path -LiteralPath $temporary) {
                (Get-Item -LiteralPath $temporary).Length
            } else {
                0
            }
            $receivedHash = if (Test-Path -LiteralPath $temporary) {
                (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
            } else {
                "missing"
            }
            throw "$Name integrity check failed. Expected $ExpectedBytes bytes / $ExpectedSha256; received $receivedBytes bytes / $receivedHash."
        }

        if (Test-Path -LiteralPath $Destination) {
            $backup = "$Destination.$([guid]::NewGuid().ToString('N')).backup"
            try {
                [System.IO.File]::Replace($temporary, $Destination, $backup, $true)
            } finally {
                if (Test-Path -LiteralPath $backup) {
                    Remove-Item -LiteralPath $backup -Force
                }
            }
        } else {
            [System.IO.File]::Move($temporary, $Destination)
        }
        if (-not (Test-VerifiedFile -LiteralPath $Destination -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256)) {
            throw "$Name failed verification after atomic publication."
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Remove-VerifiedToolchainTemporaryDirectory {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Container)) {
        return
    }
    $resolvedTemporary = [System.IO.Path]::GetFullPath($LiteralPath)
    $resolvedToolchain = [System.IO.Path]::GetFullPath($toolchainRoot).TrimEnd('\') + '\'
    if (-not $resolvedTemporary.StartsWith($resolvedToolchain, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a temporary directory outside Servo's reconstruction toolchain."
    }
    Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
}

function Install-VideoDepthSource {
    $markerPath = Join-Path $videoDepthSourceRoot ".servo-provisioning.json"
    $entryPoint = Join-Path $videoDepthSourceRoot "video_depth_anything\video_depth.py"
    $entryPointReady = Test-VerifiedFile `
        -LiteralPath $entryPoint `
        -ExpectedBytes 6712 `
        -ExpectedSha256 "208e882d60a41434b3a0d9935a7025b01cce0756c17b3d889c6db0c4c945eb29"
    $sourceManifestReady = (Get-PythonSourceManifestSha256 -SourceRoot $videoDepthSourceRoot) `
        -eq "40d096e92b5000790416ac4cc519af64adc8cb74354490535ce73c56b39dc581"
    $markerReady = $false
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        try {
            $marker = Get-Content -Raw -LiteralPath $markerPath | ConvertFrom-Json
            $markerReady = $marker.schema -eq "servo.provisioned-source/v1" `
                -and $marker.commit -eq $videoDepthCommit `
                -and $marker.archiveSha256 -eq "012dc88e5feb7e51f5794f9b8013f4c786aa3d61c60b8e0c3c5a45e1e0feb7c5" `
                -and $marker.pythonSourceManifestSha256 -eq "40d096e92b5000790416ac4cc519af64adc8cb74354490535ce73c56b39dc581"
        } catch {
            $markerReady = $false
        }
    }
    if ($entryPointReady -and $sourceManifestReady -and $markerReady) {
        Write-Host "Video Depth Anything source: verified"
        return
    }
    if ($entryPointReady -and $sourceManifestReady) {
        $marker = [ordered]@{
            schema = "servo.provisioned-source/v1"
            commit = $videoDepthCommit
            archiveBytes = 7905704
            archiveSha256 = "012dc88e5feb7e51f5794f9b8013f4c786aa3d61c60b8e0c3c5a45e1e0feb7c5"
            pythonSourceManifestSha256 = "40d096e92b5000790416ac4cc519af64adc8cb74354490535ce73c56b39dc581"
            license = "Apache-2.0"
        } | ConvertTo-Json
        $markerTemporary = "$markerPath.$([guid]::NewGuid().ToString('N')).tmp"
        try {
            [System.IO.File]::WriteAllText(
                $markerTemporary,
                $marker + [Environment]::NewLine,
                [System.Text.UTF8Encoding]::new($false))
            if (Test-Path -LiteralPath $markerPath) {
                $markerBackup = "$markerPath.$([guid]::NewGuid().ToString('N')).backup"
                try {
                    [System.IO.File]::Replace(
                        $markerTemporary,
                        $markerPath,
                        $markerBackup,
                        $true)
                } finally {
                    if (Test-Path -LiteralPath $markerBackup) {
                        Remove-Item -LiteralPath $markerBackup -Force
                    }
                }
            } else {
                [System.IO.File]::Move($markerTemporary, $markerPath)
            }
        } finally {
            if (Test-Path -LiteralPath $markerTemporary) {
                Remove-Item -LiteralPath $markerTemporary -Force
            }
        }
        Write-Host "Video Depth Anything source: verified and refreshed provenance marker"
        return
    }
    if (Test-Path -LiteralPath $videoDepthSourceRoot) {
        throw "The versioned Video Depth Anything source directory exists but is not the pinned verified tree: $videoDepthSourceRoot"
    }

    Install-VerifiedFile `
        -Name "Video Depth Anything source archive" `
        -Destination $videoDepthArchivePath `
        -Uri "https://codeload.github.com/DepthAnything/Video-Depth-Anything/zip/$videoDepthCommit" `
        -ExpectedBytes 7905704 `
        -ExpectedSha256 "012dc88e5feb7e51f5794f9b8013f4c786aa3d61c60b8e0c3c5a45e1e0feb7c5"

    $extractRoot = Join-Path $toolchainRoot ".video-depth-anything-$([guid]::NewGuid().ToString('N')).tmp"
    try {
        New-Item -ItemType Directory -Path $extractRoot | Out-Null
        Expand-Archive -LiteralPath $videoDepthArchivePath -DestinationPath $extractRoot
        $entries = @(Get-ChildItem -LiteralPath $extractRoot -Force)
        if ($entries.Count -ne 1 -or -not $entries[0].PSIsContainer) {
            throw "The pinned Video Depth Anything archive has an unexpected root layout."
        }
        $extractedSource = $entries[0].FullName
        $extractedEntryPoint = Join-Path $extractedSource "video_depth_anything\video_depth.py"
        if (-not (Test-VerifiedFile `
            -LiteralPath $extractedEntryPoint `
            -ExpectedBytes 6712 `
            -ExpectedSha256 "208e882d60a41434b3a0d9935a7025b01cce0756c17b3d889c6db0c4c945eb29")) {
            throw "The verified Video Depth Anything archive did not extract the expected inference source."
        }
        $sourceManifestSha256 = Get-PythonSourceManifestSha256 -SourceRoot $extractedSource
        if ($sourceManifestSha256 -ne "40d096e92b5000790416ac4cc519af64adc8cb74354490535ce73c56b39dc581") {
            throw "The verified Video Depth Anything archive has an unexpected Python source manifest."
        }
        $marker = [ordered]@{
            schema = "servo.provisioned-source/v1"
            commit = $videoDepthCommit
            archiveBytes = 7905704
            archiveSha256 = "012dc88e5feb7e51f5794f9b8013f4c786aa3d61c60b8e0c3c5a45e1e0feb7c5"
            pythonSourceManifestSha256 = $sourceManifestSha256
            license = "Apache-2.0"
        } | ConvertTo-Json
        [System.IO.File]::WriteAllText(
            (Join-Path $extractedSource ".servo-provisioning.json"),
            $marker + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $extractedSource -Destination $videoDepthSourceRoot
        Write-Host "Video Depth Anything source: provisioned pinned commit $videoDepthCommit"
    } finally {
        Remove-VerifiedToolchainTemporaryDirectory -LiteralPath $extractRoot
    }
}

function Get-HuggingFaceCacheRoots {
    $roots = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($env:HF_HUB_CACHE)) {
        $roots.Add($env:HF_HUB_CACHE)
    }
    if (-not [string]::IsNullOrWhiteSpace($env:HF_HOME)) {
        $roots.Add((Join-Path $env:HF_HOME "hub"))
    }
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $roots.Add((Join-Path $env:USERPROFILE ".cache\huggingface\hub"))
    }
    return @($roots | Select-Object -Unique)
}

function Get-ModelCacheCandidates {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryDirectory,
        [Parameter(Mandatory = $true)][string]$Revision,
        [Parameter(Mandatory = $true)][string]$FileName
    )
    $candidates = @()
    foreach ($cacheRoot in Get-HuggingFaceCacheRoots) {
        $candidates += Join-Path $cacheRoot "$RepositoryDirectory\snapshots\$Revision\$FileName"
    }
    return $candidates
}

New-Item -ItemType Directory -Force -Path $toolchainRoot, $archiveRoot, $modelsRoot | Out-Null

Install-VideoDepthSource

$videoDepthCheckpointRevision = "256875362cff76724b920335dfb4b29dd611f66e"
Install-VerifiedFile `
    -Name "Video Depth Anything Small checkpoint" `
    -Destination $videoDepthCheckpointPath `
    -Uri "https://huggingface.co/depth-anything/Video-Depth-Anything-Small/resolve/$videoDepthCheckpointRevision/video_depth_anything_vits.pth?download=true" `
    -ExpectedBytes 116440756 `
    -ExpectedSha256 "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609" `
    -CacheCandidates (Get-ModelCacheCandidates `
        -RepositoryDirectory "models--depth-anything--Video-Depth-Anything-Small" `
        -Revision $videoDepthCheckpointRevision `
        -FileName "video_depth_anything_vits.pth")

$oneFormerFiles = @(
    @{ Name = "config.json"; Bytes = 84284; Sha256 = "091cbc7c980128ae63b2a15d882923f326f85926ef163adad00c24bd90228896" },
    @{ Name = "preprocessor_config.json"; Bytes = 8709; Sha256 = "2c3c403d8414263e732996bb2ffeab80dd5ced0068ab11bfe5adf476ef75823c" },
    @{ Name = "pytorch_model.bin"; Bytes = 203389501; Sha256 = "909b07dbf4129c2bbb8df4498e35dcd46f305e3ec45329d3ff6d4f0360de27f3" },
    @{ Name = "merges.txt"; Bytes = 524619; Sha256 = "9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a" },
    @{ Name = "vocab.json"; Bytes = 1059962; Sha256 = "e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349" },
    @{ Name = "tokenizer_config.json"; Bytes = 807; Sha256 = "64dd88e64d791e3be4d38be62d7e77e0a24df9e79205ac740af505aa2e94c367" },
    @{ Name = "special_tokens_map.json"; Bytes = 472; Sha256 = "c4864a9376a8401918425bed71fc14fc0e81f9b59ec45c1cf96cccb2df508eac" }
)
foreach ($asset in $oneFormerFiles) {
    Install-VerifiedFile `
        -Name "OneFormer ADE20K Swin-tiny $($asset.Name)" `
        -Destination (Join-Path $oneFormerRoot $asset.Name) `
        -Uri "https://huggingface.co/shi-labs/oneformer_ade20k_swin_tiny/resolve/$oneFormerCommit/$($asset.Name)?download=true" `
        -ExpectedBytes $asset.Bytes `
        -ExpectedSha256 $asset.Sha256 `
        -CacheCandidates (Get-ModelCacheCandidates `
            -RepositoryDirectory "models--shi-labs--oneformer_ade20k_swin_tiny" `
            -Revision $oneFormerCommit `
            -FileName $asset.Name)
}

if ($ProvisionPriorsOnly) {
    Write-Host "Pinned r7 geometry priors are ready."
    Write-Host "Video depth source: $videoDepthSourceRoot"
    Write-Host "Video depth checkpoint: $videoDepthCheckpointPath"
    Write-Host "OneFormer checkpoint: $oneFormerRoot"
    return
}

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
& $environmentPython -m pip install --requirement (Join-Path $scriptRoot "requirements-native.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to install the pinned native reconstruction packages."
}

& $environmentPython -c "import importlib.metadata as m, torch, torchvision, transformers, cv2, numpy, PIL, scipy; assert torch.__version__ == '2.11.0+cu128', torch.__version__; assert torch.version.cuda == '12.8', torch.version.cuda; assert torch.cuda.is_available(); assert torchvision.__version__ == '0.26.0+cpu', torchvision.__version__; assert transformers.__version__ == '5.13.0', transformers.__version__; assert cv2.__version__ == '4.11.0', cv2.__version__; assert numpy.__version__ == '1.26.4', numpy.__version__; assert PIL.__version__ == '12.1.1', PIL.__version__; assert scipy.__version__ == '1.16.3', scipy.__version__; assert m.version('easydict') == '1.9'; assert m.version('einops') == '0.8.2'; assert m.version('tqdm') == '4.67.3'; print(torch.__version__, torch.version.cuda, torchvision.__version__, transformers.__version__, torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) {
    throw "The native environment does not match the pinned r7 CUDA and geometry-prior package contract."
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
