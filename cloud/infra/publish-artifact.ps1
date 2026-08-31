# Publish a large Servo world, model, checkpoint, dataset, or evidence bundle.
# Object bytes go to Cloud Storage; Firestore receives bounded searchable metadata.

param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$ArtifactBucket,
    [Parameter(Mandatory = $true)]
    [ValidateSet("world", "model", "checkpoint", "dataset", "evidence")]
    [string]$Kind,
    [Parameter(Mandatory = $true)][string]$ArtifactId,
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$FirestoreDatabase = "(default)",
    [string]$FirestoreCollection = "servo_artifacts"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ArtifactId -notmatch '^[a-z0-9][a-z0-9._-]{2,95}$') {
    throw "ArtifactId must be 3-96 lowercase letters, digits, dots, underscores, or hyphens."
}
if ($FirestoreCollection -notmatch '^[A-Za-z0-9_-]+$') {
    throw "FirestoreCollection must be one collection name."
}

$resolvedSource = (Resolve-Path -LiteralPath $Source -ErrorAction Stop).Path
$sourceItem = Get-Item -LiteralPath $resolvedSource -Force
$files = if ($sourceItem.PSIsContainer) {
    @(Get-ChildItem -LiteralPath $resolvedSource -Recurse -File -Force |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' } |
        Sort-Object FullName)
} else {
    @($sourceItem)
}
if ($files.Count -eq 0) {
    throw "The source contains no files."
}

$entries = foreach ($file in $files) {
    $relative = if ($sourceItem.PSIsContainer) {
        [System.IO.Path]::GetRelativePath($resolvedSource, $file.FullName).Replace('\', '/')
    } else {
        $file.Name
    }
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{
        path = $relative
        sizeBytes = [int64]$file.Length
        sha256 = "sha256:$hash"
    }
}
$totalBytes = [int64](($entries | Measure-Object -Property sizeBytes -Sum).Sum)
$createdAt = [DateTime]::UtcNow.ToString("o")
$prefix = "artifacts/$Kind/$ArtifactId"
$gsUri = "gs://$ArtifactBucket/$prefix"
$manifest = [ordered]@{
    schema = "servo.cloud-artifact-manifest/v1"
    artifactId = $ArtifactId
    kind = $Kind
    createdAt = $createdAt
    sourceName = $sourceItem.Name
    storageContract = "object-bytes-in-gcs; metadata-only-in-firestore"
    payloadUri = "$gsUri/payload"
    fileCount = $files.Count
    totalBytes = $totalBytes
    files = @($entries)
}
$manifestJson = $manifest | ConvertTo-Json -Depth 8 -Compress
$manifestBytes = [System.Text.Encoding]::UTF8.GetBytes($manifestJson)
$sha = [System.Security.Cryptography.SHA256]::HashData($manifestBytes)
$manifestHash = "sha256:" + [Convert]::ToHexString($sha).ToLowerInvariant()
$manifestJson = $manifest | ConvertTo-Json -Depth 8

$temporaryManifest = Join-Path ([System.IO.Path]::GetTempPath()) "$ArtifactId-manifest.json"
try {
    [System.IO.File]::WriteAllText(
        $temporaryManifest,
        $manifestJson + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )

    gcloud storage buckets describe "gs://$ArtifactBucket" --project $ProjectId *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Cloud Storage bucket does not exist or is not accessible: gs://$ArtifactBucket"
    }
    gcloud storage objects describe "$gsUri/manifest.json" --project $ProjectId *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "Artifact already exists; choose a new versioned ArtifactId: $ArtifactId"
    }

    if ($sourceItem.PSIsContainer) {
        gcloud storage rsync $resolvedSource "$gsUri/payload" --recursive
    } else {
        gcloud storage cp $resolvedSource "$gsUri/payload/$($sourceItem.Name)"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Artifact payload upload failed."
    }
    gcloud storage cp $temporaryManifest "$gsUri/manifest.json"
    if ($LASTEXITCODE -ne 0) {
        throw "Artifact manifest upload failed."
    }

    $accessToken = (gcloud auth print-access-token).Trim()
    if (-not $accessToken) {
        throw "Could not obtain a Google Cloud access token for Firestore registration."
    }
    $escapedDatabase = [Uri]::EscapeDataString($FirestoreDatabase)
    $documentUrl = "https://firestore.googleapis.com/v1/projects/$ProjectId/databases/$escapedDatabase/documents/$FirestoreCollection/$ArtifactId"
    $document = @{
        fields = @{
            schema = @{ stringValue = "servo.firestore-artifact-index/v1" }
            artifact_id = @{ stringValue = $ArtifactId }
            kind = @{ stringValue = $Kind }
            gs_uri = @{ stringValue = $gsUri }
            manifest_uri = @{ stringValue = "$gsUri/manifest.json" }
            manifest_sha256 = @{ stringValue = $manifestHash }
            file_count = @{ integerValue = [string]$files.Count }
            total_bytes = @{ integerValue = [string]$totalBytes }
            updated_at = @{ timestampValue = $createdAt }
            storage_contract = @{ stringValue = "metadata-only; artifact-bytes-in-gcs" }
        }
    } | ConvertTo-Json -Depth 8 -Compress
    Invoke-RestMethod -Method Patch -Uri $documentUrl -Headers @{
        Authorization = "Bearer $accessToken"
    } -ContentType "application/json" -Body $document | Out-Null

    Write-Host "Published: $gsUri" -ForegroundColor Green
    Write-Host "Manifest:  $gsUri/manifest.json"
    Write-Host "Firestore: $FirestoreCollection/$ArtifactId"
    Write-Host "SHA-256:   $manifestHash"
} finally {
    Remove-Item -LiteralPath $temporaryManifest -Force -ErrorAction SilentlyContinue
}
