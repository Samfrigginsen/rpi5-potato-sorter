#!/usr/bin/env bash
# =============================================================================
# setup.sh — Automated Raspberry Pi OS Setup for PotatoSort AI Sorter
# Target:  Raspberry Pi 5 running Raspberry Pi OS (Bookworm 64-bit)
# Usage:   chmod +x setup.sh && ./setup.sh
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }

echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  PotatoSort AI — Raspberry Pi 5 Setup Script${RESET}"
echo -e "${BOLD}  Target: Raspberry Pi OS (Bookworm 64-bit)${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo ""

# ── Guard: must not run as root directly (sudo is invoked internally) ─────────
if [[ "$EUID" -eq 0 ]]; then
  error "Do not run this script as root. Run as a normal user: ./setup.sh"
fi

# ── Detect Pi ─────────────────────────────────────────────────────────────────
if ! grep -qi "raspberry\|bcm2" /proc/cpuinfo 2>/dev/null; then
  warn "This machine does not appear to be a Raspberry Pi."
  warn "The script will continue, but hardware-specific packages may fail."
  echo ""
fi

# ── Variables ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/env"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
MODELS_DIR="$SCRIPT_DIR/models"

info "Project directory: $SCRIPT_DIR"
info "Virtual environment: $VENV_DIR"

# =============================================================================
# STEP 1 — apt update + system package installation
# =============================================================================
echo ""
echo -e "${BOLD}── Step 1: System package installation ──────────────────${RESET}"

sudo apt-get update -y
sudo apt-get upgrade -y --no-install-recommends

# Core Python packages (system-level, needed for picamera2 / lgpio)
SYSTEM_PKGS=(
  python3-picamera2
  python3-opencv
  python3-lgpio
  python3-pip
  python3-venv
  libgl1
  libglib2.0-0
  libsm6
  libxrender1
  libxext6
  git
)

info "Installing system packages: ${SYSTEM_PKGS[*]}"
sudo apt-get install -y --no-install-recommends "${SYSTEM_PKGS[@]}"
success "System packages installed"

# =============================================================================
# STEP 2 — Add current user to dialout group (serial port access)
# =============================================================================
echo ""
echo -e "${BOLD}── Step 2: Serial port access (dialout group) ───────────${RESET}"

CURRENT_USER="${SUDO_USER:-$USER}"
if groups "$CURRENT_USER" | grep -q dialout; then
  success "User '$CURRENT_USER' is already in the dialout group"
else
  sudo usermod -aG dialout "$CURRENT_USER"
  success "User '$CURRENT_USER' added to dialout group"
  warn "You must log out and back in (or reboot) for group change to take effect"
fi

# =============================================================================
# STEP 3 — Python virtual environment with system-site-packages
# =============================================================================
echo ""
echo -e "${BOLD}── Step 3: Python virtual environment ───────────────────${RESET}"

if [[ -d "$VENV_DIR" ]]; then
  warn "Virtual environment already exists at $VENV_DIR"
  warn "To rebuild it, delete the directory and rerun: rm -rf $VENV_DIR"
else
  info "Creating virtual environment (--system-site-packages)…"
  # --system-site-packages allows access to system-installed picamera2 / lgpio
  python3 -m venv --system-site-packages "$VENV_DIR"
  success "Virtual environment created at $VENV_DIR"
fi

# ── Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
success "Virtual environment activated"

# =============================================================================
# STEP 4 — pip dependency installation from requirements.txt
# =============================================================================
echo ""
echo -e "${BOLD}── Step 4: pip install from requirements.txt ────────────${RESET}"

if [[ ! -f "$REQUIREMENTS" ]]; then
  error "requirements.txt not found at $REQUIREMENTS"
fi

pip install --upgrade pip wheel setuptools
info "Installing Python dependencies…"
pip install -r "$REQUIREMENTS"
success "Python dependencies installed"

# =============================================================================
# STEP 5 — Create models directory if absent
# =============================================================================
echo ""
echo -e "${BOLD}── Step 5: Model directory ──────────────────────────────${RESET}"

if [[ ! -d "$MODELS_DIR" ]]; then
  mkdir -p "$MODELS_DIR"
  success "Created models/ directory at $MODELS_DIR"
else
  success "models/ directory already exists"
fi

ONNX_MODEL="$MODELS_DIR/potato_yolov8n_cls.onnx"
if [[ ! -f "$ONNX_MODEL" ]]; then
  warn "ONNX model NOT found at $ONNX_MODEL"
  warn "The application will run in SIMULATION MODE until the model is placed there."
  warn "Export your model: python3 -c \"from ultralytics import YOLO; YOLO('best.pt').export(format='onnx', imgsz=224)\""
  warn "Then: cp yolov8n-cls.onnx $ONNX_MODEL"
else
  success "ONNX model found: $ONNX_MODEL"
fi

# =============================================================================
# STEP 6 — Enable camera interface (raspi-config non-interactive)
# =============================================================================
echo ""
echo -e "${BOLD}── Step 6: Camera interface ─────────────────────────────${RESET}"

if command -v raspi-config &>/dev/null; then
  # Enable camera via legacy interface (not needed for libcamera/picamera2,
  # but enables /dev/video0 via v4l2 as fallback)
  if sudo raspi-config nonint get_camera 2>/dev/null | grep -q "0"; then
    success "Camera interface already enabled"
  else
    sudo raspi-config nonint do_camera 0
    success "Camera interface enabled"
  fi
else
  warn "raspi-config not found — camera may already be enabled via /boot/config.txt"
fi

# ── Verify IMX219 is detected by libcamera ────────────────────────────────
if command -v libcamera-hello &>/dev/null; then
  info "Checking libcamera camera list…"
  if libcamera-hello --list-cameras 2>&1 | grep -qi "imx219\|camera"; then
    success "IMX219 camera detected by libcamera"
  else
    warn "IMX219 not listed by libcamera — check ribbon cable and config.txt"
    warn "Add to /boot/config.txt:  dtoverlay=imx219"
  fi
fi

# =============================================================================
# STEP 7 — Verify serial port
# =============================================================================
echo ""
echo -e "${BOLD}── Step 7: Serial port verification ─────────────────────${RESET}"

if ls /dev/ttyUSB* 2>/dev/null | head -1 | grep -q ttyUSB; then
  success "ESP32 serial device found: $(ls /dev/ttyUSB* 2>/dev/null | head -1)"
elif ls /dev/ttyACM* 2>/dev/null | head -1 | grep -q ttyACM; then
  success "ESP32 serial device found: $(ls /dev/ttyACM* 2>/dev/null | head -1)"
else
  warn "No /dev/ttyUSB* or /dev/ttyACM* found — serial bridge will use mock mode"
  warn "Connect your ESP32 via USB and re-check with: ls /dev/ttyUSB* /dev/ttyACM*"
fi

# =============================================================================
# STEP 8 — Run camera test
# =============================================================================
echo ""
echo -e "${BOLD}── Step 8: Camera self-test ─────────────────────────────${RESET}"

info "Running test_camera.py (headless, 30 frames)…"
if python3 "$SCRIPT_DIR/test_camera.py" --no-display --frames 30; then
  success "Camera test PASSED"
else
  warn "Camera test reported failures — check output above"
  warn "Application will run with synthetic frame fallback"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  Setup complete!${RESET}"
echo ""
echo -e "  To start the application:"
echo -e "    ${CYAN}source $VENV_DIR/bin/activate${RESET}"
echo -e "    ${CYAN}python3 $SCRIPT_DIR/app.py${RESET}"
echo ""
echo -e "  Dashboard will be available at:"
echo -e "    ${CYAN}http://$(hostname -I | awk '{print $1}'):5000${RESET}"
echo -e "    ${CYAN}http://localhost:5000${RESET}"
echo ""
if groups "$CURRENT_USER" | grep -q dialout; then
  : # no warning needed
else
  echo -e "  ${YELLOW}⚠ Remember to log out and back in for dialout group to take effect${RESET}"
fi
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
