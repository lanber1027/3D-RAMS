param(
    [string]$Profile = "3d-rams-dev",
    [string]$Region = "eu-west-2",
    [string]$AppName = "3d-rams-mvp",
    [string]$BranchName = "main",
    [string]$AwsExe = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$distPath = Join-Path $repoRoot "frontend\dist"
$zipPath = Join-Path $repoRoot ".deploy-build\3d-rams-frontend.zip"
$summaryFile = Join-Path $PSScriptRoot "amplify-summary.json"
$hostedSummaryFile = Join-Path $PSScriptRoot "hosted-mvp-summary.json"

if (-not (Test-Path (Join-Path $distPath "index.html"))) {
    throw "Frontend dist is missing. Run the frontend build before deploying Amplify."
}
if (Test-Path $hostedSummaryFile) {
    $apiEndpoint = ((Get-Content $hostedSummaryFile -Raw | ConvertFrom-Json).apiEndpoint).TrimEnd("/")
    $assetMatches = Get-ChildItem -LiteralPath (Join-Path $distPath "assets") -Filter "*.js" -File -ErrorAction SilentlyContinue |
        Select-String -SimpleMatch $apiEndpoint -List
    if (-not $assetMatches) {
        throw "Frontend dist does not contain API endpoint $apiEndpoint. Rebuild with `$env:VITE_API_BASE_URL=`"$apiEndpoint`" before deploying Amplify."
    }
}

function Invoke-AwsJson {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if ($Args.Count -eq 1 -and $Args[0] -match "\s") {
        $Args = $Args[0] -split "\s+"
    }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $AwsExe @Args 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    if ($exitCode -ne 0) {
        throw "AWS CLI failed: aws $($Args -join ' ')`n$output"
    }
    if ([string]::IsNullOrWhiteSpace($output)) { return $null }
    return $output | ConvertFrom-Json
}

function Invoke-AwsText {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if ($Args.Count -eq 1 -and $Args[0] -match "\s") {
        $Args = $Args[0] -split "\s+"
    }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $AwsExe @Args 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    if ($exitCode -ne 0) {
        throw "AWS CLI failed: aws $($Args -join ' ')`n$output"
    }
    return $output
}

if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $distRoot = (Resolve-Path $distPath).Path.TrimEnd("\") + "\"
    Get-ChildItem -LiteralPath $distPath -Recurse -File | ForEach-Object {
        $relativePath = $_.FullName.Substring($distRoot.Length).Replace("\", "/")
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $relativePath) | Out-Null
    }
} finally {
    $zip.Dispose()
}

$apps = Invoke-AwsJson @("amplify", "list-apps", "--region", $Region, "--profile", $Profile, "--output", "json")
$app = $apps.apps | Where-Object { $_.name -eq $AppName } | Select-Object -First 1
if (-not $app) {
    $app = Invoke-AwsJson @("amplify", "create-app", "--name", $AppName, "--platform", "WEB", "--region", $Region, "--profile", $Profile, "--output", "json")
    $app = $app.app
}
$appId = $app.appId

$branches = Invoke-AwsJson @("amplify", "list-branches", "--app-id", $appId, "--region", $Region, "--profile", $Profile, "--output", "json")
$branch = $branches.branches | Where-Object { $_.branchName -eq $BranchName } | Select-Object -First 1
if (-not $branch) {
    Invoke-AwsJson @("amplify", "create-branch", "--app-id", $appId, "--branch-name", $BranchName, "--stage", "DEVELOPMENT", "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
}

$deployment = Invoke-AwsJson @("amplify", "create-deployment", "--app-id", $appId, "--branch-name", $BranchName, "--region", $Region, "--profile", $Profile, "--output", "json")
Invoke-RestMethod -Method Put -Uri $deployment.zipUploadUrl -InFile $zipPath -ContentType "application/zip" | Out-Null
Invoke-AwsJson @("amplify", "start-deployment", "--app-id", $appId, "--branch-name", $BranchName, "--job-id", $deployment.jobId, "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null

$status = "PENDING"
$job = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    $jobResult = Invoke-AwsJson @("amplify", "get-job", "--app-id", $appId, "--branch-name", $BranchName, "--job-id", $deployment.jobId, "--region", $Region, "--profile", $Profile, "--output", "json")
    $job = $jobResult.job
    $status = $job.summary.status
    if ($status -in @("SUCCEED", "FAILED", "CANCELLED")) { break }
}
if ($status -ne "SUCCEED") {
    throw "Amplify deployment did not succeed. Final status: $status"
}

$app = (Invoke-AwsJson @("amplify", "get-app", "--app-id", $appId, "--region", $Region, "--profile", $Profile, "--output", "json")).app
$url = "https://$BranchName.$($app.defaultDomain)"
$summary = [pscustomobject]@{
    appId = $appId
    appName = $AppName
    branchName = $BranchName
    url = $url
    jobId = $deployment.jobId
    status = $status
    createdAt = (Get-Date).ToUniversalTime().ToString("o")
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryFile -Encoding utf8
$summary | ConvertTo-Json -Depth 8
