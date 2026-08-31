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

function Ensure-ServiceAccount([string]$name, [string]$displayName) {
    gcloud iam service-accounts describe "$name@$ProjectId.iam.gserviceaccount.com" `
        --project $ProjectId *> $null
    if ($LASTEXITCODE -ne 0) {
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
    run.googleapis.com `
    secretmanager.googleapis.com `
    storage.googleapis.com

Step "Dedicated service identities"
Ensure-ServiceAccount $apiServiceAccountName "Servo RealityCI API"
Ensure-ServiceAccount $jobServiceAccountName "Servo RealityCI campaign job"

Step "Artifact Registry"
gcloud artifacts repositories describe servo --location $Region --project $ProjectId *> $null
if ($LASTEXITCODE -ne 0) {
    gcloud artifacts repositories create servo --repository-format docker `
        --location $Region --project $ProjectId
}

Step "Versioned campaign artifact bucket"
gcloud storage buckets describe "gs://$bucket" --project $ProjectId *> $null
if ($LASTEXITCODE -ne 0) {
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
gcloud run jobs describe $CampaignJobName --region $Region --project $ProjectId *> $null
$jobAction = if ($LASTEXITCODE -eq 0) { "update" } else { "create" }
gcloud run jobs $jobAction $CampaignJobName `
    --project $ProjectId --region $Region --image $jobImage `
    --service-account $jobServiceAccount `
    --cpu 2 --memory 4Gi --task-timeout 3600s --max-retries 1 `
    --set-env-vars "SERVO_GCS_BUCKET=$bucket,SERVO_GCS_PREFIX=$GcsPrefix,SERVO_COMMIT_SHA=$commitSha,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region,GOOGLE_GENAI_USE_VERTEXAI=true"

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
    --set-env-vars "SERVO_AUTH_MODE=firebase,SERVO_FIREBASE_PROJECT_ID=$firebaseProject,SERVO_FIREBASE_REQUIRE_VERIFIED_EMAIL=1,SERVO_GCP_REGION=$Region,SERVO_CAMPAIGN_JOB=$CampaignJobName,SERVO_GCS_BUCKET=$bucket,SERVO_GCS_PREFIX=$GcsPrefix,SERVO_CAMPAIGN_ROOT=/workspace/campaigns,SERVO_COMMIT_SHA=$commitSha,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region,GOOGLE_GENAI_USE_VERTEXAI=true"

$serviceUrl = (gcloud run services describe $ApiService --project $ProjectId `
    --region $Region --format "value(status.url)").Trim()

Step "Deployment boundary"
Write-Host "API URL:      $serviceUrl"
Write-Host "Campaign job: $CampaignJobName"
Write-Host "Artifacts:    gs://$bucket/$GcsPrefix"
Write-Host "Commit:       $commitSha"
Write-Host ""
Write-Host "Firebase Authentication must be enabled for project '$firebaseProject'."
Write-Host "The Cloud Run service is public only at the platform ingress layer; every"
Write-Host "/v1 request is rejected unless the app verifies a Firebase ID token."
Write-Host "Record the service revision and one real job execution for submission proof."
