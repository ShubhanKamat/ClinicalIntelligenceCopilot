$ErrorActionPreference = "Stop"

$Region = "us-east-1"

$Cluster = "obesity-ci-copilot-v3"
$Service = "obesity-ci-copilot-v3"

Write-Host ""
Write-Host "Starting Fargate demo backend..."

aws ecs update-service `
    --region $Region `
    --cluster $Cluster `
    --service $Service `
    --desired-count 1 `
    --force-new-deployment `
    --output json |
    Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "Could not start Fargate."
}

$TaskArn = $null

for ($Attempt = 1; $Attempt -le 60; $Attempt++) {

    $TaskArn = (
        aws ecs list-tasks `
            --region $Region `
            --cluster $Cluster `
            --service-name $Service `
            --desired-status RUNNING `
            --query "taskArns[0]" `
            --output text
    ).Trim()

    if (
        -not [string]::IsNullOrWhiteSpace($TaskArn) `
        -and `
        $TaskArn -ne "None"
    ) {
        break
    }

    Write-Host "Waiting for Fargate task... $Attempt"

    Start-Sleep -Seconds 5
}

if (
    [string]::IsNullOrWhiteSpace($TaskArn) `
    -or `
    $TaskArn -eq "None"
) {
    throw "No running Fargate task found."
}


$TaskJson = @(
    aws ecs describe-tasks `
        --region $Region `
        --cluster $Cluster `
        --tasks $TaskArn `
        --output json
) -join "`n"

$Task = (
    $TaskJson |
    ConvertFrom-Json
).tasks[0]

$Attachment = (
    $Task.attachments |
    Where-Object {
        $_.type -eq "ElasticNetworkInterface"
    } |
    Select-Object -First 1
)

$Eni = (
    $Attachment.details |
    Where-Object {
        $_.name -eq "networkInterfaceId"
    } |
    Select-Object -First 1
).value

if (
    [string]::IsNullOrWhiteSpace($Eni)
) {
    throw "Could not resolve ECS ENI."
}


$PublicIp = $null

for ($Attempt = 1; $Attempt -le 30; $Attempt++) {

    $PublicIp = (
        aws ec2 describe-network-interfaces `
            --region $Region `
            --network-interface-ids $Eni `
            --query "NetworkInterfaces[0].Association.PublicIp" `
            --output text
    ).Trim()

    if (
        -not [string]::IsNullOrWhiteSpace($PublicIp) `
        -and `
        $PublicIp -ne "None"
    ) {
        break
    }

    Start-Sleep -Seconds 3
}


if (
    [string]::IsNullOrWhiteSpace($PublicIp) `
    -or `
    $PublicIp -eq "None"
) {
    throw "No Fargate public IP."
}


$ApiUrl = "http://$PublicIp`:8000"


Write-Host ""
Write-Host "Backend:"
Write-Host $ApiUrl


Write-Host ""
Write-Host "Waiting for /health..."


$Healthy = $false

for ($Attempt = 1; $Attempt -le 40; $Attempt++) {

    try {

        $Health = Invoke-RestMethod `
            -Uri "$ApiUrl/health" `
            -Method Get `
            -TimeoutSec 10

        if ($Health.status -eq "ok") {

            $Healthy = $true
            break
        }

    }
    catch {

        Write-Host "API not ready... $Attempt"
    }

    Start-Sleep -Seconds 5
}


if (-not $Healthy) {
    throw "Fargate API failed health check."
}


$env:COPILOT_API_URL = $ApiUrl


Write-Host ""
Write-Host "Backend healthy."
Write-Host ""
Write-Host "Starting Streamlit..."
Write-Host ""


python -m streamlit run `
    ".\ui\streamlit_app.py" `
    --server.port 8501
