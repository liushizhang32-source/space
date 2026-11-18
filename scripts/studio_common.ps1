$ErrorActionPreference = 'Stop'
$StudioRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $StudioRoot '.runtime'
$AppPython = Join-Path $RuntimeDir 'app\Scripts\python.exe'
$OcrPython = Join-Path $RuntimeDir 'ocr\Scripts\python.exe'
$ToolsConfig = Join-Path $RuntimeDir 'tools.json'
function Set-StudioEnvironment {
    if (!(Test-Path -LiteralPath $AppPython) -or !(Test-Path -LiteralPath $ToolsConfig)) { throw 'Run scripts/install_all.ps1 first.' }
    $toolSettings = Get-Content -LiteralPath $ToolsConfig -Raw | ConvertFrom-Json
    $env:OCR_PYTHON = $toolSettings.ocr_python
    $env:FFMPEG_PATH = $toolSettings.ffmpeg
    $env:FFPROBE_PATH = $toolSettings.ffprobe
    $env:VIDEO_FONT = $toolSettings.font
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
}
function Invoke-CheckedPython {
    param([string]$Executable,[string[]]$PythonArgs)
    & $Executable @PythonArgs
    if ($LASTEXITCODE -ne 0) { throw "Python step failed (exit $LASTEXITCODE)." }
}
