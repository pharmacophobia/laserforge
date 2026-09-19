"""
LaserForge Plugin API.
Provides a minimal, stable extension point for third-party LaserForge plugins.
Plugins are discovered from ~/.laserforge/plugins/ directory.
Each plugin lives in its own subdirectory and exposes a PLUGIN_CLASS attribute.
"""

import os
import importlib.util
from typing import List, Dict, Any, Callable, Optional, Type
from dataclasses import dataclass, field
import warnings


@dataclass
class PluginMetadata:
    """Descriptive metadata for a LaserForge plugin."""
    name: str
    version: str = '1.0.0'
    author: str = 'Unknown'
    description: str = ''
    api_version: str = '1.0'


class LaserForgePlugin:
    """
    Base class for all LaserForge plugins.
    Subclass and implement only the hooks you need.
    Place your plugin at ~/.laserforge/plugins/<name>/plugin.py
    and set PLUGIN_CLASS = YourPluginClass at module level.
    """
    metadata: PluginMetadata = PluginMetadata(name='UnnamedPlugin')

    def on_load(self, app_context: Dict[str, Any]) -> None:
        """
        Called when the plugin is loaded. app_context provides references to core subsystems:

        Keys available in app_context:
          'settings': MachineSettings — current machine configuration
          'layer_manager': LayerManager — layer/cut settings manager
          'scene': LaserCanvasScene — the 2D CAD canvas scene
          'serial': SerialController — GRBL serial connection manager
          'gcode_generator': GCodeGenerator — CAM G-code compiler
          'main_window': QMainWindow — the application main window (when GUI is active)

        Store any references you need: self.settings = app_context.get('settings')
        Do NOT hold strong references to UI widgets that may be destroyed.
        """

    def on_unload(self) -> None:
        """Called when the plugin is unloaded or the app exits."""

    def register_gcode_postprocessor(self) -> Optional[Callable[[str], str]]:
        """Return a callable(gcode: str) -> str, or None."""
        return None

    def register_import_handler(self) -> Optional[Dict[str, Any]]:
        """Return {'extensions': ['.ext'], 'handler': callable} or None."""
        return None

    def register_export_handler(self) -> Optional[Dict[str, Any]]:
        """Return {'extension': '.ext', 'label': 'Format Name', 'handler': callable} or None."""
        return None

    def register_canvas_tool(self) -> Optional[Dict[str, Any]]:
        """
        Return a dict defining a custom canvas drawing tool, or None.
        Dict keys:
          'tool_id': str — unique identifier (e.g. 'my_plugin.spiral_tool')
          'label': str — display name in toolbar
          'tooltip': str
          'cursor': str — cursor type ('crosshair', 'default', 'pencil')
          'on_mouse_press': callable(scene_x: float, scene_y: float) -> None
          'on_mouse_move': callable(scene_x: float, scene_y: float) -> None
          'on_mouse_release': callable(scene_x: float, scene_y: float) -> None
        Returns None if not providing a tool.
        """
        return None

    def register_layer_panel_widget(self) -> Optional[Any]:
        """
        Return a QWidget subclass instance to inject into the Cuts/Layers
        panel as an additional tab, or None.
        The widget will be added as a tab labeled with plugin.metadata.name.
        Returns None if not providing a widget.
        """
        return None

    def on_job_start(self, gcode: str, estimated_time_sec: float) -> None:
        """Called immediately before a laser job begins streaming. gcode is the full G-code string."""

    def on_job_complete(self, duration_sec: float, was_aborted: bool) -> None:
        """Called when a laser job finishes (normally or via emergency stop)."""

    def on_job_progress(self, lines_sent: int, lines_total: int, pct: float) -> None:
        """Called periodically during streaming to report progress. pct is 0.0-100.0."""


class PluginRegistry:
    """Discovers, loads, and manages LaserForge plugins from the plugin directory."""

    PLUGIN_DIR: str = os.path.expanduser('~/.laserforge/plugins')
    API_VERSION: str = '1.0'

    def __init__(self):
        self._plugins: Dict[str, LaserForgePlugin] = {}
        self._gcode_postprocessors: List[Callable[[str], str]] = []
        self._import_handlers: Dict[str, Callable] = {}
        self._export_handlers: Dict[str, Dict[str, Any]] = {}
        self._canvas_tools: List[Dict[str, Any]] = []
        self._layer_widgets: List[Any] = []

    def discover_and_load(self, app_context: Dict[str, Any]) -> List[str]:
        """Scans plugin directory and loads all valid plugins. Returns list of loaded plugin names."""
        loaded: List[str] = []
        if not os.path.isdir(self.PLUGIN_DIR):
            return loaded
        for entry in os.scandir(self.PLUGIN_DIR):
            if entry.is_dir():
                plugin_file = os.path.join(entry.path, 'plugin.py')
                if os.path.isfile(plugin_file):
                    name = self._load_plugin_file(entry.name, plugin_file, app_context)
                    if name:
                        loaded.append(name)
        return loaded

    def _load_plugin_file(self, dir_name: str, plugin_file: str, app_context: Dict[str, Any]) -> Optional[str]:
        try:
            spec = importlib.util.spec_from_file_location(f'laserforge_plugin_{dir_name}', plugin_file)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            plugin_cls: Type[LaserForgePlugin] = getattr(module, 'PLUGIN_CLASS', None)
            if plugin_cls is None or not issubclass(plugin_cls, LaserForgePlugin):
                warnings.warn(f'[LaserForge] Plugin {dir_name}: no valid PLUGIN_CLASS found', RuntimeWarning)
                return None
            plugin = plugin_cls()
            plugin.on_load(app_context)
            self._plugins[plugin.metadata.name] = plugin

            pp = plugin.register_gcode_postprocessor()
            if callable(pp):
                self._gcode_postprocessors.append(pp)

            ih = plugin.register_import_handler()
            if ih and 'handler' in ih:
                for ext in ih.get('extensions', []):
                    self._import_handlers[ext.lower().lstrip('.')] = ih['handler']

            eh = plugin.register_export_handler()
            if eh and 'extension' in eh:
                self._export_handlers[eh['extension'].lower().lstrip('.')] = eh

            tool = plugin.register_canvas_tool()
            if tool and isinstance(tool, dict):
                self._canvas_tools.append(tool)

            widget = plugin.register_layer_panel_widget()
            if widget is not None:
                self._layer_widgets.append((plugin.metadata.name, widget))

            return plugin.metadata.name
        except Exception as e:
            warnings.warn(f'[LaserForge] Failed to load plugin from {plugin_file}: {e}', RuntimeWarning)
            return None

    def apply_gcode_postprocessors(self, gcode: str) -> str:
        """Runs G-code through all registered post-processors in registration order."""
        for fn in self._gcode_postprocessors:
            try:
                gcode = fn(gcode)
            except Exception as e:
                warnings.warn(f'[LaserForge] G-code postprocessor error: {e}', RuntimeWarning)
        return gcode

    def get_import_handler(self, extension: str) -> Optional[Callable]:
        """Returns the import handler for the given file extension, or None."""
        return self._import_handlers.get(extension.lower().lstrip('.'))

    def get_export_handler(self, extension: str) -> Optional[Dict[str, Any]]:
        """Returns the export handler dict for the given file extension, or None."""
        return self._export_handlers.get(extension.lower().lstrip('.'))

    def get_canvas_tools(self) -> List[Dict[str, Any]]:
        """Returns registered custom canvas tools."""
        return list(self._canvas_tools)

    def get_layer_widgets(self) -> List[Any]:
        """Returns registered custom layer panel tabs/widgets."""
        return list(self._layer_widgets)

    def dispatch_job_start(self, gcode: str, estimated_time_sec: float) -> None:
        """Dispatches job start event to all active plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_job_start(gcode, estimated_time_sec)
            except Exception as e:
                warnings.warn(f'[LaserForge] Plugin {plugin.metadata.name} error in on_job_start: {e}', RuntimeWarning)

    def dispatch_job_complete(self, duration_sec: float, was_aborted: bool) -> None:
        """Dispatches job completion event to all active plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_job_complete(duration_sec, was_aborted)
            except Exception as e:
                warnings.warn(f'[LaserForge] Plugin {plugin.metadata.name} error in on_job_complete: {e}', RuntimeWarning)

    def dispatch_job_progress(self, lines_sent: int, lines_total: int, pct: float) -> None:
        """Dispatches job progress event to all active plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_job_progress(lines_sent, lines_total, pct)
            except Exception as e:
                warnings.warn(f'[LaserForge] Plugin {plugin.metadata.name} error in on_job_progress: {e}', RuntimeWarning)

    def list_plugins(self) -> List[str]:
        """Returns the names of all currently loaded plugins."""
        return list(self._plugins.keys())

    def unload_all(self) -> None:
        """Calls on_unload() on all plugins and clears the registry."""
        for plugin in self._plugins.values():
            try:
                plugin.on_unload()
            except Exception as e:
                warnings.warn(f'[LaserForge] Error unloading plugin {plugin.metadata.name!r}: {e}', RuntimeWarning)
        self._plugins.clear()
        self._gcode_postprocessors.clear()
        self._import_handlers.clear()
        self._export_handlers.clear()
        self._canvas_tools.clear()
        self._layer_widgets.clear()


_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Returns the global PluginRegistry singleton."""
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry
