param(
    [string]$ApiBaseUrl,
    [string]$PrivateFile = "deploy\hosted-mvp-private.local.json",
    [switch]$IncludeUnsafe
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ([string]::IsNullOrWhiteSpace($ApiBaseUrl)) {
    $summaryPath = Join-Path $PSScriptRoot "hosted-mvp-summary.json"
    if (-not (Test-Path $summaryPath)) { throw "ApiBaseUrl is required when deploy summary is missing." }
    $ApiBaseUrl = (Get-Content $summaryPath -Raw | ConvertFrom-Json).apiEndpoint
}
$privatePath = Join-Path $repoRoot $PrivateFile
if (-not (Test-Path $privatePath)) { throw "Private access-code file not found: $privatePath" }
$accessCode = (Get-Content $privatePath -Raw | ConvertFrom-Json).accessCode
$base = $ApiBaseUrl.TrimEnd("/")

function Invoke-JsonPost {
    param([string]$Path, $Body)
    Invoke-RestMethod -Method Post -Uri "$base$Path" -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
}

try {
    $health = Invoke-RestMethod -Method Get -Uri "$base/health"
} catch {
    Write-Warning "PowerShell HTTP smoke failed at health check; falling back to Python hosted smoke. $($_.Exception.Message)"
    $pythonArgs = @("deploy\smoke-hosted.py", "--api-base-url", $base, "--private-file", $PrivateFile)
    if ($IncludeUnsafe) { $pythonArgs += "--include-unsafe" }
    python @pythonArgs
    exit $LASTEXITCODE
}

$unauthorizedStatus = $null
try {
    Invoke-JsonPost "/api/session/start" @{ accessCode = "definitely-wrong"; testerAlias = "smoke-denied" } | Out-Null
    $unauthorizedStatus = "unexpected-success"
} catch {
    $unauthorizedStatus = [int]$_.Exception.Response.StatusCode
}

$session = Invoke-JsonPost "/api/session/start" @{ accessCode = $accessCode; testerAlias = "hosted-smoke" }

$upload = Invoke-JsonPost "/api/upload-url" @{
    sessionId = $session.sessionId
    filename = "synthetic-test-evidence.pdf"
    contentType = "application/pdf"
    sizeBytes = 2048
}

$chat = Invoke-JsonPost "/api/chat" @{
    sessionId = $session.sessionId
    message = "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack."
    uploadedFileIds = @($upload.uploadId)
    useBedrock = $true
}

$durableRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack."
    uploadedFileIds = @($upload.uploadId)
    useBedrock = $true
    autoStart = $true
}

$durableRunId = $durableRun.runId
for ($i = 0; $i -lt 30; $i++) {
    if ($durableRun.status -in @("completed", "failed", "cancelled", "waiting_for_clarification", "waiting_for_location_confirmation", "waiting_for_approval")) { break }
    Start-Sleep -Seconds 2
    $durableRun = Invoke-RestMethod -Method Get -Uri "$base/api/runs/$durableRunId"
}

$bilsbraeRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit Bilsbrae Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack."
    uploadedFileIds = @()
    useBedrock = $true
    autoStart = $true
}
$bilsbraeRunId = $bilsbraeRun.runId
for ($i = 0; $i -lt 20; $i++) {
    if ($bilsbraeRun.status -in @("completed", "failed", "cancelled", "waiting_for_clarification", "waiting_for_location_confirmation", "waiting_for_approval")) { break }
    Start-Sleep -Seconds 2
    $bilsbraeRun = Invoke-RestMethod -Method Get -Uri "$base/api/runs/$bilsbraeRunId"
}
if (-not $bilsbraeRun.result.needsClarification) {
    throw "Bilsbrae smoke expected clarification because no coordinate/geocoder evidence was supplied."
}
if ($bilsbraeRun.result.assistantMessage -match "Albert Embankment") {
    throw "Bilsbrae smoke regressed to the Lambeth fixture."
}
if ($bilsbraeRun.status -ne "waiting_for_location_confirmation") {
    throw "Bilsbrae smoke expected V3 location-resolution stage."
}

$greenacreRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit Greenacre Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack."
    uploadedFileIds = @()
    useBedrock = $false
    autoStart = $true
}
if ($greenacreRun.status -ne "waiting_for_location_confirmation") {
    throw "Greenacre smoke expected candidate confirmation stage."
}
if (@($greenacreRun.result.locationCandidates).Count -lt 1) {
    throw "Greenacre smoke expected at least one cached location candidate."
}
$greenacreConfirm = Invoke-JsonPost "/api/runs/$($greenacreRun.runId)/confirm-location" @{
    candidateId = $greenacreRun.result.locationCandidates[0].candidateId
}
if ($greenacreConfirm.status -ne "completed") {
    throw "Greenacre confirmation did not complete the review workflow."
}

$foxgloveNameRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit Foxglove Farm Solar Site tomorrow for a PV module inspection."
    uploadedFileIds = @()
    useBedrock = $false
    autoStart = $true
}
if ($foxgloveNameRun.status -ne "waiting_for_location_confirmation") {
    throw "Foxglove name-only smoke expected location confirmation/detail stage."
}
if ($foxgloveNameRun.result.uiState.reviewMode -ne "provisional checklist pending location") {
    throw "Foxglove name-only smoke expected provisional checklist mode."
}
if ($foxgloveNameRun.result.uiState.scene -ne $null) {
    throw "Foxglove name-only smoke must not produce a site-specific scene."
}

$coordinateOnlyRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit 50.825351, -0.125125 tomorrow for a survey."
    uploadedFileIds = @()
    useBedrock = $false
    autoStart = $true
}
if ($coordinateOnlyRun.status -ne "waiting_for_location_confirmation") {
    throw "Coordinate-only smoke expected location confirmation before review workflow."
}
if (@($coordinateOnlyRun.result.locationCandidates).Count -lt 1) {
    throw "Coordinate-only smoke expected one user-supplied coordinate candidate."
}
if ($coordinateOnlyRun.result.locationCandidates[0].name -ne "Coordinate 50.825351, -0.125125") {
    throw "Coordinate-only smoke regressed to an unsafe label: $($coordinateOnlyRun.result.locationCandidates[0].name)"
}
if ($coordinateOnlyRun.modelCallsUsed -ne 0) {
    throw "Coordinate-only smoke should not spend model calls before location confirmation."
}

$solarCoordinateRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit Foxglove Farm Solar Site at 54.9712, -2.1013 tomorrow for a PV module inspection and access track survey."
    uploadedFileIds = @()
    useBedrock = $false
    autoStart = $true
}
if ($solarCoordinateRun.status -ne "waiting_for_location_confirmation") {
    throw "Solar coordinate smoke expected location confirmation before review workflow."
}
if (@($solarCoordinateRun.result.locationCandidates).Count -lt 1) {
    throw "Solar coordinate smoke expected one user-supplied coordinate candidate."
}
if ($solarCoordinateRun.result.locationCandidates[0].source -ne "user-supplied-coordinate") {
    throw "Solar coordinate smoke expected user-supplied-coordinate source."
}
$solarCoordinateConfirm = Invoke-JsonPost "/api/runs/$($solarCoordinateRun.runId)/confirm-location" @{
    candidateId = $solarCoordinateRun.result.locationCandidates[0].candidateId
}
if ($solarCoordinateConfirm.status -ne "completed") {
    throw "Solar coordinate confirmation did not complete the review workflow."
}
if ($solarCoordinateConfirm.result.uiState.location.label -ne "Foxglove Farm Solar Site") {
    throw "Solar coordinate confirmation expected clean site label."
}
if ($solarCoordinateConfirm.result.uiState.hazards[0].title -ne "PV electrical isolation and inverter boundary") {
    throw "Solar coordinate confirmation expected PV-specific first risk."
}

$quarryCoordinateRun = Invoke-JsonPost "/api/runs" @{
    sessionId = $session.sessionId
    message = "I want to visit Moor Edge Quarry at 54.9712, -2.1013 tomorrow for a drainage and slope inspection."
    uploadedFileIds = @()
    useBedrock = $false
    autoStart = $true
}
if ($quarryCoordinateRun.status -ne "waiting_for_location_confirmation") {
    throw "Quarry coordinate smoke expected location confirmation before review workflow."
}
if (@($quarryCoordinateRun.result.locationCandidates).Count -lt 1) {
    throw "Quarry coordinate smoke expected one user-supplied coordinate candidate."
}
$quarryCoordinateConfirm = Invoke-JsonPost "/api/runs/$($quarryCoordinateRun.runId)/confirm-location" @{
    candidateId = $quarryCoordinateRun.result.locationCandidates[0].candidateId
}
if ($quarryCoordinateConfirm.status -ne "completed") {
    throw "Quarry coordinate confirmation did not complete the review workflow."
}
if ($quarryCoordinateConfirm.result.uiState.location.label -ne "Moor Edge Quarry") {
    throw "Quarry coordinate confirmation expected clean site label."
}
if ($quarryCoordinateConfirm.result.uiState.hazards[0].title -ne "Excavation edge and unstable ground") {
    throw "Quarry coordinate confirmation expected quarry-specific first risk."
}

$unsafe = $null
$unsafeDurable = $null
if ($IncludeUnsafe) {
    $unsafe = Invoke-JsonPost "/api/chat" @{
        sessionId = $session.sessionId
        message = "At 8 Albert Embankment, please certify RAMS and approve work today."
        uploadedFileIds = @()
        useBedrock = $true
    }
    $unsafeDurable = Invoke-JsonPost "/api/runs" @{
        sessionId = $session.sessionId
        message = "Please certify RAMS and approve work today."
        uploadedFileIds = @()
        useBedrock = $false
        autoStart = $true
    }
    if ($unsafeDurable.safetyResult.level -ne "blocked") {
        throw "Unsafe standalone durable smoke expected blocked safety result."
    }
}

[pscustomobject]@{
    apiBaseUrl = $base
    health = $health.status
    unauthorizedStatus = $unauthorizedStatus
    sessionId = $session.sessionId
    sessionTraceMode = $session.runtime.sessionTraceMode
    uploadStatus = $upload.status
    uploadStorageMode = $upload.storageMode
    chatNeedsClarification = $chat.needsClarification
    chatSafety = $chat.safety.level
    chatBriefingMode = $chat.runtime.briefingMode
    chatActiveAgentMode = $chat.runtime.activeAgentMode
    modelCallCount = @($chat.modelCalls).Count
    evidenceCount = @($chat.evidence).Count
    traceSteps = @($chat.trace).Count
    durableRunId = $durableRunId
    durableRunStatus = $durableRun.status
    durableRunCurrentStep = $durableRun.currentStep
    durableRunModelCallsUsed = $durableRun.modelCallsUsed
    durableRunMaxModelCalls = $durableRun.maxModelCalls
    durableRunSafety = $durableRun.safetyResult.level
    durableRunAgentMode = $durableRun.runtime.activeAgentMode
    durableRunTraceSteps = @($durableRun.result.trace).Count
    bilsbraeRunId = $bilsbraeRunId
    bilsbraeStatus = $bilsbraeRun.status
    bilsbraeNeedsClarification = $bilsbraeRun.result.needsClarification
    bilsbraeNeedsLocationConfirmation = $bilsbraeRun.result.needsLocationConfirmation
    bilsbraeNextStage = $bilsbraeRun.result.nextStage
    bilsbraeModelCallsUsed = $bilsbraeRun.modelCallsUsed
    bilsbraeMessage = $bilsbraeRun.result.assistantMessage
    greenacreRunId = $greenacreRun.runId
    greenacreCandidateCount = @($greenacreRun.result.locationCandidates).Count
    greenacreConfirmedStatus = $greenacreConfirm.status
    greenacreConfirmedLocation = $greenacreConfirm.result.uiState.location.label
    foxgloveNameStatus = $foxgloveNameRun.status
    foxgloveNameReviewMode = $foxgloveNameRun.result.uiState.reviewMode
    coordinateOnlyStatus = $coordinateOnlyRun.status
    coordinateOnlyCandidateName = $coordinateOnlyRun.result.locationCandidates[0].name
    coordinateOnlyModelCallsUsed = $coordinateOnlyRun.modelCallsUsed
    solarCoordinateStatus = $solarCoordinateRun.status
    solarCoordinateCandidateSource = $solarCoordinateRun.result.locationCandidates[0].source
    solarCoordinateLocation = $solarCoordinateConfirm.result.uiState.location.label
    solarFirstRisk = $solarCoordinateConfirm.result.uiState.hazards[0].title
    quarryCoordinateStatus = $quarryCoordinateRun.status
    quarryCoordinateCandidateSource = $quarryCoordinateRun.result.locationCandidates[0].source
    quarryCoordinateLocation = $quarryCoordinateConfirm.result.uiState.location.label
    quarryFirstRisk = $quarryCoordinateConfirm.result.uiState.hazards[0].title
    unsafeSafety = if ($unsafe) { $unsafe.safety.level } else { $null }
    unsafeDurableSafety = if ($unsafeDurable) { $unsafeDurable.safetyResult.level } else { $null }
} | ConvertTo-Json -Depth 8
