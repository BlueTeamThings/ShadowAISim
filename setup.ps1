#Requires -Version 5.1
# Shadow AI Simulator — One-command setup & launch for Windows
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  Shadow AI Simulator — Setup & Launch" -ForegroundColor Cyan
Write-Host "  Red Team DLP / EDR Validation Toolkit" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── Python check ─────────────────────────────────────────────────────────────
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { $pythonCmd = $cmd; break }
}
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python not found. Install Python 3.9+ from python.org and re-run." -ForegroundColor Red
    exit 1
}
$verStr   = & $pythonCmd --version 2>&1
$minorNum = [int]($verStr -replace "Python 3\.", "" -replace "\..*", "")
if ($minorNum -lt 9) {
    Write-Host "[ERROR] Python 3.9+ required. Found: $verStr" -ForegroundColor Red; exit 1
}
Write-Host "[OK] $verStr found" -ForegroundColor Green

# ── Virtual environment ───────────────────────────────────────────────────────
$VenvDir = Join-Path $env:USERPROFILE ".shadow-ai-simulator\venv"

if (-not (Test-Path "$VenvDir\Scripts\Activate.ps1")) {
    Write-Host "[*] Creating virtual environment at $VenvDir"
    New-Item -ItemType Directory -Force -Path (Split-Path $VenvDir) | Out-Null
    & $pythonCmd -m venv $VenvDir
}

$VenvDir | Out-File -FilePath ".venv_path" -Encoding utf8
Write-Host "[OK] Virtual environment ready" -ForegroundColor Green

# ── Dependencies ──────────────────────────────────────────────────────────────
& "$VenvDir\Scripts\Activate.ps1"
Write-Host "[*] Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# ── Playwright ────────────────────────────────────────────────────────────────
Write-Host "[*] Installing Playwright Chromium..."
playwright install chromium
Write-Host "[OK] Playwright Chromium ready" -ForegroundColor Green

# ── Launch ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[OK] Setup complete! Starting server..." -ForegroundColor Green
Write-Host "     Open: http://127.0.0.1:8766" -ForegroundColor Cyan
Write-Host ""
python main.py
