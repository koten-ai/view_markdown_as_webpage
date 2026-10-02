$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$Venv = Join-Path $Root "packaging\.venv"
$match = Select-String -Path (Join-Path $Root "serve.py") -Pattern 'VERSION = "([^"]+)"'
if (-not $match) { throw "VERSION not found in serve.py" }
$Version = $match.Matches[0].Groups[1].Value
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    & $Py -m venv $Venv
}
& "$Venv\Scripts\python.exe" -m pip install -U pip
& "$Venv\Scripts\python.exe" -m pip install -r packaging\requirements.txt
& "$Venv\Scripts\python.exe" packaging\make_icons.py
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean packaging\markdown-viewer.spec
$Built = Join-Path $Root "dist\Markdown Viewer.exe"
if (-not (Test-Path $Built)) {
    throw "PyInstaller did not write $Built"
}
$Out = Join-Path $Root "dist\Markdown-Viewer-$Version-windows-x64.exe"
Copy-Item $Built $Out -Force
Write-Host "exe  $Out"
