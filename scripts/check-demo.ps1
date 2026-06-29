param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RootDir

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

if ($Install) {
    Write-Host "Installing backend dependencies"
    Invoke-Checked { python -m pip install --disable-pip-version-check -r backend/requirements.txt } "Backend dependency install"

    Write-Host "Installing frontend dependencies"
    Push-Location frontend
    try {
        if (Test-Path package-lock.json) {
            Invoke-Checked { npm.cmd ci } "Frontend npm ci"
        }
        else {
            Invoke-Checked { npm.cmd install } "Frontend npm install"
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Compiling backend, tests, and scripts"
Invoke-Checked { python -m compileall backend/app backend/tests scripts } "Compileall"

Write-Host "Running backend unit and API contract tests"
Invoke-Checked { python -m unittest discover -s backend/tests -q } "Backend unit/API tests"

Write-Host "Running deterministic no-AWS demo evaluation"
$previousEnableBedrock = [Environment]::GetEnvironmentVariable("ENABLE_BEDROCK", "Process")
[Environment]::SetEnvironmentVariable("ENABLE_BEDROCK", "false", "Process")
try {
    Invoke-Checked { python scripts/evaluate-demo.py } "Deterministic no-AWS demo evaluation"
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
    Invoke-Checked { npm.cmd run build } "Frontend build"
}
finally {
    Pop-Location
}

Write-Host "Running backend/frontend HTTP runtime smoke test"
Invoke-Checked { python scripts/smoke-runtime.py } "Runtime smoke test"

Write-Host "3D-RAMS local verification passed."
