"""
Shared pytest fixtures for LaserForge tests.
"""
import pytest

from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.serial_controller import VirtualGrblSerial


@pytest.fixture
def machine_settings():
    """Returns a default MachineSettings instance."""
    return MachineSettings()


@pytest.fixture
def layer_manager():
    """Returns a default LayerManager instance."""
    return LayerManager()


@pytest.fixture
def gcode_generator(machine_settings, layer_manager):
    """Returns a GCodeGenerator wired to default settings and layer manager."""
    return GCodeGenerator(machine_settings, layer_manager)


@pytest.fixture
def virtual_grbl():
    """Returns a VirtualGrblSerial and closes it after the test."""
    vg = VirtualGrblSerial()
    yield vg
    vg.close()


@pytest.fixture
def tmp_project_dir(tmp_path):
    """Returns a temporary directory for project files."""
    return tmp_path
