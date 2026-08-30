@echo off
setlocal
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
set DISTUTILS_USE_SDK=1
set MSSdk=1
set PATH=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\bin\Hostx64\x64;%PATH%
set INCLUDE=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\include;%INCLUDE%
set TORCH_CUDA_ARCH_LIST=8.9
if not exist "D:\Servo\runtime\climate\python" mkdir "D:\Servo\runtime\climate\python"
python -m pip install "%~dp0..\..\third_party\Climate_NeRF\models\csrc" --target "%~dp0..\..\runtime\climate\python" --no-build-isolation -v
exit /b %errorlevel%
