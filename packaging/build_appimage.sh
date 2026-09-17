#!/usr/bin/env bash
# LaserForge AppImage & Portable Linux Builder
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build"
DIST_DIR="${ROOT_DIR}/dist"
APPDIR="${BUILD_DIR}/LaserForge.AppDir"

PYTHON_BIN="/home/k/.pyenv/versions/3.10.13/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

echo "========================================="
echo " Building LaserForge AppImage & Portable Bundle"
echo "========================================="

# 1. Build standalone binary with PyInstaller
echo "--> Compiling standalone binary with PyInstaller..."
cd "${ROOT_DIR}"
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "${SCRIPT_DIR}/laserforge.spec"

# 2. Assemble AppDir structure
echo "--> Assembling AppDir structure..."
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller bundle into AppDir
cp -r "${DIST_DIR}/laserforge/"* "${APPDIR}/usr/bin/"

# Copy icon and desktop file
cp "${ROOT_DIR}/assets/laserforge.png" "${APPDIR}/laserforge.png"
cp "${ROOT_DIR}/assets/laserforge.png" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/laserforge.png"

cat << 'EOF' > "${APPDIR}/laserforge.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=LaserForge
GenericName=Laser Engraver CAD/CAM
Comment=High-Performance LightBurn Alternative for Linux and GRBL Engravers
Exec=laserforge-bin %F
Icon=laserforge
Terminal=false
StartupNotify=true
Categories=Graphics;Engineering;2DGraphics;VectorGraphics;
MimeType=application/x-laserproj;
EOF
cp "${APPDIR}/laserforge.desktop" "${APPDIR}/usr/share/applications/"

# Create AppRun entry script
cat << 'EOF' > "${APPDIR}/AppRun"
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH}"
export QT_PLUGIN_PATH="${HERE}/usr/bin/PyQt6/Qt6/plugins"
export QML2_IMPORT_PATH="${HERE}/usr/bin/PyQt6/Qt6/qml"
exec "${HERE}/usr/bin/laserforge-bin" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

# 3. Create portable tar.gz bundle
echo "--> Creating portable tarball: ${DIST_DIR}/LaserForge-Linux-x86_64.tar.gz..."
cd "${DIST_DIR}"
tar -czf "LaserForge-Linux-x86_64.tar.gz" "laserforge"

# 4. Generate AppImage using appimagetool if available
echo "--> Checking for appimagetool..."
APPIMAGETOOL="${ROOT_DIR}/build/appimagetool"
if ! command -v appimagetool >/dev/null 2>&1 && [ ! -x "${APPIMAGETOOL}" ]; then
    echo "--> Downloading standalone appimagetool..."
    curl -fsSL -o "${APPIMAGETOOL}" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage || true
    if [ -f "${APPIMAGETOOL}" ]; then
        chmod +x "${APPIMAGETOOL}"
    fi
fi

if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL_CMD="appimagetool"
elif [ -x "${APPIMAGETOOL}" ]; then
    APPIMAGETOOL_CMD="${APPIMAGETOOL} --appimage-extract-and-run"
else
    APPIMAGETOOL_CMD=""
fi

if [ -n "${APPIMAGETOOL_CMD}" ]; then
    echo "--> Packaging AppImage..."
    ARCH=x86_64 ${APPIMAGETOOL_CMD} "${APPDIR}" "${DIST_DIR}/LaserForge-x86_64.AppImage" || true
fi

echo "========================================="
echo " Build Complete!"
if [ -f "${DIST_DIR}/LaserForge-x86_64.AppImage" ]; then
    echo " AppImage: ${DIST_DIR}/LaserForge-x86_64.AppImage"
fi
echo " Portable Tarball: ${DIST_DIR}/LaserForge-Linux-x86_64.tar.gz"
echo "========================================="
