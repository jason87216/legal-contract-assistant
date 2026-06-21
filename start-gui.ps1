$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11+ and try again."
}

if (-not (Test-Path -LiteralPath ".venv")) {
    python -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

$FrontendPackage = Join-Path $ProjectRoot "frontend\package.json"
$FrontendIndex = Join-Path $ProjectRoot "frontend\dist\index.html"
if ((Test-Path -LiteralPath $FrontendPackage) -and -not (Test-Path -LiteralPath $FrontendIndex)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found. Install Node.js 20.19+ and try again."
    }
    Push-Location -LiteralPath (Join-Path $ProjectRoot "frontend")
    npm install
    npm run build
    Pop-Location
}

Start-Process "http://127.0.0.1:8787"
& $Python -m uvicorn src.legal_contract_assistant.web_app:app --host 127.0.0.1 --port 8787
