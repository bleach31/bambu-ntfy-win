$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating local Python virtual environment..."
    py -3 -m venv .venv
}
$python = Join-Path $root ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
if (-not (Test-Path "config.json")) {
    Copy-Item "config.example.json" "config.json"
    Write-Host "Created config.json. Fill in local printer and ntfy values."
} else {
    Write-Host "Existing config.json kept unchanged."
}
Write-Host "Installed. Edit config.json, then run: .\scripts\start.ps1"
