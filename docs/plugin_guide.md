# LaserForge Plugin Developer Guide

LaserForge features an extensible, lightweight plugin architecture that allows developers to add custom G-code post-processors, specialized CAD drawing tools, custom import/export file handlers, UI panels, and job monitoring hooks without modifying core application code.

---

## 1. Directory Structure

LaserForge discovers plugins from the user application directory:
```
~/.laserforge/plugins/
└── <plugin_name>/
    ├── plugin.py           # Required: Main entry point
    └── metadata / assets   # Optional: Icons, presets, data files
```

Each plugin folder must contain a `plugin.py` file exposing a module-level attribute:
```python
PLUGIN_CLASS = YourPluginClass
```

---

## 2. The `LaserForgePlugin` Base Class

All plugins subclass `laserforge.core.plugin_api.LaserForgePlugin`:

```python
from laserforge.core.plugin_api import LaserForgePlugin, PluginMetadata

class MyCustomPlugin(LaserForgePlugin):
    metadata = PluginMetadata(
        name="My Custom Plugin",
        version="1.0.0",
        author="Your Name or Studio",
        description="Brief explanation of plugin capabilities",
        api_version="1.0"
    )

    def on_load(self, app_context: dict) -> None:
        """Called upon discovery and activation."""
        pass

    def on_unload(self) -> None:
        """Called when LaserForge closes or plugins are reloaded."""
        pass
```

---

## 3. Subsystem Access via `app_context`

During `on_load(app_context)`, LaserForge passes references to active application subsystems:

| Key | Type | Purpose |
|---|---|---|
| `settings` | `MachineSettings` | Read and modify machine travel bounds, speeds, laser power modes, and kinematics. |
| `layer_manager`| `LayerManager` | Inspect or configure laser cut layers (C00–C11), cut speeds, passes, and air assist. |
| `scene` | `LaserCanvasScene` | Query, insert, or manipulate 2D vector shapes and CAD canvas items. |
| `serial` | `SerialController` | Listen to live machine telemetry, send commands, or poll GRBL status. |
| `gcode_generator` | `GCodeGenerator` | Access CAM compilation parameters and toolpath vectorizers. |
| `main_window` | `QMainWindow` | Access primary Qt UI components and status bar (when running in GUI mode). |

---

## 4. Extension Hooks

### A. G-Code Post-Processor
Transform or inject commands into generated G-code before it is streamed or exported:

```python
def register_gcode_postprocessor(self):
    def postprocess(gcode: str) -> str:
        # Prepend exhaust delay or custom header
        return "M8 ; Force Air Assist\n" + gcode
    return postprocess
```

### B. Custom Import & Export Handlers
Register custom CAD/vector file format parsers or exporters:

```python
def register_import_handler(self):
    return {
        'extensions': ['.plt', '.hpgl'],
        'handler': self.import_hpgl_file  # callable(filepath) -> List[LaserEntity]
    }

def register_export_handler(self):
    return {
        'extension': '.cnc',
        'label': 'Custom CNC Format',
        'handler': self.export_custom_cnc  # callable(filepath, entities, settings)
    }
```

### C. Custom Canvas Drawing Tools
Inject interactive tools directly onto the 2D CAD canvas:

```python
def register_canvas_tool(self):
    return {
        'tool_id': 'my_spiral_tool',
        'label': 'Archimedean Spiral',
        'tooltip': 'Click and drag to draw a parametric laser spiral',
        'cursor': 'crosshair',
        'on_mouse_press': self.on_press,
        'on_mouse_move': self.on_move,
        'on_mouse_release': self.on_release,
    }
```

### D. Layer Panel Widgets
Add custom tabs into the Cuts/Layers dock widget:

```python
def register_layer_panel_widget(self):
    from PyQt6.QtWidgets import QLabel
    widget = QLabel("Custom Material Helper")
    return widget
```

### E. Job Lifecycle Hooks
Receive notifications when jobs start, advance, or finish:

```python
def on_job_start(self, gcode: str, estimated_time_sec: float) -> None:
    print(f"Burn started! Estimated run time: {estimated_time_sec}s")

def on_job_progress(self, lines_sent: int, lines_total: int, pct: float) -> None:
    print(f"Progress: {pct:.1f}% ({lines_sent}/{lines_total})")

def on_job_complete(self, duration_sec: float, was_aborted: bool) -> None:
    print(f"Burn {'ABORTED' if was_aborted else 'FINISHED'} in {duration_sec}s")
```

---

## 5. Worked Example
See [`examples/plugins/gcode_header_plugin/`](file:///home/k/LaserForge/examples/plugins/gcode_header_plugin/) for an end-to-end working implementation.
