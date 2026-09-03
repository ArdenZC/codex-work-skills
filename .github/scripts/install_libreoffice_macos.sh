#!/usr/bin/env bash
set -euo pipefail

# The override keeps the fail-closed control flow testable without changing
# the production path used by macOS runners.
SOFFICE="${LIBREOFFICE_SOFFICE:-/Applications/LibreOffice.app/Contents/MacOS/soffice}"
SOFFICE_DIR="$(dirname "$SOFFICE")"

add_soffice_to_path() {
    if [[ -n "${GITHUB_PATH:-}" ]]; then
        printf '%s\n' "$SOFFICE_DIR" >> "$GITHUB_PATH"
    fi
}

verify_soffice() {
    if [[ ! -x "$SOFFICE" ]]; then
        echo "ERROR: LibreOffice command was not found: $SOFFICE" >&2
        return 1
    fi
    "$SOFFICE" --version
}

if [[ -x "$SOFFICE" ]]; then
    echo "LibreOffice is already available: $SOFFICE"
else
    echo "Refreshing Homebrew metadata before LibreOffice installation..."
    brew update-reset || true
    brew update

    if brew install --cask libreoffice; then
        echo "Installed LibreOffice from the fresh Homebrew cask."
    else
        echo "Fresh LibreOffice cask failed; trying libreoffice-still..."
        brew install --cask libreoffice-still
    fi
fi

verify_soffice
add_soffice_to_path
