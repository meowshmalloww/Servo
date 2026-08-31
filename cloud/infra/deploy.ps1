# Reproducible Servo deployment: Firebase-authenticated Cloud Run API plus a
# background Google ADK campaign job. Local CARLA/GPU reconstruction is not
# uploaded or represented as cloud execution.

param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$Region,
    [string]$FirebaseProjectId = "",
    [string]$ApiService = "servo-realityci-api",
    [string]$CampaignJobName = "servo-campaign-job",
    [string]$ArtifactBucket = "",
    [string]$GcsPrefix = "campaigns"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$firebaseProject = if ($FirebaseProjectId) { $FirebaseProjectId } else { $ProjectId }
$bucket = if ($ArtifactBucket) { $ArtifactBucket } else { "$ProjectId-servo-artifacts" }
$apiServiceAccountName = "servo-realityci-api"
$jobServiceAccountName = "servo-realityci-job"
$apiServiceAccount = "$apiServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$jobServiceAccount = "$jobServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$commitSha = (git -C $repoRoot rev-parse HEAD).Trim()

function Step([string]$message) {
    Write-Host ""
    Write-Host "== $message ==" -ForegroundColor Cyan
}

function Test-Gcloud([string[]]$Arguments) {
    # PowerShell 7 can promote native stderr from an expected nonzero probe to
    # a terminating NativeCommandError when the script is fail-fast. Keep the
    # probe quiet and return only its exit status; real mutations remain strict.
    $previousPreference = $ErrorActionPreference
    $hasNativePreference = Test-Path variable:PSNativeCommandUseErrorActionPreference
    if ($hasNativePreference) {
        $previousNativePreference = $PSNativeCommandUseErrorActionPreference
    }
    try {
        $ErrorActionPreference = "SilentlyContinue"
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        & gcloud @Arguments 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } finally {
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
        $ErrorActionPreference = $previousPreference
    }
}

function Ensure-ServiceAccount([string]$name, [string]$displayName) {
    if (-not (Test-Gcloud @(
        "iam", "service-accounts", "describe",
        "$name@$ProjectId.iam.gserviceaccount.com", "--project", $ProjectId
    ))) {
        gcloud iam service-accounts create $name --project $ProjectId `
            --display-name $displayName
    }
}

Step "Project and APIs"
gcloud config set project $ProjectId
gcloud config set run/region $Region
gcloud services enable `
    aiplatform.googleapis.com `
    artifactregistry.googleapis.com `
    cloudbuild.googleapis.com `
    identitytoolkit.googleapis.com `
    iamcredentials.googleapis.com `
    logging.googleapis.com `
    firestore.googleapis.com `
    run.googleapis.com `
    secretmanager.googleapis.com `
    storage.googleapis.com

Step "Dedicated service identities"
Ensure-ServiceAccount $apiServiceAccountName "Servo RealityCI API"
Ensure-ServiceAccount $jobServiceAccountName "Servo RealityCI campaign job"

Step "Firestore metadata database"
if (-not (Test-Gcloud @(
    "firestore", "databases", "describe", "--database=(default)",
    "--project", $ProjectId
))) {
    gcloud firestore databases create --database="(default)" `
        --location=$Region --type=firestore-native --project=$ProjectId
}
foreach ($serviceAccount in @($apiServiceAccount, $jobServiceAccount)) {
    gcloud projects add-iam-policy-binding $ProjectId `
        --member "serviceAccount:$serviceAccount" --role roles/datastore.user `
        --condition None
}

Step "Artifact Registry"
if (-not (Test-Gcloud @(
    "artifacts", "repositories", "describe", "servo", "--location", $Region,
    "--project", $ProjectId
))) {
    gcloud artifacts repositories create servo --repository-format docker `
        --location $Region --project $ProjectId
}

Step "Versioned campaign artifact bucket"
if (-not (Test-Gcloud @(
    "storage", "buckets", "describe", "gs://$bucket", "--project", $ProjectId
))) {
    gcloud storage buckets create "gs://$bucket" --project $ProjectId `
        --location $Region --uniform-bucket-level-access
}
gcloud storage buckets update "gs://$bucket" --versioning
$lifecyclePath = Join-Path ([System.IO.Path]::GetTempPath()) "servo-gcs-lifecycle.json"
[System.IO.File]::WriteAllText(
    $lifecyclePath,
    '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30,"isLive":false}}]}',
    [System.Text.UTF8Encoding]::new($false)
)
gcloud storage buckets update "gs://$bucket" --lifecycle-file $lifecyclePath
gcloud storage buckets add-iam-policy-binding "gs://$bucket" `
    --member "serviceAccount:$apiServiceAccount" --role roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding "gs://$bucket" `
    --member "serviceAccount:$jobServiceAccount" --role roles/storage.objectAdmin

Step "Vertex AI permission for the ADK campaign job"
gcloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$jobServiceAccount" --role roles/aiplatform.user `
    --condition None

Step "Build API and campaign job in Cloud Build"
gcloud builds submit $repoRoot `
    --config "$repoRoot\cloud\infra\cloudbuild-api.yaml" `
    --substitutions "_REGION=$Region,_SERVICE=$ApiService"
gcloud builds submit $repoRoot `
    --config "$repoRoot\cloud\infra\cloudbuild-job.yaml" `
    --substitutions "_REGION=$Region,_IMAGE=$CampaignJobName,_DOCKERFILE=cloud/campaign_job/Dockerfile"

Step "Create or update the background ADK campaign job"
$jobImage = "$Region-docker.pkg.dev/$ProjectId/servo/$CampaignJobName`:cpu"
$jobExists = Test-Gcloud @(
    "run", "jobs", "describe", $CampaignJobName, "--region", $Region,
    "--project", $ProjectId
)
$jobAction = if ($jobExists) { "update" } else { "create" }
gcloud run jobs $jobAction $CampaignJobName `
    --project $ProjectId --region $Region --image $jobImage `
    --service-account $jobServiceAccount `
    --cpu 2 --memory 4Gi --task-timeout 3600s --max-retries 1 `
    --set-env-vars "SERVO_GCS_BUCKET=$bucket,SERVO_GCS_PREFIX=$GcsPrefix,SERVO_FIRESTORE_DATABASE=(default),SERVO_FIRESTORE_COLLECTION=servo_campaigns,SERVO_COMMIT_SHA=$commitSha,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region,GOOGLE_GENAI_USE_VERTEXAI=true"

Step "Allow only the API identity to execute the campaign job"
gcloud run jobs add-iam-policy-binding $CampaignJobName `
    --project $ProjectId --region $Region `
    --member "serviceAccount:$apiServiceAccount" --role roles/run.invoker

Step "Deploy Firebase-authenticated API"
$apiImage = "$Region-docker.pkg.dev/$ProjectId/servo/$ApiService`:cpu"
gcloud run deploy $ApiService `
    --project $ProjectId --region $Region --image $apiImage `
    --service-account $apiServiceAccount `
    --allow-unauthenticated `
    --min-instances 0 --max-instances 1 `
    --cpu 2 --memory 4Gi --concurrency 8 --timeout 3600 `
    --set-env-vars "SERVO_AUTH_MODE=firebase,SERVO_FIREBASE_PROJECT_ID=$firebaseProject,SERVO_FIREBASE_REQUIRE_VERIFIED_EMAIL=1,SERVO_GCP_REGION=$Region,SERVO_CAMPAIGN_JOB=$CampaignJobName,SERVO_GCS_BUCKET=$bucket,SERVO_GCS_PREFIX=$GcsPrefix,SERVO_FIRESTORE_DATABASE=(default),SERVO_FIRESTORE_COLLECTION=servo_campaigns,SERVO_CAMPAIGN_ROOT=/workspace/campaigns,SERVO_COMMIT_SHA=$commitSha,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region,GOOGLE_GENAI_USE_VERTEXAI=true"

$serviceUrl = (gcloud run services describe $ApiService --project $ProjectId `
    --region $Region --format "value(status.url)").Trim()

Step "Deployment boundary"
Write-Host "API URL:      $serviceUrl"
Write-Host "Campaign job: $CampaignJobName"
Write-Host "Artifacts:    gs://$bucket/$GcsPrefix"
Write-Host "Metadata:     Firestore (default)/servo_campaigns"
Write-Host "Commit:       $commitSha"
Write-Host ""
Write-Host "Firebase Authentication must be enabled for project '$firebaseProject'."
Write-Host "The Cloud Run service is public only at the platform ingress layer; every"
Write-Host "/v1 request is rejected unless the app verifies a Firebase ID token."
Write-Host "Record the service revision and one real job execution for submission proof."
