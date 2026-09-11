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
# Configure PyTorch memory allocator to avoid fragmentation on 8GB VRAM
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export PYTORCH_ALLOC_CONF="expandable_segments:True"

# Auto-detect Python binary with PyTorch and CUDA support
PYTHON_BIN="python3"
if [ -x "/home/k/.pyenv/versions/3.10.13/bin/python" ]; then
    PYTHON_BIN="/home/k/.pyenv/versions/3.10.13/bin/python"
elif [ -x "$HOME/.pyenv/shims/python" ]; then
    PYTHON_BIN="$HOME/.pyenv/shims/python"
fi

exec "$PYTHON_BIN" -m laserforge.main "$@"
