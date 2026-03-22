#!/usr/bin/env bash
# Shadow AI Simulator — One-command setup & launch for Linux / macOS
set -e

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║       Shadow AI Simulator — Setup & Launch           ║"
echo "  ║       Red Team DLP / EDR Validation Toolkit          ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Python check ────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[ERROR] Python 3 not found. Install Python 3.9+ and re-run.${NC}"; exit 1
fi

PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MINOR" -lt 9 ]; then
    echo -e "${RED}[ERROR] Python 3.9+ required. Found 3.${PY_MINOR}.${NC}"; exit 1
fi
echo -e "${GREEN}[✓] Python 3.${PY_MINOR} found${NC}"

# ── Virtual environment ──────────────────────────────────────────────────────
# Stored in $HOME/.shadow-ai-simulator/venv to avoid hgfs/VMware symlink issues.
VENV_DIR="$HOME/.shadow-ai-simulator/venv"

_install_venv_pkg() {
    echo -e "${YELLOW}[!] Installing python3-venv…${NC}"
    if   command -v apt-get &>/dev/null; then sudo apt-get install -y python3-venv python3-pip
    elif command -v dnf     &>/dev/null; then sudo dnf     install -y python3 python3-pip
    elif command -v yum     &>/dev/null; then sudo yum     install -y python3 python3-pip
    elif command -v pacman  &>/dev/null; then sudo pacman  -S --noconfirm python python-pip
    else echo -e "${RED}[ERROR] Cannot auto-install python3-venv. Please install it manually.${NC}"; exit 1
    fi
}

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[*] Creating virtual environment at $VENV_DIR"
    mkdir -p "$HOME/.shadow-ai-simulator"
    if ! python3 -m venv "$VENV_DIR" 2>/tmp/venv_err; then
        _install_venv_pkg
        if ! python3 -m venv "$VENV_DIR"; then
            echo -e "${RED}[ERROR] Still failed to create venv. Check Python installation.${NC}"; exit 1
        fi
    fi
fi

# Save path for future runs
echo "$VENV_DIR" > .venv_path
echo -e "${GREEN}[✓] Virtual environment ready${NC}"

# ── Dependencies ─────────────────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"
echo "[*] Installing Python dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo -e "${GREEN}[✓] Dependencies installed${NC}"

# ── Playwright browsers ───────────────────────────────────────────────────────
echo "[*] Installing Playwright Chromium…"
playwright install chromium
echo -e "${GREEN}[✓] Playwright Chromium ready${NC}"

# ── Launch ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}[✓] Setup complete! Starting server…${NC}"
echo -e "    Open: ${CYAN}http://127.0.0.1:8766${NC}"
echo ""
python main.py
