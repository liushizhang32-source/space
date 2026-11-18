. (Join-Path $PSScriptRoot 'studio_common.ps1')
Set-StudioEnvironment
Push-Location $StudioRoot
try { Invoke-CheckedPython $AppPython @('scripts/check_studio.py','--warm-ocr','--output',(Join-Path $RuntimeDir ('environment-check-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.json'))) } finally { Pop-Location }
