$ErrorActionPreference = "Stop"
$sourceDir = (Resolve-Path $PSScriptRoot).Path
$env:PYTHONPATH = $sourceDir
if ([string]::IsNullOrWhiteSpace($env:AIOPS_CELERY_BROKER)) {
    $env:AIOPS_CELERY_BROKER = "redis://localhost:6379/0"
}

Set-Location -LiteralPath $sourceDir
celery -A "celery_app:celery_app" worker --pool=solo --concurrency=1 --loglevel=INFO
