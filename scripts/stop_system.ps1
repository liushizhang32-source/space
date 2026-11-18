. (Join-Path $PSScriptRoot 'studio_common.ps1')
$pidFile = Join-Path $RuntimeDir 'studio-process.json'
if (!(Test-Path -LiteralPath $pidFile)) { Write-Host 'No tracked studio process.'; exit 0 }
$saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.pid)"
if (!$process) { Write-Host 'Studio already stopped.'; exit 0 }
if ($process.ExecutablePath -ne $saved.executable -or $process.CommandLine -notmatch 'scripts/studio_server\.py') { throw 'PID ownership mismatch; refused to stop another process.' }
# Graceful shutdown route is local-owner/CSRF protected and waits for workers.
& $AppPython (Join-Path $PSScriptRoot 'studio_cli.py') --url "http://127.0.0.1:$($saved.port)" shutdown
if ($LASTEXITCODE -ne 0) { throw 'Graceful shutdown failed; process was not force killed.' }
Write-Host 'Shutdown requested; waits for current native/network operation to finish.'
