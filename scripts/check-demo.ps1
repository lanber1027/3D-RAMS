param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RootDir

if ($Install) {
    Write-Host "Installing backend dependencies"
    python -m pip install --disable-pip-version-check -r backend/requirements.txt

    Write-Host "Installing frontend dependencies"
    Push-Location frontend
    try {
        if (Test-Path package-lock.json) {
            npm.cmd ci
        }
        else {
            npm.cmd install
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Compiling backend, tests, and scripts"
python -m compileall backend/app backend/tests scripts

Write-Host "Running backend unit and API contract tests"
python -m unittest discover -s backend/tests -q

Write-Host "Running deterministic no-AWS demo evaluation"
$previousEnableBedrock = [Environment]::GetEnvironmentVariable("ENABLE_BEDROCK", "Process")
[Environment]::SetEnvironmentVariable("ENABLE_BEDROCK", "false", "Process")
try {
    python scripts/evaluate-demo.py
}
finally {
    [Environment]::SetEnvironmentVariable("ENABLE_BEDROCK", $previousEnableBedrock, "Process")
}

Write-Host "Building frontend"
if (-not (Test-Path frontend/node_modules)) {
    throw "frontend/node_modules is missing. Run: powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1 -Install"
}

Push-Location frontend
try {
    npm.cmd run build
}
finally {
    Pop-Location
}

Write-Host "Running backend/frontend HTTP runtime smoke test"
python scripts/smoke-runtime.py

Write-Host "3D-RAMS local verification passed."
