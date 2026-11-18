param([int]$Port=8765,[switch]$NoBrowser)
. (Join-Path $PSScriptRoot 'studio_common.ps1')
Set-StudioEnvironment
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Port must be 1024..65535.' }
$pidFile = Join-Path $RuntimeDir 'studio-process.json'
$url = "http://127.0.0.1:$Port"
try { $health = Invoke-RestMethod "$url/health" -TimeoutSec 2 } catch { $health = $null }
if (!$health -or $health.service -ne 'paperbook-real-model-studio') {
    $process = Start-Process -FilePath $AppPython -WorkingDirectory $StudioRoot -WindowStyle Hidden -PassThru -ArgumentList @('scripts/studio_server.py','--port',"$Port") -RedirectStandardOutput (Join-Path $RuntimeDir 'server.out.log') -RedirectStandardError (Join-Path $RuntimeDir 'server.err.log')
    @{pid=$process.Id;port=$Port;started=$process.StartTime.ToUniversalTime().ToString('o');executable=$AppPython} | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) { throw 'Studio failed to start; see .runtime/server.err.log.' }
        try { $health = Invoke-RestMethod "$url/health" -TimeoutSec 1; if ($health.service -eq 'paperbook-real-model-studio') { break } } catch {}
    }
    if (!$health -or $health.service -ne 'paperbook-real-model-studio') { throw 'Studio startup timeout.' }
}
Write-Host "Studio: $url"
if (!$NoBrowser) { Start-Process $url }
