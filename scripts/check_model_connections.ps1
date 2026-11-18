param([int]$Port=8765)
. (Join-Path $PSScriptRoot 'studio_common.ps1')
Set-StudioEnvironment
Invoke-CheckedPython $AppPython @((Join-Path $PSScriptRoot 'studio_cli.py'),'--url',"http://127.0.0.1:$Port",'connections')
