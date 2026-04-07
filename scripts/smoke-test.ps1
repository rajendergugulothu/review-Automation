param(
    [string]$BackendBase = "http://localhost:8000",
    [string]$FrontendBase = "http://localhost:3000",
    [switch]$SkipFrontendCheck
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Json {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Uri,
        [object]$Body = $null
    )

    $params = @{
        Method     = $Method
        Uri        = $Uri
        TimeoutSec = 30
    }

    if ($null -ne $Body) {
        $params["ContentType"] = "application/json"
        $params["Body"] = ($Body | ConvertTo-Json -Depth 10)
    }

    try {
        return Invoke-RestMethod @params
    }
    catch {
        $statusCode = ""
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = " status=" + $_.Exception.Response.StatusCode.value__
        }
        throw "Request failed: $Method $Uri$statusCode. $($_.Exception.Message)"
    }
}

function Get-TokenFromReviewLink {
    param([string]$ReviewLink)
    $parts = $ReviewLink.TrimEnd("/") -split "/"
    return $parts[-1]
}

Write-Step "Checking backend health"
$docs = Invoke-WebRequest -Uri "$BackendBase/docs" -UseBasicParsing -TimeoutSec 15
Assert-True ($docs.StatusCode -eq 200) "Backend docs not reachable at $BackendBase/docs"

if (-not $SkipFrontendCheck) {
    Write-Step "Checking frontend admin page"
    $adminPage = Invoke-WebRequest -Uri "$FrontendBase/admin" -UseBasicParsing -TimeoutSec 15
    Assert-True ($adminPage.StatusCode -eq 200) "Frontend admin page not reachable at $FrontendBase/admin"
}

Write-Step "Creating negative-path review request"
$createNegative = Invoke-Json -Method "POST" -Uri "$BackendBase/create-review-request" -Body @{
    client_name  = "Smoke Test Negative"
    client_email = "smoke-negative@example.com"
    client_phone = "1112223333"
    event_type   = "move_in"
    channel      = "email"
}
Assert-True (-not [string]::IsNullOrWhiteSpace($createNegative.review_link)) "Missing review_link for negative-path request"
$negativeToken = Get-TokenFromReviewLink -ReviewLink $createNegative.review_link

Write-Step "Validating negative-path token"
$ratePageNegative = Invoke-Json -Method "GET" -Uri "$BackendBase/rate/$negativeToken"
Assert-True ($ratePageNegative.token -eq $negativeToken) "Negative token validation failed"

Write-Step "Submitting negative rating (2)"
$negativeRating = Invoke-Json -Method "POST" -Uri "$BackendBase/submit-rating" -Body @{
    token  = $negativeToken
    rating = 2
    name   = "Smoke Test Negative"
    email  = "smoke-negative@example.com"
}
Assert-True ($negativeRating.type -eq "negative") "Expected negative routing for rating=2"
Assert-True ($negativeRating.redirect_url -match "/internal-feedback\?token=") "Expected internal feedback redirect URL"

Write-Step "Submitting internal feedback for negative-path token"
$feedbackResponse = Invoke-Json -Method "POST" -Uri "$BackendBase/submit-feedback" -Body @{
    token    = $negativeToken
    name     = "Smoke Test Negative"
    email    = "smoke-negative@example.com"
    feedback = "Smoke test feedback submission"
}
Assert-True ($feedbackResponse.message -eq "Feedback submitted successfully") "Feedback submission failed"

Write-Step "Creating positive-path review request"
$createPositive = Invoke-Json -Method "POST" -Uri "$BackendBase/create-review-request" -Body @{
    client_name  = "Smoke Test Positive"
    client_email = "smoke-positive@example.com"
    client_phone = "4445556666"
    event_type   = "move_out"
    channel      = "sms"
}
Assert-True (-not [string]::IsNullOrWhiteSpace($createPositive.review_link)) "Missing review_link for positive-path request"
$positiveToken = Get-TokenFromReviewLink -ReviewLink $createPositive.review_link

Write-Step "Validating positive-path token"
$ratePagePositive = Invoke-Json -Method "GET" -Uri "$BackendBase/rate/$positiveToken"
Assert-True ($ratePagePositive.token -eq $positiveToken) "Positive token validation failed"

Write-Step "Submitting positive rating (5)"
$positiveRating = Invoke-Json -Method "POST" -Uri "$BackendBase/submit-rating" -Body @{
    token  = $positiveToken
    rating = 5
    name   = "Smoke Test Positive"
    email  = "smoke-positive@example.com"
}
Assert-True ($positiveRating.type -eq "positive") "Expected positive routing for rating=5"
Assert-True ($positiveRating.redirect_url -like "https://*") "Expected external redirect URL for positive rating"

Write-Step "Checking admin APIs"
$reviews = Invoke-Json -Method "GET" -Uri "$BackendBase/admin/reviews"
$analytics = Invoke-Json -Method "GET" -Uri "$BackendBase/admin/analytics"

$reviewList = @($reviews)
$ourRows = @($reviewList | Where-Object { $_.unique_token -in @($negativeToken, $positiveToken) })
Assert-True ($ourRows.Count -eq 2) "Expected 2 inserted rows in /admin/reviews for smoke test tokens"

$negativeRow = $ourRows | Where-Object { $_.unique_token -eq $negativeToken } | Select-Object -First 1
$positiveRow = $ourRows | Where-Object { $_.unique_token -eq $positiveToken } | Select-Object -First 1
Assert-True ($null -ne $negativeRow) "Negative row not found in reviews"
Assert-True ($null -ne $positiveRow) "Positive row not found in reviews"
Assert-True ($negativeRow.rating -eq 2) "Negative row rating mismatch"
Assert-True ($negativeRow.status -eq "feedback_received") "Negative row status mismatch"
Assert-True ($positiveRow.rating -eq 5) "Positive row rating mismatch"
Assert-True ($positiveRow.status -eq "completed") "Positive row status mismatch"

Assert-True ($null -ne $analytics.average_rating) "Analytics missing average_rating"
Assert-True ($null -ne $analytics.total_reviews) "Analytics missing total_reviews"
Assert-True ($null -ne $analytics.positive_reviews) "Analytics missing positive_reviews"
Assert-True ($null -ne $analytics.negative_reviews) "Analytics missing negative_reviews"
Assert-True ([int]$analytics.total_reviews -ge 2) "Unexpected analytics total_reviews value"

Write-Step "Smoke test passed"
[pscustomobject]@{
    result         = "PASS"
    backend        = $BackendBase
    frontend       = $FrontendBase
    negative_token = $negativeToken
    positive_token = $positiveToken
    reviews_count  = $reviewList.Count
    average_rating = $analytics.average_rating
    total_reviews  = $analytics.total_reviews
} | Format-List
