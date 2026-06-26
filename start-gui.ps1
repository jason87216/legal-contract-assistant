$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$HostAddress = "127.0.0.1"
$Port = 8787
$AppUrl = "http://${HostAddress}:$Port"

function Test-PortInUse {
    param(
        [string]$Address,
        [int]$PortNumber
    )

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $AsyncResult = $Client.BeginConnect($Address, $PortNumber, $null, $null)
        if (-not $AsyncResult.AsyncWaitHandle.WaitOne(300)) {
            return $false
        }
        $Client.EndConnect($AsyncResult)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $Client.Close()
    }
}

if (Test-PortInUse -Address $HostAddress -PortNumber $Port) {
    Write-Warning "Port $Port is already in use. A local service may already be running at $AppUrl."
    Write-Warning "Opening the existing URL instead of starting another server. Stop the old PowerShell window with Ctrl+C if you need to restart."
    Start-Process $AppUrl
    exit 1
}

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

Start-Process $AppUrl
& $Python -m uvicorn src.legal_contract_assistant.web_app:app --host $HostAddress --port $Port
