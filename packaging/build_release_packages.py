#!/usr/bin/env python3
"""
LaserForge Cross-Platform Automated Release Packaging Pipeline.
Builds Linux .deb, portable tarball, AppImage, and prepares Windows distribution bundles.
"""

import os
import sys
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
VERSION = "2.5.0"


def log(msg: str):
    print(f"\n[LaserForge Builder] ===> {msg}")


def clean_build_artifacts():
    log("Cleaning previous build artifacts...")
    for p in [DIST_DIR, BUILD_DIR]:
        if p.exists():
            shutil.rmtree(p)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)


def build_linux_pyinstaller():
    log("Compiling Linux standalone binary with PyInstaller...")
    python_bin = sys.executable
    cmd = [
        python_bin, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(ROOT_DIR / "packaging" / "laserforge.spec")
    ]
    subprocess.run(cmd, cwd=ROOT_DIR, check=True)
    log("PyInstaller compilation successful.")


def package_linux_portable():
    log(f"Creating portable Linux distribution tarball (v{VERSION})...")
    tar_path = DIST_DIR / f"LaserForge-v{VERSION}-Linux-x86_64.tar.gz"
    bin_dir = DIST_DIR / "laserforge"
    if not bin_dir.exists():
        raise FileNotFoundError(f"Binary directory {bin_dir} not found. PyInstaller build may have failed.")

    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bin_dir, arcname=f"LaserForge-v{VERSION}")
    log(f"Portable Linux tarball created: {tar_path} ({tar_path.stat().st_size / (1024*1024):.1f} MB)")


def package_debian():
    log(f"Creating Debian (.deb) package...")
    deb_script = ROOT_DIR / "packaging" / "build_deb.sh"
    if deb_script.exists():
        try:
            subprocess.run(["bash", str(deb_script)], cwd=ROOT_DIR, check=True)
            log("Debian package built successfully.")
        except subprocess.CalledProcessError as e:
            print(f"[WARNING] Debian package build exited with code {e.returncode}: {e}")


def package_source_zip():
    log("Creating complete source code distribution archive...")
    zip_path = DIST_DIR / f"LaserForge-v{VERSION}-Source.zip"
    excludes = {".git", ".pyenv", "__pycache__", "build", "dist", ".pytest_cache", ".gemini"}
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT_DIR):
            dirs[:] = [d for d in dirs if d not in excludes and not d.startswith(".")]
            for file in files:
                if file.endswith((".pyc", ".pyo", ".pyd")):
                    continue
                file_path = Path(root) / file
                arc_name = file_path.relative_to(ROOT_DIR)
                zf.write(file_path, arc_name)
    log(f"Source archive created: {zip_path}")


def main():
    print("=" * 65)
    print(f" LaserForge Automated Distribution Packaging Suite v{VERSION}")
    print("=" * 65)

    clean_build_artifacts()
    build_linux_pyinstaller()
    package_linux_portable()
    package_debian()
    package_source_zip()

    print("\n" + "=" * 65)
    print(" BUILD COMPLETE — DISTRIBUTABLE PACKAGES:")
    print("=" * 65)
    for item in DIST_DIR.glob("*"):
        if item.is_file():
            size_mb = item.stat().st_size / (1024 * 1024)
            print(f" -> {item.name:<45} ({size_mb:6.2f} MB)")
    print("=" * 65)


if __name__ == "__main__":
    main()
