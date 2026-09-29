# Build the standalone DayOS.exe with PyInstaller.
# Keeps every cache and temporary file on the project drive (inside the project).
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# Output: dist\DayOS.exe  (single windowed executable; Python not required to run it)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$env:PYINSTALLER_CONFIG_DIR = Join-Path $root ".cache\pyinstaller"
$env:TEMP = Join-Path $root ".cache\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:PYINSTALLER_CONFIG_DIR, $env:TEMP | Out-Null

$python = Join-Path $root ".venv\Scripts\python.exe"
& $python (Join-Path $root "tools\make_art.py") | Out-Null
& $python (Join-Path $root "tools\make_icon.py")

# Remove the old one-folder output if present so dist\ only holds the release EXE.
$oldFolder = Join-Path $root "dist\DayOS"
if (Test-Path $oldFolder) { Remove-Item -Recurse -Force $oldFolder }

Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean `
        --workpath (Join-Path $root "build") `
        --distpath (Join-Path $root "dist") `
        (Join-Path $root "dayos.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
$exe = Join-Path $root "dist\DayOS.exe"
Write-Host ("Built: {0} ({1:N1} MB)" -f $exe, ((Get-Item $exe).Length / 1MB))
