# Run once from repo root:  .\screenshots\copy-from-cursor-assets.ps1
# Copies chat screenshots from Cursor assets into screenshots/ with stable names.

$ErrorActionPreference = "Stop"
$assets = Join-Path $env:USERPROFILE ".cursor\projects\c-Users-david-MyProject-devops-car-detection\assets"
$dest = $PSScriptRoot

if (-not (Test-Path $assets)) {
    Write-Error "Assets folder not found: $assets`nPaste your PNG files into screenshots/ manually instead."
}

$map = @{
    "jenkins-metrics-success.png"    = "*image-4b7026c3*"
    "jenkins-finished-success.png"     = "*image-ed3cee98*"
    "ecr-car-detector-tags.png"        = "*image-d5c03d2e*"
    "jenkins-ecr-push.png"             = "*image-606ab3e8*"
    "eks-cluster-active.png"           = "*image-914fa39a*"
    "kubectl-get-jobs.png"             = "*image-4c3546d3*"
    "eks-pod-logs-metrics.png"         = "*image-b20aabf2*"
    "eks-describe-pod-success.png"     = "*image-2ef02bb6*"
    "eks-describe-pod-irsa.png"        = "*image-979cf412*"
}

foreach ($name in $map.Keys) {
    $src = Get-ChildItem -Path $assets -Filter $map[$name] | Select-Object -First 1
    if (-not $src) { Write-Warning "Missing source for $name"; continue }
    Copy-Item -LiteralPath $src.FullName -Destination (Join-Path $dest $name) -Force
    Write-Host "Copied $name"
}

Write-Host "Done. Commit: git add screenshots/*.png screenshots/README.md README.md"
