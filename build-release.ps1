$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ReleaseName = "legal-contract-assistant-gui-$Stamp"
$DistRoot = Join-Path $ProjectRoot "dist"
$ReleaseDir = Join-Path $DistRoot $ReleaseName

Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js 20.19+ and try again."
}

Push-Location -LiteralPath (Join-Path $ProjectRoot "frontend")
npm install
npm run build
Pop-Location

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "frontend") | Out-Null

function Copy-FilteredTree {
    param(
        [string]$Source,
        [string]$Destination
    )
    Get-ChildItem -LiteralPath $Source -Recurse -File |
        Where-Object {
            $_.FullName -notlike "*\__pycache__\*" -and
            $_.Name -notlike "*.pyc" -and
            $_.Name -notlike "*.pyo" -and
            $_.Name -notlike "*.tsbuildinfo"
        } |
        ForEach-Object {
            $Relative = $_.FullName.Substring($Source.Length).TrimStart("\")
            $Target = Join-Path $Destination $Relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $Target
        }
}

Copy-FilteredTree -Source (Join-Path $ProjectRoot "src") -Destination (Join-Path $ReleaseDir "src")
Copy-FilteredTree -Source (Join-Path $ProjectRoot "tests") -Destination (Join-Path $ReleaseDir "tests")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "frontend\dist") -Destination (Join-Path $ReleaseDir "frontend") -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot "RELEASE_NOTES.md") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot "USER_GUIDE.zh-TW.md") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot "requirements.txt") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot "requirements-dev.txt") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot "start-gui.ps1") -Destination $ReleaseDir

$ZipPath = Join-Path $DistRoot "$ReleaseName.zip"
Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $ZipPath -Force
Write-Host "Created $ZipPath"
