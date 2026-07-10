$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Creating virtual environment..."
    python -m venv $Venv
}

Write-Host "Installing backend dependencies..."
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Backend "requirements.txt")

$Port = 8000
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    $Port = 8001
}

$LanIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.PrefixOrigin -ne "WellKnown"
    } |
    Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host "Starting Enterprise RAG QA Platform..."
Write-Host "Open on this computer: http://127.0.0.1:$Port"
if ($LanIp) {
    Write-Host "Open on phone in the same Wi-Fi/LAN: http://$LanIp`:$Port"
}
Set-Location $Backend
& $Python -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
