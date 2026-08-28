$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $projectRoot

Write-Host "运行自动化测试..."
python -m unittest discover -s 06_Tests -v

Write-Host "运行 Python 编译检查..."
python -m compileall -q 02_Source 06_Tests

Write-Host "运行 Git 差异检查..."
git diff --check

Write-Host "验证完成。"
