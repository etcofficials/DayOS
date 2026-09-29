# Build the one-folder DayOS release with PyInstaller.
# Keeps every cache and temporary file on G: (inside the project).
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# Output: G:\DayOS\dist\DayOS\DayOS.exe

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$env:PYINSTALLER_CONFIG_DIR = Join-Path $root ".cache\pyinstaller"
$env:TEMP = Join-Path $root ".cache\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:PYINSTALLER_CONFIG_DIR, $env:TEMP | Out-Null

$python = Join-Path $root ".venv\Scripts\python.exe"
& $python (Join-Path $root "tools\make_icon.py")
& $python -m PyInstaller --noconfirm --clean `
    --workpath (Join-Path $root "build") `
    --distpath (Join-Path $root "dist") `
    (Join-Path $root "dayos.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Write-Host "Built: $(Join-Path $root 'dist\DayOS\DayOS.exe')"
