param(
    [string]$TaskName = "UrbanReviewReminderJob",
    [string]$BackendBase = "http://localhost:8000",
    [int]$EveryHours = 1
)

$ErrorActionPreference = "Stop"

if ($EveryHours -lt 1) {
    throw "EveryHours must be >= 1"
}

$scriptPath = Join-Path $PSScriptRoot "process-reminders.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Missing script: $scriptPath"
}

$startAt = (Get-Date).AddMinutes(1)
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -BackendBase `"$BackendBase`""
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $startAt `
    -RepetitionInterval (New-TimeSpan -Hours $EveryHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs Urban Review reminder processor on schedule." `
    -Force | Out-Null

Write-Host "Task '$TaskName' created/updated."
Write-Host "Starts at $($startAt.ToString('yyyy-MM-dd HH:mm:ss')) and repeats every $EveryHours hour(s)."
Write-Host "Run now with:"
Write-Host "Start-ScheduledTask -TaskName `"$TaskName`""
