$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$config = Join-Path $root "config.json"
if (-not (Test-Path $python)) { throw "Run .\scripts\install.ps1 first" }
if (-not (Test-Path $config)) { throw "Edit config.json first" }
& $python (Join-Path $root "bambu_ntfy.py") --config $config @args
exit $LASTEXITCODE
