$ErrorActionPreference = "Stop"
$sourceDir = (Resolve-Path $PSScriptRoot).Path
$env:PYTHONPATH = $sourceDir
Set-Location -LiteralPath $sourceDir
python -m api_server
