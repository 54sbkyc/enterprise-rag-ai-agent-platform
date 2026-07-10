$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) {
    $VenvPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}

Write-Host "Project verification"
Write-Host "Project root: $Root"
Write-Host "Python: $Python"
Write-Host "No project files will be modified."
Write-Host ""

Push-Location $Backend
try {
    Write-Host "[1/4] python -m compileall"
    & $Python -m compileall -q app
    if ($LASTEXITCODE -ne 0) {
        throw "compileall failed with exit code $LASTEXITCODE"
    }

    Write-Host "[2/4] python -m pip check"
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "pip check failed with exit code $LASTEXITCODE"
    }

    Write-Host "[3/4] python -m pytest"
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "[4/4] GitHub release readiness"
& (Join-Path $PSScriptRoot "prepare_github_release.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "GitHub release readiness failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Project verification status: PASSED"
