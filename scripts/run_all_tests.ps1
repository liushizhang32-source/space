param([string]$Output='')
. (Join-Path $PSScriptRoot 'studio_common.ps1')
Set-StudioEnvironment
if (!$Output) { $Output=Join-Path (Split-Path $StudioRoot -Parent) ('reports\REAL-MODEL-FINAL-INTEGRATION-001\run-'+(Get-Date -Format 'yyyyMMdd-HHmmss')) }
New-Item -ItemType Directory -Force -Path $Output | Out-Null
Push-Location $StudioRoot
try {
    Invoke-CheckedPython $AppPython @('scripts/run_real_model_acceptance.py','--output',$Output)
    Invoke-CheckedPython $AppPython @('scripts/run_full_offline_acceptance.py','--phase','full','--output',(Join-Path $Output 'legacy-full'))
} finally { Pop-Location }
