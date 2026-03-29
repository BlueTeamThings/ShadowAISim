#Requires -Version 5.1
# Shadow AI Simulator — One-command setup & launch for Windows
#
# Options:
#   --skip-system-deps   Skip node/npm/npx validation
#   --repair-deps        Re-run all dependency installs
#   --dependency-check   Print dependency status and exit without launching

param(
    [switch]$SkipSystemDeps,
    [switch]$RepairDeps,
    [switch]$DependencyCheck,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$PassArgs
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  Shadow AI Simulator — Setup & Launch" -ForegroundColor Cyan
Write-Host "  Red Team DLP / EDR Validation Toolkit" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── Python check ──────────────────────────────────────────────────────────────
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

# ── System dependency checks ──────────────────────────────────────────────────
if (-not $SkipSystemDeps) {
    Write-Host "[*] Checking system dependencies..."

    # curl — Windows 10+ ships curl.exe
    if (Get-Command curl -ErrorAction SilentlyContinue) {
        Write-Host "[OK] curl found" -ForegroundColor Green
    } else {
        Write-Host "[!] curl not found. PowerShell Invoke-WebRequest will be used as download fallback." -ForegroundColor Yellow
    }

    # PowerShell download support (always available on Win10+)
    try {
        $null = [Net.ServicePointManager]::SecurityProtocol
        Write-Host "[OK] PowerShell Invoke-WebRequest available" -ForegroundColor Green
    } catch {
        Write-Host "[!] PowerShell download support may be limited" -ForegroundColor Yellow
    }

    # Node.js / npm / npx
    $NodeOk = [bool](Get-Command node -ErrorAction SilentlyContinue)
    $NpmOk  = [bool](Get-Command npm  -ErrorAction SilentlyContinue)
    $NpxOk  = [bool](Get-Command npx  -ErrorAction SilentlyContinue)

    if ($NodeOk -and $NpmOk -and $NpxOk) {
        $nodeVer = & node --version 2>&1
        Write-Host "[OK] node $nodeVer / npm / npx found" -ForegroundColor Green
    } else {
        $missing = @()
        if (-not $NodeOk) { $missing += "node" }
        if (-not $NpmOk)  { $missing += "npm"  }
        if (-not $NpxOk)  { $missing += "npx"  }
        Write-Host "[!] Missing: $($missing -join ', ')" -ForegroundColor Yellow
        Write-Host "    Install Node.js from https://nodejs.org/ (includes npm and npx)" -ForegroundColor Yellow
        Write-Host "    MCP npm scenarios will use config-only simulation fallback until Node.js is installed." -ForegroundColor Yellow
    }
}

# ── Virtual environment ───────────────────────────────────────────────────────
$VenvDir = Join-Path $env:USERPROFILE ".shadow-ai-simulator\venv"

if (-not (Test-Path "$VenvDir\Scripts\Activate.ps1") -or $RepairDeps) {
    Write-Host "[*] Creating virtual environment at $VenvDir"
    New-Item -ItemType Directory -Force -Path (Split-Path $VenvDir) | Out-Null
    & $pythonCmd -m venv $VenvDir
}

$VenvDir | Out-File -FilePath ".venv_path" -Encoding utf8
Write-Host "[OK] Virtual environment ready" -ForegroundColor Green

# ── Python dependencies ───────────────────────────────────────────────────────
& "$VenvDir\Scripts\Activate.ps1"
Write-Host "[*] Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
Write-Host "[OK] Python dependencies installed" -ForegroundColor Green

# ── Playwright Chromium ───────────────────────────────────────────────────────
Write-Host "[*] Installing Playwright Chromium..."
playwright install chromium
Write-Host "[OK] Playwright Chromium ready" -ForegroundColor Green

# ── Dependency report ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  -- Dependency Report --" -ForegroundColor Cyan

function Check-Cmd($name) {
    if (Get-Command $name -ErrorAction SilentlyContinue) {
        Write-Host "  [OK] $name" -ForegroundColor Green
    } else {
        Write-Host "  [X]  $name (not found)" -ForegroundColor Yellow
    }
}

Check-Cmd python
Check-Cmd pip
Check-Cmd curl
Check-Cmd node
Check-Cmd npm
Check-Cmd npx

try {
    $chromiumPath = & $pythonCmd -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()" 2>&1
    Write-Host "  [OK] playwright chromium: $chromiumPath" -ForegroundColor Green
} catch {
    Write-Host "  [X]  playwright chromium (not installed)" -ForegroundColor Yellow
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "  [OK] ollama" -ForegroundColor Green
} else {
    Write-Host "  [~]  ollama (optional — only needed for Ollama installer test)" -ForegroundColor DarkGray
}

Write-Host "  ----------------------" -ForegroundColor Cyan
Write-Host ""

# ── Dependency-check-only mode ────────────────────────────────────────────────
if ($DependencyCheck) {
    Write-Host "[OK] Dependency check complete. Exiting (--dependency-check mode)." -ForegroundColor Green
    exit 0
}

# ── Launch ────────────────────────────────────────────────────────────────────
Write-Host "[OK] Setup complete! Starting server..." -ForegroundColor Green
Write-Host "     Local URL : http://127.0.0.1:8766" -ForegroundColor Cyan
Write-Host "     Browser   : auto-open enabled on Windows desktop" -ForegroundColor Cyan
Write-Host "     Stop      : Ctrl+C" -ForegroundColor Cyan
Write-Host ""

if ($PassArgs) {
    & $pythonCmd main.py @PassArgs
} else {
    & $pythonCmd main.py
}
