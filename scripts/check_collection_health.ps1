$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

Set-Location -LiteralPath $projectRoot
& $python -m backend.collection_health --days 7 --fail-on-unhealthy
exit $LASTEXITCODE
