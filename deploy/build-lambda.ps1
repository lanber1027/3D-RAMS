param(
    [string]$OutputZip = ".deploy-build\3d-rams-lambda.zip"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$buildRoot = Join-Path $repoRoot ".deploy-build"
$packageRoot = Join-Path $buildRoot "lambda-package"
$requirements = Join-Path $PSScriptRoot "lambda-requirements.txt"
$zipPath = Join-Path $repoRoot $OutputZip

if (Test-Path $packageRoot) { Remove-Item -LiteralPath $packageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $packageRoot | Out-Null

python -m pip install `
    --only-binary=:all: `
    --platform manylinux2014_x86_64 `
    --python-version 311 `
    --implementation cp `
    --abi cp311 `
    --requirement $requirements `
    --target $packageRoot `
    --upgrade `
    --progress-bar off `
    --disable-pip-version-check `
    --no-cache-dir
if ($LASTEXITCODE -ne 0) { throw "pip install failed; Lambda package was not built." }

Copy-Item -Path (Join-Path $repoRoot "backend") -Destination (Join-Path $packageRoot "backend") -Recurse
Copy-Item -Path (Join-Path $repoRoot "fixtures") -Destination (Join-Path $packageRoot "fixtures") -Recurse

if (-not (Test-Path (Join-Path $packageRoot "mangum"))) {
    throw "Lambda package dependency check failed: mangum is missing."
}

if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $zipPath -Force

$zipItem = Get-Item $zipPath
[pscustomobject]@{
    zipPath = $zipItem.FullName
    sizeBytes = $zipItem.Length
    sizeMB = [math]::Round($zipItem.Length / 1MB, 2)
} | ConvertTo-Json
