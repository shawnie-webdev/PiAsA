#!/usr/bin/env bash
set -Eeuo pipefail

# System-wide PiAsA installer.
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${PIASA_HOME:-/opt/piasa}"
BIN_DIR="${PIASA_BIN_DIR:-/usr/local/bin}"
VENV_DIR="$APP_DIR/venv"
PYTHON="${PYTHON:-python3}"

say() { printf 'PiAsA: %s\\n' "$*"; }
die() { printf 'PiAsA: error: %s\\n' "$*" >&2; exit 1; }

run_root() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
PiAsA installer

Usage:
  bash install.sh           Install/update PiAsA system-wide
  bash install.sh --uninstall
  bash install.sh --help

The virtual environment is installed in /opt/piasa and the command is
installed in /usr/local/bin, so 'piasa' also works through sudo.

Optional environment variables:
  PYTHON        Python executable (default: python3)
  PIASA_HOME    Installation directory (default: /opt/piasa)
  PIASA_BIN_DIR Command directory (default: /usr/local/bin)
EOF
    exit 0
fi

if [[ "${1:-}" == "--uninstall" ]]; then
    command -v sudo >/dev/null 2>&1 || [[ "$EUID" -eq 0 ]] || die "sudo is required to uninstall system-wide PiAsA."
    run_root rm -f "$BIN_DIR/piasa"
    run_root rm -rf "$APP_DIR"
    say "removed PiAsA from $APP_DIR"
    say "user configuration in ~/.config/piasa was left untouched"
    exit 0
fi

command -v "$PYTHON" >/dev/null 2>&1 || die "Python 3 was not found. Install python3 first."
PYTHON_BIN="$(command -v "$PYTHON")"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null || die "PiAsA requires Python 3.9 or newer."
"$PYTHON_BIN" -m venv --help >/dev/null 2>&1 || die "Python venv support is missing. On Debian/Raspberry Pi OS, install it with: sudo apt install python3-venv"
command -v sudo >/dev/null 2>&1 || [[ "$EUID" -eq 0 ]] || die "sudo is required for a system-wide installation."

say "creating isolated environment at $VENV_DIR"
run_root mkdir -p "$APP_DIR" "$BIN_DIR"
run_root "$PYTHON_BIN" -m venv "$VENV_DIR"

say "installing PiAsA into its system-wide virtual environment"
run_root "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools
run_root "$VENV_DIR/bin/python" -m pip install "$ROOT_DIR"

run_root ln -sfn "$VENV_DIR/bin/piasa" "$BIN_DIR/piasa"

say "installation complete"
say "command: $BIN_DIR/piasa"
say "try: piasa --help"
say "the command is available to both your user and sudo."
