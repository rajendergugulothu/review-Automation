param(
    [string]$BackendBase = "http://localhost:8000",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $PSScriptRoot "logs\reminder-job.log"
}

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Write-Host $line
    Add-Content -Path $LogPath -Value $line
}

try {
    $logDir = Split-Path -Path $LogPath -Parent
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    $uri = "$($BackendBase.TrimEnd('/'))/admin/process-reminders"
    Write-Log "Starting reminder job: POST $uri"

    $response = Invoke-RestMethod -Method POST -Uri $uri -TimeoutSec 60
    $summary = "attempted=$($response.attempted) sent=$($response.sent) failed=$($response.failed) skipped=$($response.skipped)"
    Write-Log "Reminder job completed: $summary"
}
catch {
    Write-Log "Reminder job failed: $($_.Exception.Message)"
    exit 1
}
