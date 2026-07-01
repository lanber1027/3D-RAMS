param(
    [string]$Profile = "3d-rams-dev",
    [string]$Region = "eu-west-2",
    [string]$Prefix = "3d-rams-mvp",
    [string]$LambdaZip = ".deploy-build\3d-rams-lambda.zip",
    [string]$AmplifyOrigin = "",
    [string]$AwsExe = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$zipPath = Resolve-Path (Join-Path $repoRoot $LambdaZip)
$buildConfigDir = Join-Path $repoRoot ".deploy-build\aws-config"
$privateFile = Join-Path $PSScriptRoot "hosted-mvp-private.local.json"
$summaryFile = Join-Path $PSScriptRoot "hosted-mvp-summary.json"
New-Item -ItemType Directory -Path $buildConfigDir -Force | Out-Null

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

function ConvertTo-CompactJson {
    param($Value)
    return ($Value | ConvertTo-Json -Depth 30 -Compress)
}

function New-AccessCode {
    $bytes = New-Object byte[] 18
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return "3drams-" + (Convert-BytesToHex $bytes)
}

function Get-Sha256Hex {
    param([string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    return Convert-BytesToHex $sha.ComputeHash($bytes)
}

function Convert-BytesToHex {
    param([byte[]]$Bytes)
    return (($Bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

$identity = Invoke-AwsJson @("sts", "get-caller-identity", "--profile", $Profile, "--output", "json")
$accountId = $identity.Account
$roleName = "$Prefix-lambda-role"
$policyName = "$Prefix-lambda-policy"
$functionName = "$Prefix-api"
$tableName = "$Prefix-sessions"
$bucketName = ("$Prefix-uploads-$accountId-$Region").ToLowerInvariant()
$apiName = "$Prefix-http-api"
$logGroupName = "/aws/lambda/$functionName"

if (Test-Path $privateFile) {
    $private = Get-Content $privateFile -Raw | ConvertFrom-Json
    $accessCode = $private.accessCode
    $accessHash = $private.accessHash
} else {
    $accessCode = New-AccessCode
    $accessHash = Get-Sha256Hex $accessCode
    [pscustomobject]@{
        accessCode = $accessCode
        accessHash = $accessHash
        createdAt = (Get-Date).ToUniversalTime().ToString("o")
        note = "Private local handoff only. Do not commit or paste into public docs."
    } | ConvertTo-Json | Set-Content -Path $privateFile -Encoding utf8
}

$trustPolicy = ConvertTo-CompactJson @{
    Version = "2012-10-17"
    Statement = @(@{
        Effect = "Allow"
        Principal = @{ Service = "lambda.amazonaws.com" }
        Action = "sts:AssumeRole"
    })
}
$trustPolicyFile = Join-Path $buildConfigDir "lambda-trust-policy.json"
$trustPolicy | Set-Content -Path $trustPolicyFile -Encoding ascii

try {
    $role = Invoke-AwsJson @("iam", "get-role", "--role-name", $roleName, "--profile", $Profile, "--output", "json")
} catch {
    $role = Invoke-AwsJson @("iam", "create-role", "--role-name", $roleName, "--assume-role-policy-document", "file://$trustPolicyFile", "--profile", $Profile, "--output", "json")
    Start-Sleep -Seconds 8
}
$roleArn = $role.Role.Arn

$bucketArn = "arn:aws:s3:::$bucketName"
$tableArn = "arn:aws:dynamodb:${Region}:${accountId}:table/$tableName"
$modelArn = "arn:aws:bedrock:${Region}::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0"
$policyDoc = ConvertTo-CompactJson @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Action = @("logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents")
            Resource = "arn:aws:logs:${Region}:${accountId}:*"
        },
        @{
            Effect = "Allow"
            Action = @("bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream")
            Resource = $modelArn
        },
        @{
            Effect = "Allow"
            Action = @("dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem")
            Resource = $tableArn
        },
        @{
            Effect = "Allow"
            Action = @("s3:PutObject", "s3:GetObject")
            Resource = "$bucketArn/sessions/*"
        }
    )
}
$policyDocFile = Join-Path $buildConfigDir "lambda-inline-policy.json"
$policyDoc | Set-Content -Path $policyDocFile -Encoding ascii
Invoke-AwsText @("iam", "put-role-policy", "--role-name", $roleName, "--policy-name", $policyName, "--policy-document", "file://$policyDocFile", "--profile", $Profile) | Out-Null

try {
    Invoke-AwsJson @("dynamodb", "describe-table", "--table-name", $tableName, "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
} catch {
    Invoke-AwsJson @(
        "dynamodb", "create-table",
        "--table-name", $tableName,
        "--attribute-definitions", "AttributeName=sessionId,AttributeType=S",
        "--key-schema", "AttributeName=sessionId,KeyType=HASH",
        "--billing-mode", "PAY_PER_REQUEST",
        "--region", $Region,
        "--profile", $Profile,
        "--output", "json"
    ) | Out-Null
    Invoke-AwsText @("dynamodb", "wait", "table-exists", "--table-name", $tableName, "--region", $Region, "--profile", $Profile) | Out-Null
}
try {
    Invoke-AwsText @("dynamodb", "update-time-to-live", "--table-name", $tableName, "--time-to-live-specification", "Enabled=true,AttributeName=expiresAt", "--region", $Region, "--profile", $Profile) | Out-Null
} catch {
    if ($_.Exception.Message -notmatch "already enabled") { throw }
}

try {
    Invoke-AwsText @("s3api", "head-bucket", "--bucket", $bucketName, "--profile", $Profile) | Out-Null
} catch {
    Invoke-AwsJson @("s3api", "create-bucket", "--bucket", $bucketName, "--create-bucket-configuration", "LocationConstraint=$Region", "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
}
Invoke-AwsText @("s3api", "put-public-access-block", "--bucket", $bucketName, "--public-access-block-configuration", "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true", "--profile", $Profile) | Out-Null
$bucketEncryptionFile = Join-Path $buildConfigDir "s3-encryption.json"
'{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' | Set-Content -Path $bucketEncryptionFile -Encoding ascii
$bucketLifecycleFile = Join-Path $buildConfigDir "s3-lifecycle.json"
'{"Rules":[{"ID":"delete-hosted-mvp-uploads-after-7-days","Status":"Enabled","Filter":{"Prefix":"sessions/"},"Expiration":{"Days":7}}]}' | Set-Content -Path $bucketLifecycleFile -Encoding ascii
Invoke-AwsText @("s3api", "put-bucket-encryption", "--bucket", $bucketName, "--server-side-encryption-configuration", "file://$bucketEncryptionFile", "--profile", $Profile) | Out-Null
Invoke-AwsText @("s3api", "put-bucket-lifecycle-configuration", "--bucket", $bucketName, "--lifecycle-configuration", "file://$bucketLifecycleFile", "--profile", $Profile) | Out-Null

$origins = @("http://localhost:5173", "http://127.0.0.1:5173")
if (-not [string]::IsNullOrWhiteSpace($AmplifyOrigin)) { $origins += $AmplifyOrigin.TrimEnd("/") }
$allowedOrigins = $origins -join ","
$envJson = ConvertTo-CompactJson @{
    Variables = @{
        APP_ENV = "hosted"
        ALLOWED_ORIGINS = $allowedOrigins
        APP_ACCESS_TOKEN_HASH = $accessHash
        APP_ACCESS_CODE_LABEL = "team-test"
        ENABLE_BEDROCK = "true"
        BEDROCK_MODEL_ID = "anthropic.claude-3-7-sonnet-20250219-v1:0"
        BEDROCK_MAX_TOKENS = "1200"
        BEDROCK_TEMPERATURE = "0.2"
        BEDROCK_MAX_MODEL_CALLS = "2"
        BEDROCK_PLANNER_MAX_TOKENS = "900"
        BEDROCK_REASONER_MAX_TOKENS = "1500"
        BEDROCK_COMPILER_MAX_TOKENS = "2200"
        DURABLE_RUN_MAX_TOOL_CALLS = "12"
        DURABLE_RUN_TIMEOUT_SECONDS = "45"
        DURABLE_RUN_PROCESS_INLINE = "true"
        S3_UPLOAD_BUCKET = $bucketName
        DYNAMODB_SESSION_TABLE = $tableName
        UPLOAD_RETENTION_DAYS = "7"
        SESSION_RETENTION_DAYS = "7"
        ENABLE_GEOAPIFY_GEOCODING = "false"
        GEOAPIFY_GEOCODING_LIMIT = "3"
        GEOAPIFY_GEOCODING_TIMEOUT_SECONDS = "4"
    }
}
$envJsonFile = Join-Path $buildConfigDir "lambda-env.json"
$envJson | Set-Content -Path $envJsonFile -Encoding ascii

try {
    Invoke-AwsJson @("lambda", "get-function", "--function-name", $functionName, "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
    Invoke-AwsJson @("lambda", "update-function-code", "--function-name", $functionName, "--zip-file", "fileb://$zipPath", "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
    Invoke-AwsText @("lambda", "wait", "function-updated", "--function-name", $functionName, "--region", $Region, "--profile", $Profile) | Out-Null
    Invoke-AwsJson @(
        "lambda", "update-function-configuration",
        "--function-name", $functionName,
        "--runtime", "python3.11",
        "--handler", "backend.app.lambda_handler.handler",
        "--timeout", "60",
        "--memory-size", "1024",
        "--environment", "file://$envJsonFile",
        "--region", $Region,
        "--profile", $Profile,
        "--output", "json"
    ) | Out-Null
} catch {
    Invoke-AwsJson @(
        "lambda", "create-function",
        "--function-name", $functionName,
        "--runtime", "python3.11",
        "--handler", "backend.app.lambda_handler.handler",
        "--role", $roleArn,
        "--zip-file", "fileb://$zipPath",
        "--timeout", "60",
        "--memory-size", "1024",
        "--environment", "file://$envJsonFile",
        "--region", $Region,
        "--profile", $Profile,
        "--output", "json"
    ) | Out-Null
}
Invoke-AwsText @("lambda", "wait", "function-active", "--function-name", $functionName, "--region", $Region, "--profile", $Profile) | Out-Null
try {
    Invoke-AwsJson @("lambda", "put-function-concurrency", "--function-name", $functionName, "--reserved-concurrent-executions", "2", "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
} catch {
    Write-Warning "Could not set reserved concurrency. Continue with account defaults. $($_.Exception.Message)"
}

try {
    Invoke-AwsJson @("logs", "create-log-group", "--log-group-name", $logGroupName, "--region", $Region, "--profile", $Profile, "--output", "json") | Out-Null
} catch {}
try {
    Invoke-AwsText @("logs", "put-retention-policy", "--log-group-name", $logGroupName, "--retention-in-days", "7", "--region", $Region, "--profile", $Profile) | Out-Null
} catch {}

$lambdaArn = "arn:aws:lambda:${Region}:${accountId}:function:$functionName"
$apis = Invoke-AwsJson @("apigatewayv2", "get-apis", "--region", $Region, "--profile", $Profile, "--output", "json")
$api = $apis.Items | Where-Object { $_.Name -eq $apiName } | Select-Object -First 1
if (-not $api) {
    $api = Invoke-AwsJson @(
        "apigatewayv2", "create-api",
        "--name", $apiName,
        "--protocol-type", "HTTP",
        "--target", $lambdaArn,
        "--cors-configuration", "AllowOrigins=$allowedOrigins,AllowMethods=GET,POST,OPTIONS,AllowHeaders=content-type,x-3drams-access",
        "--region", $Region,
        "--profile", $Profile,
        "--output", "json"
    )
} else {
    Invoke-AwsJson @(
        "apigatewayv2", "update-api",
        "--api-id", $api.ApiId,
        "--cors-configuration", "AllowOrigins=$allowedOrigins,AllowMethods=GET,POST,OPTIONS,AllowHeaders=content-type,x-3drams-access",
        "--region", $Region,
        "--profile", $Profile,
        "--output", "json"
    ) | Out-Null
}
$apiId = $api.ApiId
$apiEndpoint = "https://$apiId.execute-api.$Region.amazonaws.com"

try {
    Invoke-AwsJson @(
        "lambda", "add-permission",
        "--function-name", $functionName,
        "--statement-id", "$Prefix-apigw-invoke",
        "--action", "lambda:InvokeFunction",
        "--principal", "apigateway.amazonaws.com",
        "--source-arn", "arn:aws:execute-api:${Region}:${accountId}:$apiId/*",
        "--region", $Region,
        "--profile", $Profile,
        "--output", "json"
    ) | Out-Null
} catch {}

$summary = [pscustomobject]@{
    accountId = $accountId
    region = $Region
    prefix = $Prefix
    functionName = $functionName
    apiName = $apiName
    apiId = $apiId
    apiEndpoint = $apiEndpoint
    dynamodbTable = $tableName
    s3Bucket = $bucketName
    lambdaRole = $roleName
    logGroup = $logGroupName
    allowedOrigins = $origins
    privateHandoffFile = $privateFile
    createdAt = (Get-Date).ToUniversalTime().ToString("o")
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryFile -Encoding utf8
$summary | ConvertTo-Json -Depth 8
