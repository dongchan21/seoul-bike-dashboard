param(
    [string]$TaskName = 'SeoulBikeInventoryCollector'
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'run_collector.ps1'
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Collector runner was not found: $runner"
}

$quotedRunner = '"' + $runner + '"'
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File $quotedRunner"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Collect Seoul Bike inventory every five minutes while the user is logged on.' `
    -Force | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "It will start at the next logon. Start it now with:"
Write-Host "Start-ScheduledTask -TaskName '$TaskName'"
