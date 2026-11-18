param([Parameter(Mandatory=$true)][string[]]$Files,[string]$Title='我的绘本',[ValidateSet('3-6','6-9')][string]$Age='3-6',[decimal]$CostLimit=0,[switch]$ApproveCloudAndCost,[switch]$AccountPermissionsConfirmed,[int]$Port=8765)
. (Join-Path $PSScriptRoot 'studio_common.ps1')
Set-StudioEnvironment
$cliArgs=@((Join-Path $PSScriptRoot 'studio_cli.py'),'--url',"http://127.0.0.1:$Port",'generate','--title',$Title,'--age',$Age,'--cost-limit',"$CostLimit")
if ($ApproveCloudAndCost) { $cliArgs+='--approve-cloud-and-cost' }
if ($AccountPermissionsConfirmed) { $cliArgs+='--account-permissions-confirmed' }
foreach ($file in $Files) { $cliArgs+=@('--file',(Resolve-Path -LiteralPath $file).Path) }
Invoke-CheckedPython $AppPython $cliArgs
