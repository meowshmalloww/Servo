param(
    [string]$Image = "servo-climatenerf:official-2023-cu113-semantic"
)

$ErrorActionPreference = "Stop"
docker build --progress=plain --tag $Image `
  --file "$PSScriptRoot\Dockerfile.climatenerf-semantic" $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    throw "ClimateNeRF semantic container build failed with exit code $LASTEXITCODE"
}
docker run --rm --gpus all $Image -c "import torch,tinycudann,vren,torch_scatter,mmcv,mmseg; print({'cuda':torch.cuda.is_available(),'gpu':torch.cuda.get_device_name(0),'torch':torch.__version__,'mmcv':mmcv.__version__,'mmseg':mmseg.__version__})"
if ($LASTEXITCODE -ne 0) {
    throw "ClimateNeRF semantic container qualification failed with exit code $LASTEXITCODE"
}
