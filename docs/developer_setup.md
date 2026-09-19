# LaserForge Developer & Contributor Setup Guide

Welcome to the LaserForge development guide. This document covers setting up your local development environment, running test suites, working with the virtual GRBL simulator, and executing release checks.

---

## 1. Prerequisites

- **Operating System**: Linux (Ubuntu 22.04+, Debian 12+, Arch, Fedora 38+)
- **Python**: Python 3.10, 3.11, 3.12, or 3.13
- **Qt Dependencies**: PyQt6 and OpenGL libraries

System dependencies (Ubuntu/Debian):
```bash
sudo apt-get update
sudo apt-get install -y python3-dev python3-pip libgl1-mesa-glx libxcb-cursor0
```

Grant standard USB serial permissions (dialout):
```bash
sudo usermod -aG dialout $USER
# Log out and log back in for permissions to take effect
```

---

## 2. Quick Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/laserforge/laserforge.git
cd laserforge

# Option A: Core dependencies (fast setup without camera computer vision)
pip install -r requirements-core.txt

# Option B: Full development dependencies (including OpenCV camera vision & test tools)
pip install -r requirements.txt
pip install pytest pytest-cov pre-commit
```

Install git pre-commit hooks:
```bash
pre-commit install
```

---

## 3. Running LaserForge

### Normal Mode
```bash
./run.sh
# or
python3 -m laserforge.main
```

### Headless & Hardware-Free Simulation Mode
You can test LaserForge without a physical laser machine connected. LaserForge includes an in-memory `VirtualGrblSerial` controller simulating GRBL 1.1f motion responses, status telemetry, alarms, and overrides.

In LaserForge, select **Port** -> **`VIRTUAL_GRBL`** to connect to the internal loopback simulator.

---

## 4. Running Verification & Test Suites

The repository contains an automated suite of unit, integration, and regression tests.

### Run All Tests via unittest:
```bash
make test
# or
python3 -m unittest discover tests -q
```

### Run All Tests via pytest:
```bash
pytest
```

### Quick Syntax & Lint Check:
```bash
make lint
```

### Full Pre-Flight CI Check:
```bash
make check
```

---

## 5. Key Architecture & File Layout

- [`laserforge/core/`](file:///home/k/LaserForge/laserforge/core/): Computational CAD/CAM algorithms, G-code emission, serial drivers, dithering, and nesting.
- [`laserforge/ui/`](file:///home/k/LaserForge/laserforge/ui/): PyQt6 presentation layer, CAD canvas scenes, toolbars, and studio dialogs.
- [`laserforge/config.py`](file:///home/k/LaserForge/laserforge/config.py): Machine profiles, layer defaults, and configuration models.
- [`tests/`](file:///home/k/LaserForge/tests/): 280+ test cases covering geometry, CAM, dithering, and machine drivers.
- [`ARCHITECTURE.md`](file:///home/k/LaserForge/ARCHITECTURE.md): Full technical architecture and system design specification.
- [`CHANGELOG.md`](file:///home/k/LaserForge/CHANGELOG.md): Release notes and feature history.

---

## 6. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LASERFORGE_LICENSE_SALT` | *(internal)* | Production secret salt for signing commercial license keys. Must be set in production vendor builds. |
| `LASERFORGE_HEADLESS` | `0` | Run without opening Qt display (used for CI pipelines). |
| `QT_QPA_PLATFORM` | `xcb` | Qt platform plugin (`xcb`, `wayland`, or `offscreen`). |
