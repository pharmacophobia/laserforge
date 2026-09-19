#!/usr/bin/env bash
# LaserForge Linux System & Desktop Installer
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
DESKTOP_DIR="${HOME}/Desktop"

echo "========================================="
echo " LaserForge Desktop & System Installer"
echo "========================================="

# 1. Ensure dialout permissions for USB GRBL lasers
if ! groups | grep -q "\bdialout\b"; then
    echo "--> Adding $USER to 'dialout' group for USB serial access..."
    sudo usermod -aG dialout "$USER" || echo "[Warning] Could not run sudo. Run 'sudo usermod -aG dialout $USER' manually."
else
    echo "--> User $USER is already in 'dialout' group."
fi

# 2. Register Application Icon
echo "--> Installing desktop icons..."
mkdir -p "${ICONS_DIR}"
cp "${SCRIPT_DIR}/assets/laserforge.png" "${ICONS_DIR}/laserforge.png"

# 3. Create Start Menu Application Entry
echo "--> Registering Start Menu application launcher..."
mkdir -p "${APPS_DIR}"
cat << EOF > "${APPS_DIR}/laserforge.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=LaserForge
GenericName=Laser Engraver CAD/CAM
Comment=High-Performance LightBurn Alternative for Linux and GRBL Engravers
Exec=${SCRIPT_DIR}/run.sh %F
Icon=${ICONS_DIR}/laserforge.png
Path=${SCRIPT_DIR}
Terminal=false
StartupNotify=true
Categories=Graphics;Engineering;2DGraphics;VectorGraphics;
MimeType=application/x-laserproj;
Keywords=laser;lightburn;grbl;engraver;cad;cam;cutting;dxf;svg;
EOF
chmod +x "${APPS_DIR}/laserforge.desktop"

# 4. Create Desktop Shortcut (if ~/Desktop exists)
if [ -d "${DESKTOP_DIR}" ]; then
    echo "--> Creating Desktop shortcut..."
    cp "${APPS_DIR}/laserforge.desktop" "${DESKTOP_DIR}/laserforge.desktop"
    chmod +x "${DESKTOP_DIR}/laserforge.desktop"
    if command -v gio >/dev/null 2>&1; then
        gio set "${DESKTOP_DIR}/laserforge.desktop" metadata::trusted true 2>/dev/null || true
    fi
fi

# 5. Update FreeDesktop database cache
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" || true
fi

echo "========================================="
echo " Installation Complete! 🚀"
echo " You can now launch LaserForge from your Application Menu"
echo " or directly from your Desktop."
echo "========================================="

# 6. Optional Interactive Tutorial Onboarding
if [ -t 0 ]; then
    echo ""
    read -r -p "Would you like to launch LaserForge with the Interactive Tutorial now? [Y/n] " launch_tut
    launch_tut=${launch_tut:-Y}
    if [[ "$launch_tut" =~ ^[Yy]$ ]]; then
        echo "--> Launching LaserForge Interactive Tutorial..."
        "${SCRIPT_DIR}/run.sh" --tutorial &
    fi
fi
