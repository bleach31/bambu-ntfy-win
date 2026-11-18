$ErrorActionPreference = "Stop"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$admin = [System.Security.Principal.WindowsPrincipal]::new($identity)
if (-not $admin.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script in PowerShell as Administrator."
}
$taskName = "BambuP1S-Ntfy"
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath "\" -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.State -in @("Running", "Queued")) {
        Stop-ScheduledTask -TaskName $taskName -TaskPath "\"
    }
    Unregister-ScheduledTask -TaskName $taskName -TaskPath "\" -Confirm:$false
    Write-Host "$taskName task removed."
} else {
    Write-Host "$taskName task was not registered."
}
