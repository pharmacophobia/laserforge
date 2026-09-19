# LaserForge Example Plugin: G-Code Header & Production Logger

This example demonstrates how to build and install a custom third-party plugin for LaserForge.

## Capabilities Demonstrated
1. **G-Code Post-Processor**: Injects a custom production header and safety checklist into all exported or streamed G-code.
2. **Job Lifecycle Hooks**: Logs job start, estimated runtime, and job completion/abort telemetry.

## Installation
To activate this plugin in LaserForge:

```bash
mkdir -p ~/.laserforge/plugins/gcode_header_plugin
cp plugin.py ~/.laserforge/plugins/gcode_header_plugin/
```

Launch LaserForge. The plugin will be automatically discovered, validated, and loaded at startup.
