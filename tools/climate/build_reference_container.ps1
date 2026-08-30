param(
    [string]$ClimateSource = "$PSScriptRoot\..\..\third_party\Climate_NeRF",
    [string]$Image = "servo-climatenerf:official-2023-cu113"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $ClimateSource -PathType Container)) {
    throw "ClimateNeRF source not found: $ClimateSource"
}
docker build --progress=plain --tag $Image --file "$PSScriptRoot\Dockerfile.climatenerf" $ClimateSource
if ($LASTEXITCODE -ne 0) {
    throw "ClimateNeRF container build failed with exit code $LASTEXITCODE"
}
docker run --rm --gpus all $Image -c "import torch,tinycudann,vren,torch_scatter; print({'cuda':torch.cuda.is_available(),'gpu':torch.cuda.get_device_name(0),'torch':torch.__version__})"
if ($LASTEXITCODE -ne 0) {
    throw "ClimateNeRF container qualification failed with exit code $LASTEXITCODE"
}
