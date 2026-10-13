param([int]$Width=1280,[int]$Height=720,[int]$Fps=15)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$Python=Join-Path $PSScriptRoot '.venv-usb/Scripts/python.exe'
if (-not (Test-Path $Python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3 with the py.exe launcher first.' }
    & py -3 -m venv .venv-usb
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3 with the py launcher first.' }
    & $Python -m pip install -r requirements-windows-usb.txt
    if ($LASTEXITCODE -ne 0) { throw 'USB bridge dependency installation failed.' }
}
& $Python scripts/windows_usb_bridge.py --width $Width --height $Height --fps $Fps
if ($LASTEXITCODE -ne 0) { throw 'USB bridge failed.' }
