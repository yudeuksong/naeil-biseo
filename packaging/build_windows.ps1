# Build NaeilBiseo.exe on Windows with PyInstaller.
# Usage (PowerShell, from the project root):
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Output: dist\NaeilBiseo\NaeilBiseo.exe
# This file is ASCII-only on purpose (Windows PowerShell 5.1 misreads UTF-8 without BOM).
param(
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = "python"
if (Get-Command py -ErrorAction SilentlyContinue) { $python = "py" }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[1/5] Creating virtual environment"
    if ($python -eq "py") { & py -3 -m venv .venv } else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "Could not create a virtual environment. Install Python 3.10+ first." }
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "[2/5] Installing dependencies"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipTests) {
    Write-Host "[3/5] Running tests"
    $env:QT_QPA_PLATFORM = "offscreen"
    & $venvPy -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed. Fix them or rerun with -SkipTests." }
    Remove-Item Env:\QT_QPA_PLATFORM
} else {
    Write-Host "[3/5] Tests skipped"
}

Write-Host "[4/5] Building with PyInstaller"
& $venvPy -m PyInstaller --noconfirm --clean packaging\naeilbiseo.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "[5/5] Self-test of the built exe (mock mode, nothing is sent anywhere)"
$exe = Join-Path $root "dist\NaeilBiseo\NaeilBiseo.exe"
if (-not (Test-Path $exe)) { throw "Build output not found: $exe" }
$testData = Join-Path $env:TEMP ("naeilbiseo-selftest-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testData | Out-Null
$env:NAEILBISEO_DATA_DIR = $testData
$proc = Start-Process -FilePath $exe -ArgumentList "--self-test" -Wait -PassThru
Remove-Item Env:\NAEILBISEO_DATA_DIR
$report = Join-Path $testData "selftest_result.txt"
if (Test-Path $report) { Get-Content $report -Encoding UTF8 }
if ($proc.ExitCode -ne 0) { throw "Self-test failed with exit code $($proc.ExitCode)" }

Write-Host ""
Write-Host "Done: $exe"
Write-Host "Copy the whole dist\NaeilBiseo folder to the target PC. The exe is not code-signed,"
Write-Host "so Windows SmartScreen may show a warning the first time it runs."
