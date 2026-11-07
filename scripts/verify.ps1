# 成员 3 代码包一键验证（Windows / PowerShell）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
#       $env:PYTHON = "C:\Python312\python.exe"  可指定解释器

$ErrorActionPreference = "Stop"
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Write-Host "== 0/4 解释器 ==" -ForegroundColor Cyan
& $python --version

Write-Host "== 1/4 依赖 ==" -ForegroundColor Cyan
& $python -c "import pydantic, fastapi, uvicorn, PIL; print('deps ok')"

Write-Host "== 2/4 测试 ==" -ForegroundColor Cyan
& $python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== 3/4 安装示例页 ==" -ForegroundColor Cyan
if (-not $env:DATA_DIR) { $env:DATA_DIR = "_verify_data" }
& $python examples\install_example.py

Write-Host "== 4/4 跑全链路 ==" -ForegroundColor Cyan
& $python -m agents.generation run --page-id book01_p03 --age-level 3-6
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "产物目录：$env:DATA_DIR" -ForegroundColor Green
Get-ChildItem "$env:DATA_DIR\json", "$env:DATA_DIR\videos", "$env:DATA_DIR\audios" -ErrorAction SilentlyContinue |
    Select-Object FullName, Length
