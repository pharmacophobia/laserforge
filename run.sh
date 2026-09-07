#!/usr/bin/env bash
# LaserForge Launcher Script
# High-Performance LightBurn Alternative for Linux and GRBL Engravers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

# Ensure user has access to serial dialout
if ! groups | grep -q "\bdialout\b"; then
    echo "[LaserForge Warning] Current user is not in the 'dialout' group."
    echo "To access /dev/ttyUSB0 without root, run: sudo usermod -aG dialout $USER (then re-login)"
fi

exec python3 -m laserforge.main "$@"
