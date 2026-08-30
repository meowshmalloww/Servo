# ClimateNeRF isolated Windows-host setup

Build the locked Linux/CUDA image through Docker Desktop, then qualify it on the Windows-hosted NVIDIA GPU:

```powershell
pwsh -File D:\Servo\tools\climate\build_reference_container.ps1
python -m tools.climate.reference_backend qualify --output D:\Servo\simulations\runtime\t5\evidence\climate\container-qualification.json
```

Exit code 0 proves only that the exact image exposes CUDA and imports `tinycudann`, `vren`, and `torch_scatter`. It does not prove scene quality.

Qualified image identity: `sha256:cf9bb69574cf9ec47e6006c922f99a831dac886122b0ee1636f7b6f391881764`. Runtime: PyTorch 1.11.0+cu113 on an RTX 4080 Laptop GPU. A real T5 one-step model run and checkpoint reload passed, followed by 47 held-out smog renders. The result failed quality at PSNR 13.75 dB and SSIM 0.281 and must remain disabled in Servo.

Do not install the original pinned environment globally. The Docker path is the supported reference backend. Native Windows build experiments are not a qualified runtime.

MTMT shadow, mmseg semantics, stylization, panoramas, flood and snow remain fail-closed until their source/checkpoint licenses, hashes and scene prerequisites pass audit. ClimateNeRF does not implement rain.
