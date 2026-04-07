param(
    [string]$TaskName = "UrbanReviewReminderJob"
)

$ErrorActionPreference = "Stop"

$proc = Start-Process -FilePath "schtasks.exe" -ArgumentList @("/Delete", "/TN", $TaskName, "/F") -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -eq 0) {
    Write-Host "Task '$TaskName' removed."
}
else {
    Write-Host "Task '$TaskName' not found or could not be removed."
}
