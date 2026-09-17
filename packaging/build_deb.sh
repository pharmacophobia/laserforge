#!/usr/bin/env bash
# LaserForge Debian Package Builder (.deb)
# Packages LaserForge into a system-wide installable .deb package for Ubuntu, Debian, Mint, Pop!_OS
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build/deb"
DIST_DIR="${ROOT_DIR}/dist"
PKG_NAME="laserforge"
PKG_VER="1.2.0"
PKG_ARCH="amd64"
DEB_DIR="${BUILD_DIR}/${PKG_NAME}_${PKG_VER}_${PKG_ARCH}"

echo "========================================="
echo " Building LaserForge .deb Package v${PKG_VER}"
echo "========================================="

# Clean build directory
rm -rf "${DEB_DIR}"
mkdir -p "${DEB_DIR}/DEBIAN"
mkdir -p "${DEB_DIR}/opt/laserforge"
mkdir -p "${DEB_DIR}/usr/bin"
mkdir -p "${DEB_DIR}/usr/share/applications"
mkdir -p "${DEB_DIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${DIST_DIR}"

# 1. Copy Application Code & Assets
echo "--> Copying application files to /opt/laserforge..."
cp -r "${ROOT_DIR}/laserforge" "${DEB_DIR}/opt/laserforge/"
cp -r "${ROOT_DIR}/assets" "${DEB_DIR}/opt/laserforge/"
cp -r "${ROOT_DIR}/examples" "${DEB_DIR}/opt/laserforge/"
cp "${ROOT_DIR}/requirements.txt" "${DEB_DIR}/opt/laserforge/"
cp "${ROOT_DIR}/requirements-core.txt" "${DEB_DIR}/opt/laserforge/"
cp "${ROOT_DIR}/run.sh" "${DEB_DIR}/opt/laserforge/"
chmod +x "${DEB_DIR}/opt/laserforge/run.sh"

# Clean any pycache artifacts
find "${DEB_DIR}/opt/laserforge" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${DEB_DIR}/opt/laserforge" -name "*.pyc" -delete 2>/dev/null || true

# 2. Install Desktop Launcher & Icons
echo "--> Installing desktop entries and icons..."
cp "${ROOT_DIR}/assets/laserforge.png" "${DEB_DIR}/usr/share/icons/hicolor/256x256/apps/laserforge.png"

cat << 'EOF' > "${DEB_DIR}/usr/share/applications/laserforge.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=LaserForge
GenericName=Laser Engraver CAD/CAM
Comment=High-Performance LightBurn Alternative for Linux and GRBL Engravers
Exec=/usr/bin/laserforge %F
Icon=laserforge
Terminal=false
StartupNotify=true
Categories=Graphics;Engineering;2DGraphics;VectorGraphics;Manufacturing;
MimeType=application/x-laserproj;
Keywords=laser;lightburn;grbl;engraver;cad;cam;cutting;dxf;svg;
EOF
chmod 644 "${DEB_DIR}/usr/share/applications/laserforge.desktop"

# 3. Create /usr/bin/laserforge wrapper script
cat << 'EOF' > "${DEB_DIR}/usr/bin/laserforge"
#!/usr/bin/env bash
export PYTHONPATH="/opt/laserforge:${PYTHONPATH}"
cd /opt/laserforge
exec /opt/laserforge/run.sh "$@"
EOF
chmod 755 "${DEB_DIR}/usr/bin/laserforge"

# 4. Create DEBIAN/control file
cat << EOF > "${DEB_DIR}/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${PKG_VER}
Section: graphics
Priority: optional
Architecture: ${PKG_ARCH}
Depends: python3 (>= 3.9), python3-pip, python3-pyqt6 | python3, libgl1
Maintainer: LaserForge Developers <info@laserforge.org>
Homepage: https://github.com/laserforge/laserforge
Description: High-Performance LightBurn Alternative for Linux and GRBL Engravers
 LaserForge is a full-featured desktop laser engraving and cutting suite built natively
 for Linux. Includes 2D CAD canvas, multi-layer CAM processing, vector booleans (CSG),
 directional vector hatching, 2D nesting optimization, rotary roller & chuck studio,
 OpenCV camera bed vision, Floyd-Steinberg photo dithering, and real-time USB GRBL control.
EOF

# 5. Create DEBIAN/postinst script
cat << 'EOF' > "${DEB_DIR}/DEBIAN/postinst"
#!/usr/bin/env bash
set -e

# Add desktop database cache update
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi

# Update icon cache
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi

echo "========================================================="
echo " LaserForge installed successfully!"
echo " Launch from application menu or run 'laserforge' in terminal."
echo " Ensure your user belongs to dialout group: sudo usermod -aG dialout \$USER"
echo "========================================================="
EOF
chmod 755 "${DEB_DIR}/DEBIAN/postinst"

# 6. Build the .deb package
echo "--> Compiling package with dpkg-deb..."
dpkg-deb --build --root-owner-group "${DEB_DIR}" "${DIST_DIR}/${PKG_NAME}_${PKG_VER}_${PKG_ARCH}.deb"

echo "========================================="
echo " Package successfully built!"
echo " Location: ${DIST_DIR}/${PKG_NAME}_${PKG_VER}_${PKG_ARCH}.deb"
echo " Install with: sudo dpkg -i ${DIST_DIR}/${PKG_NAME}_${PKG_VER}_${PKG_ARCH}.deb"
echo "========================================="
