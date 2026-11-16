#!/usr/bin/env bash
set -Eeuo pipefail

# PiAsA per-user installer. No sudo required.
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${PIASA_HOME:-$HOME/.local/share/piasa}"
BIN_DIR="${PIASA_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$APP_DIR/venv"
PYTHON="${PYTHON:-python3}"

say() { printf 'PiAsA: %s\n' "$*"; }
die() { printf 'PiAsA: error: %s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
PiAsA installer

Usage:
  ./install.sh           Install/update PiAsA for the current user
  ./install.sh --uninstall
  ./install.sh --help

Optional environment variables:
  PYTHON        Python executable (default: python3)
  PIASA_HOME    Installation directory (default: ~/.local/share/piasa)
  PIASA_BIN_DIR Command directory (default: ~/.local/bin)
EOF
    exit 0
fi

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$BIN_DIR/piasa"
    rm -rf "$APP_DIR"
    say "removed PiAsA from $APP_DIR"
    say "user configuration in ~/.config/piasa was left untouched"
    exit 0
fi

command -v "$PYTHON" >/dev/null 2>&1 || die "Python 3 was not found. Install python3 first."
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null || die "PiAsA requires Python 3.9 or newer."
"$PYTHON" -m venv --help >/dev/null 2>&1 || die "Python venv support is missing. On Debian/Raspberry Pi OS, install it with: sudo apt install python3-venv"

say "creating isolated environment at $VENV_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR"
"$PYTHON" -m venv "$VENV_DIR"

say "installing PiAsA into its virtual environment"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools
"$VENV_DIR/bin/python" -m pip install "$ROOT_DIR"

ln -sfn "$VENV_DIR/bin/piasa" "$BIN_DIR/piasa"

say "installation complete"
say "command: $BIN_DIR/piasa"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    say "$BIN_DIR is not currently in PATH. Add this to your shell profile:"
    printf '  export PATH="%s:$PATH"\n' "$BIN_DIR"
fi
say "try: piasa --help"
say "PiAsA is installed for your user; only gadget activation needs sudo."
