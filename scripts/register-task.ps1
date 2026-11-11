$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "bambu_ntfy.py"
$config = Join-Path $root "config.json"
$taskName = "BambuP1S-Ntfy"
if (-not (Test-Path $pythonw)) { throw "Run .\scripts\install.ps1 first" }
if (-not (Test-Path $config)) { throw "Edit config.json first" }
# pythonw hides the console; errors go to .runtime\bambu-ntfy.log.
$arguments = ('"{0}" --config "{1}"' -f $script, $config)
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Registered task $taskName (runs at your Windows logon)."
Write-Host "Start it now with: Start-ScheduledTask -TaskName $taskName"
