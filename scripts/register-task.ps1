$ErrorActionPreference = "Stop"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$admin = [System.Security.Principal.WindowsPrincipal]::new($identity)
if (-not $admin.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script in PowerShell as Administrator. The startup task runs as SYSTEM."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "bambu_ntfy.py"
$config = Join-Path $root "config.json"
$taskName = "BambuP1S-Ntfy"
if (-not (Test-Path $pythonw -PathType Leaf)) { throw "Run .\scripts\install.ps1 first" }
if (-not (Test-Path $script -PathType Leaf)) { throw "Monitor script not found" }
if (-not (Test-Path $config -PathType Leaf)) { throw "Edit config.json first" }

# SYSTEM is privileged. Keep this checkout and Python installation writable
# only by trusted administrators and SYSTEM; do not use a shared writable folder.
# pythonw hides the console; errors go to .runtime\bambu-ntfy.log.
$arguments = ('"{0}" --config "{1}"' -f $script, $config)
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# Stop the old login-triggered instance before replacing it.
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath "\" -ErrorAction SilentlyContinue
if ($existing -and $existing.State -in @("Running", "Queued")) {
    Stop-ScheduledTask -TaskName $taskName -TaskPath "\"
}
Register-ScheduledTask -TaskName $taskName -TaskPath "\" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Registered task $taskName (runs as SYSTEM at PC startup, no user login needed)."
Write-Host "Start it now with: Start-ScheduledTask -TaskName $taskName"
