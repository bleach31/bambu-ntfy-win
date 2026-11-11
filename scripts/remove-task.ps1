$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName "BambuP1S-Ntfy" -Confirm:$false
Write-Host "BambuP1S-Ntfy task removed."
