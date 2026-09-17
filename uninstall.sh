#!/usr/bin/env bash
# LaserForge Linux Desktop Uninstaller
set -e

APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
DESKTOP_DIR="${HOME}/Desktop"

echo "========================================="
echo " Uninstalling LaserForge Desktop Shortcuts"
echo "========================================="

rm -f "${APPS_DIR}/laserforge.desktop"
rm -f "${DESKTOP_DIR}/laserforge.desktop"
rm -f "${ICONS_DIR}/laserforge.png"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" || true
fi

echo "LaserForge shortcuts successfully removed."
