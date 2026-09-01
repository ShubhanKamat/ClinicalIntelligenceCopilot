$ErrorActionPreference = "Stop"

$Region = "us-east-1"

$Cluster = "obesity-ci-copilot-v3"
$Service = "obesity-ci-copilot-v3"


aws ecs update-service `
    --region $Region `
    --cluster $Cluster `
    --service $Service `
    --desired-count 0 `
    --output json |
    Out-Null


if ($LASTEXITCODE -ne 0) {
    throw "Could not stop Fargate."
}


Write-Host ""
Write-Host "Fargate desired count = 0."
Write-Host "Demo compute stopped."
