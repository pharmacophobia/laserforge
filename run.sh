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

# Auto-detect compatible Python binary
PYTHON_CANDIDATES=(
    "/home/k/.pyenv/versions/3.10.13/bin/python"
    "$HOME/.pyenv/shims/python"
    "python3"
)

PYTHON_BIN=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
        if "$candidate" -c "import PyQt6, ezdxf, shapely" >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi


exec "$PYTHON_BIN" -m laserforge.main "$@"
