$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Sanal ortam oluşturuluyor..."
    python -m venv ".venv" --system-site-packages
    & $venvPython -m pip install -r requirements.txt
}

& $venvPython (Join-Path $PSScriptRoot "launch.py")
