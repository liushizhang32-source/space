param([string]$PythonPath = '')
. (Join-Path $PSScriptRoot 'studio_common.ps1')
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
if (!$PythonPath) {
    $candidates = @((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { $candidates += $pythonCmd.Source }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $version = & $candidate -c 'import sys;print(".".join(map(str,sys.version_info[:2])))'
            if ($LASTEXITCODE -eq 0 -and $version -eq '3.12') { $PythonPath = $candidate; break }
        }
    }
}
if (!$PythonPath) {
    $installer = Join-Path $RuntimeDir 'python-3.12.10-amd64.exe'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'Python installer signature invalid.' }
    $pythonDir = Join-Path $RuntimeDir 'python312'
    $process = Start-Process -FilePath $installer -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/quiet','InstallAllUsers=0','Include_test=0','PrependPath=0',('TargetDir="'+$pythonDir+'"'))
    if ($process.ExitCode -ne 0) { throw 'Python installation failed.' }
    $PythonPath = Join-Path $pythonDir 'python.exe'
}
Push-Location $StudioRoot
try {
    if (!(Test-Path -LiteralPath $AppPython)) { Invoke-CheckedPython $PythonPath @('-m','venv',(Join-Path $RuntimeDir 'app')) }
    if (!(Test-Path -LiteralPath $OcrPython)) { Invoke-CheckedPython $PythonPath @('-m','venv',(Join-Path $RuntimeDir 'ocr')) }
    Invoke-CheckedPython $AppPython @('-m','pip','install','-r','requirements-real-model.txt')
    Invoke-CheckedPython $OcrPython @('-m','pip','install','-r','requirements-ocr.txt')
    Invoke-CheckedPython $AppPython @('-m','pip','check')
    Invoke-CheckedPython $OcrPython @('-m','pip','check')
    Invoke-CheckedPython $AppPython @('scripts/prepare_studio_tools.py','--runtime',$RuntimeDir,'--ocr-python',$OcrPython)
    Set-StudioEnvironment
    Invoke-CheckedPython $AppPython @('scripts/check_studio.py','--warm-ocr','--output',(Join-Path $RuntimeDir ('install-check-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.json')))
    $installedBrowser = @('C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','C:\Program Files\Google\Chrome\Application\chrome.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($installedBrowser) { Write-Host "Browser available: $installedBrowser" }
    else { Invoke-CheckedPython $AppPython @('-m','playwright','install','chromium') }
    Write-Host 'Installed. Run scripts/start_system.ps1. No cloud inference has been submitted.'
} finally { Pop-Location }
