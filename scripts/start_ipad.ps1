. (Join-Path $PSScriptRoot 'studio_common.ps1')
Set-StudioEnvironment
Push-Location $StudioRoot
try {
    if (Test-Path .runtime/ipad-network.json) {
        $existing=Get-Content .runtime/ipad-network.json -Raw | ConvertFrom-Json
        & $AppPython scripts/ipad_control.py check 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Backend already running: $($existing.url)"
            Write-Host 'If pairing code expired, generate a new one in Parent Center.'
            Start-Process (Join-Path $RuntimeDir 'IPAD_ACCESS.html')
            return
        }
    }
    & $AppPython scripts/ipad_network.py
    if ($LASTEXITCODE -ne 0) { throw 'LAN/TLS configuration failed.' }
    $network = Get-Content .runtime/ipad-network.json -Raw | ConvertFrom-Json
    # Wi-Fi may be classified Public. Do not change that classification: limit
    # this program's two ports to this exact private IP and LocalSubnet instead.
    foreach($port in @(8766,8767)) {
        $ruleName="Paperbook-iPad-$port"
        if (!(Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -LocalAddress $network.ip -RemoteAddress LocalSubnet -Profile Any -Program $AppPython | Out-Null
        } else {
            Set-NetFirewallRule -DisplayName $ruleName -Enabled True -LocalAddress $network.ip -RemoteAddress LocalSubnet -Program $AppPython -Profile Any | Out-Null
        }
    }
    Import-Certificate -FilePath $network.public_ca -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    $proc=Start-Process -FilePath $AppPython -WorkingDirectory $StudioRoot -WindowStyle Hidden -PassThru -ArgumentList @('scripts/ipad_server.py') -RedirectStandardOutput .runtime/ipad.out.log -RedirectStandardError .runtime/ipad.err.log
    @{pid=$proc.Id;executable=$AppPython;url=$network.url} | ConvertTo-Json | Set-Content .runtime/ipad-process.json -Encoding UTF8
    Start-Process (Join-Path $RuntimeDir 'IPAD_ACCESS.html')
    Write-Host "HTTPS backend starting: $($network.url)"
    Write-Host 'First iPad use requires installing and explicitly trusting the displayed household CA.'
} finally { Pop-Location }
