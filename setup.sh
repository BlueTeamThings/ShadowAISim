#!/usr/bin/env bash
# Shadow AI Simulator — One-command setup & launch for Linux / macOS
# Headless-safe: never calls xdg-open or assumes a desktop session.
#
# Options:
#   --skip-system-deps   Skip curl / node / npm / npx system-package checks
#   --repair-deps        Re-run all dependency installs even if they exist
#   --dependency-check   Print dependency status and exit without launching
#   --open-browser       Auto-open browser after launch (requires desktop session)
#   --no-browser         Never auto-open browser
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

# ── Parse flags ──────────────────────────────────────────────────────────────
SKIP_SYSTEM_DEPS=0
REPAIR_DEPS=0
DEP_CHECK_ONLY=0
PASS_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --skip-system-deps)  SKIP_SYSTEM_DEPS=1 ;;
        --repair-deps)       REPAIR_DEPS=1 ;;
        --dependency-check)  DEP_CHECK_ONLY=1 ;;
        *)                   PASS_ARGS+=("$arg") ;;
    esac
done

# ── Detect OS / package manager ───────────────────────────────────────────────
detect_pm() {
    for pm in apt-get apt dnf yum pacman apk brew; do
        if command -v "$pm" &>/dev/null; then echo "$pm"; return; fi
    done
    echo "none"
}
PM=$(detect_pm)

install_pkg() {
    local pkg="$1"
    case "$PM" in
        apt-get|apt) sudo "$PM" install -y "$pkg" ;;
        dnf)         sudo dnf    install -y "$pkg" ;;
        yum)         sudo yum    install -y "$pkg" ;;
        pacman)      sudo pacman -S --noconfirm "$pkg" ;;
        apk)         sudo apk    add --no-cache "$pkg" ;;
        brew)        brew        install "$pkg" ;;
        *)           return 1 ;;
    esac
}

# ── Python check ─────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[ERROR] Python 3 not found. Install Python 3.9+ and re-run.${NC}"; exit 1
fi

PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MINOR" -lt 9 ]; then
    echo -e "${RED}[ERROR] Python 3.9+ required. Found 3.${PY_MINOR}.${NC}"; exit 1
fi
echo -e "${GREEN}[✓] Python 3.${PY_MINOR} found${NC}"

# ── System dependency checks ──────────────────────────────────────────────────
if [ "$SKIP_SYSTEM_DEPS" -eq 0 ]; then

    echo "[*] Checking system dependencies (package manager: ${PM})…"

    # ── curl ──────────────────────────────────────────────────────────────────
    if command -v curl &>/dev/null; then
        echo -e "${GREEN}[✓] curl found${NC}"
    elif [ "$PM" != "none" ]; then
        echo -e "${YELLOW}[!] curl not found — installing…${NC}"
        install_pkg curl && echo -e "${GREEN}[✓] curl installed${NC}" \
            || echo -e "${YELLOW}[!] curl install failed — Python urllib fallback will be used${NC}"
    else
        echo -e "${YELLOW}[!] curl not found and no package manager available — Python fallback will be used${NC}"
    fi

    # ── Node.js / npm / npx ───────────────────────────────────────────────────
    NODE_OK=0
    NPM_OK=0
    NPX_OK=0
    command -v node &>/dev/null && NODE_OK=1
    command -v npm  &>/dev/null && NPM_OK=1
    command -v npx  &>/dev/null && NPX_OK=1

    if [ "$NODE_OK" -eq 1 ] && [ "$NPM_OK" -eq 1 ] && [ "$NPX_OK" -eq 1 ]; then
        NODE_VER=$(node --version 2>/dev/null || echo "?")
        echo -e "${GREEN}[✓] node ${NODE_VER} / npm / npx found${NC}"
    else
        MISSING=""
        [ "$NODE_OK" -eq 0 ] && MISSING="$MISSING node"
        [ "$NPM_OK"  -eq 0 ] && MISSING="$MISSING npm"
        [ "$NPX_OK"  -eq 0 ] && MISSING="$MISSING npx"
        echo -e "${YELLOW}[!] Missing Node.js tools:${MISSING}${NC}"

        if [ "$PM" != "none" ]; then
            echo -e "${YELLOW}[!] Installing Node.js…${NC}"
            case "$PM" in
                apt-get|apt) install_pkg nodejs && install_pkg npm ;;
                dnf|yum)     install_pkg nodejs && install_pkg npm ;;
                pacman)      install_pkg nodejs && install_pkg npm ;;
                apk)         install_pkg nodejs && install_pkg npm ;;
                brew)        install_pkg node ;;
            esac

            # Re-check after install
            command -v node &>/dev/null && NODE_OK=1 || true
            command -v npm  &>/dev/null && NPM_OK=1  || true
            command -v npx  &>/dev/null && NPX_OK=1  || true

            if [ "$NODE_OK" -eq 1 ] && [ "$NPM_OK" -eq 1 ]; then
                echo -e "${GREEN}[✓] Node.js installed${NC}"
                if [ "$NPX_OK" -eq 0 ]; then
                    npm install -g npx 2>/dev/null || true
                    command -v npx &>/dev/null && echo -e "${GREEN}[✓] npx installed${NC}"
                fi
            else
                echo -e "${YELLOW}[!] Node.js install did not complete — MCP npm scenarios will use config-only fallback${NC}"
            fi
        else
            echo -e "${YELLOW}[!] No package manager — install Node.js manually from https://nodejs.org/${NC}"
            echo -e "${YELLOW}    MCP npm scenarios will use config-only simulation fallback${NC}"
        fi
    fi

fi  # end SKIP_SYSTEM_DEPS

# ── Virtual environment ──────────────────────────────────────────────────────
VENV_DIR="$HOME/.shadow-ai-simulator/venv"

_install_venv_pkg() {
    echo -e "${YELLOW}[!] Installing python3-venv…${NC}"
    if   command -v apt-get &>/dev/null; then sudo apt-get install -y python3-venv python3-pip
    elif command -v dnf     &>/dev/null; then sudo dnf     install -y python3 python3-pip
    elif command -v yum     &>/dev/null; then sudo yum     install -y python3 python3-pip
    elif command -v pacman  &>/dev/null; then sudo pacman  -S --noconfirm python python-pip
    elif command -v apk     &>/dev/null; then sudo apk     add --no-cache python3 py3-pip
    else echo -e "${RED}[ERROR] Cannot auto-install python3-venv. Install it manually.${NC}"; exit 1
    fi
}

if [ ! -f "$VENV_DIR/bin/activate" ] || [ "$REPAIR_DEPS" -eq 1 ]; then
    echo "[*] Creating virtual environment at $VENV_DIR"
    mkdir -p "$HOME/.shadow-ai-simulator"
    if ! python3 -m venv "$VENV_DIR" 2>/tmp/venv_err; then
        _install_venv_pkg
        if ! python3 -m venv "$VENV_DIR"; then
            echo -e "${RED}[ERROR] Still failed to create venv.${NC}"; exit 1
        fi
    fi
fi

echo "$VENV_DIR" > .venv_path
echo -e "${GREEN}[✓] Virtual environment ready${NC}"

# ── Python dependencies ───────────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"
echo "[*] Installing Python dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo -e "${GREEN}[✓] Python dependencies installed${NC}"

# ── Playwright Chromium ───────────────────────────────────────────────────────
if [ "$SKIP_SYSTEM_DEPS" -eq 0 ]; then
    echo "[*] Installing Playwright Chromium OS dependencies…"
    python3 -m playwright install-deps chromium 2>/dev/null \
        && echo -e "${GREEN}[✓] Playwright OS deps installed${NC}" \
        || echo -e "${YELLOW}[!] playwright install-deps skipped (may need sudo — run manually if browser launch fails)${NC}"
fi

echo "[*] Installing Playwright Chromium browser…"
python3 -m playwright install chromium \
    && echo -e "${GREEN}[✓] Playwright Chromium ready${NC}" \
    || { echo -e "${RED}[ERROR] Playwright Chromium install failed.${NC}"; exit 1; }

# ── Dependency report ─────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ── Dependency Report ─────────────────────────────────${NC}"
_check() { command -v "$1" &>/dev/null && echo -e "  ${GREEN}[✓] $1${NC}" || echo -e "  ${YELLOW}[✗] $1 (not found)${NC}"; }
_check python3
_check pip
_check curl
_check node
_check npm
_check npx
python3 -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); ok=p.chromium.executable_path; p.stop(); print('  \033[0;32m[✓] playwright chromium: ' + ok + '\033[0m')" 2>/dev/null \
    || echo -e "  ${YELLOW}[✗] playwright chromium (not installed)${NC}"
command -v ollama &>/dev/null && echo -e "  ${GREEN}[✓] ollama${NC}" || echo -e "  ${YELLOW}[✗] ollama (optional — only needed for Ollama installer test)${NC}"
echo -e "${CYAN}  ──────────────────────────────────────────────────────${NC}"
echo ""

# ── Dependency-check-only mode ────────────────────────────────────────────────
if [ "$DEP_CHECK_ONLY" -eq 1 ]; then
    echo -e "${GREEN}[✓] Dependency check complete. Exiting (--dependency-check mode).${NC}"
    exit 0
fi

# ── Detect network IP ─────────────────────────────────────────────────────────
NETWORK_IP=$(python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    print('')
" 2>/dev/null)

# ── Launch ────────────────────────────────────────────────────────────────────
echo -e "${GREEN}[✓] Setup complete! Starting server…${NC}"
echo ""
echo "  --------------------------------------------------"
echo -e "  ${CYAN}Shadow AI Simulator${NC} — server starting"
echo -e "  Local URL   : ${CYAN}http://127.0.0.1:8766${NC}"
if [ -n "$NETWORK_IP" ] && [ "$NETWORK_IP" != "127.0.0.1" ]; then
    echo -e "  Network URL : ${CYAN}http://${NETWORK_IP}:8766${NC}"
fi
echo "  Browser     : will not auto-open (use --open-browser to enable)"
echo "  Stop        : Ctrl+C"
echo "  --------------------------------------------------"
echo ""
python3 main.py "${PASS_ARGS[@]}"
