$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python was not found: $python"
}

Set-Location -LiteralPath $projectRoot
& $python -m backend.collect
exit $LASTEXITCODE
