# Scripts

## Reminder Automation

### 1) Run reminder job once
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\process-reminders.ps1
```

### 2) Install hourly scheduled task
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-reminder-task.ps1
```

Optional custom interval:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-reminder-task.ps1 -EveryHours 2
```

### 3) Remove scheduled task
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove-reminder-task.ps1
```

### Logs
Reminder job logs are written to:
`.\scripts\logs\reminder-job.log`
