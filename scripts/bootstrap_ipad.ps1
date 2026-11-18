$ErrorActionPreference='Stop'
$packageRoot=Split-Path -Parent $PSScriptRoot
try {
    & (Join-Path $PSScriptRoot 'start_ipad.ps1')
} catch {
    $runtime=Join-Path $packageRoot '.runtime'
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $log=Join-Path $runtime 'startup-error.log'
    # Errors only: never transcript the initial parent PIN or environment keys.
    @((Get-Date).ToString('o'),$_.Exception.Message,$_.ScriptStackTrace) | Set-Content -LiteralPath $log -Encoding UTF8
    Write-Host "Startup failed. Error details saved to: $log" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
