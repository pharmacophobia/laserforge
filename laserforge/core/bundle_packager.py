"""
LaserForge Calibrated Preset Exchange & Project Bundle (.lfpak) Packager Engine.
Packages canvas vector artwork, calibrated material libraries, machine profiles,
and templates into compressed, checksum-verified portable distribution containers.
"""

from typing import List, Dict, Any, Optional, Tuple
import zipfile
import json
import os
import time
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, UTC

from laserforge.core.models import LaserEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.materials_database import MaterialDatabase, MaterialProfile, MATERIALS_CONFIG_PATH
from laserforge.config import MachineSettings
from laserforge.core.project_io import ProjectIO


@dataclass
class BundleManifest:
    bundle_name: str = "LaserForge-Package"
    author: str = "LaserForge Maker"
    created_at: str = ""
    format_version: str = "1.0"
    app_version: str = "2.5.0"
    notes: str = ""
    has_project: bool = False
    has_materials: bool = False
    has_machine_settings: bool = False
    has_templates: bool = False
    contents_summary: Dict[str, Any] = None
    checksums: Dict[str, str] = None


class BundlePackager:
    """Creates, inspects, and restores .lfpak project & workshop profile archives."""

    @classmethod
    def export_bundle(
        cls,
        export_path: str,
        project_entities: Optional[List[LaserEntity]] = None,
        layer_manager: Optional[LayerManager] = None,
        machine_settings: Optional[MachineSettings] = None,
        materials: Optional[List[MaterialProfile]] = None,
        templates: Optional[List[Dict[str, Any]]] = None,
        bundle_name: str = "LaserForge-Package",
        author: str = "LaserForge Maker",
        notes: str = ""
    ) -> Dict[str, Any]:
        """
        Compresses selected project components into a portable .lfpak zip bundle.
        """
        if not export_path.endswith(".lfpak"):
            export_path += ".lfpak"

        manifest = BundleManifest(
            bundle_name=bundle_name,
            author=author or "LaserForge Maker",
            created_at=datetime.now(UTC).isoformat() + "Z",
            format_version="1.0",
            app_version="2.5.0",
            notes=notes,
            has_project=project_entities is not None and len(project_entities) > 0,
            has_materials=materials is not None and len(materials) > 0,
            has_machine_settings=machine_settings is not None,
            has_templates=templates is not None and len(templates) > 0,
            contents_summary={},
            checksums={}
        )

        temp_files: Dict[str, bytes] = {}

        # 1. Project Artwork & Layers
        if manifest.has_project and layer_manager is not None:
            # Construct standard ProjectIO serialization dictionary
            entities_data = []
            for e in project_entities:
                e_dict = {
                    "type": e.__class__.__name__,
                    "id": e.id,
                    "layer_id": e.layer_id,
                    "name": e.name,
                    "x": e.x,
                    "y": e.y,
                    "rotation": e.rotation,
                    "locked": e.locked
                }
                if getattr(e, "speed_override", None) is not None:
                    e_dict["speed_override"] = float(e.speed_override)
                if getattr(e, "power_override", None) is not None:
                    e_dict["power_override"] = float(e.power_override)
                # Specific entity geometries
                for attr in ["width", "height", "corner_radius", "radius_x", "radius_y", "x2", "y2", "contours", "closed", "text", "font_family", "font_size"]:
                    if hasattr(e, attr):
                        e_dict[attr] = getattr(e, attr)
                entities_data.append(e_dict)

            layers_data = [l.to_dict() for l in layer_manager.get_all_layers()]

            proj_payload = {
                "version": "1.0",
                "entities": entities_data,
                "layers": layers_data
            }
            p_bytes = json.dumps(proj_payload, indent=2).encode("utf-8")
            temp_files["project.lfg"] = p_bytes
            manifest.contents_summary["entities_count"] = len(project_entities)
            manifest.contents_summary["layers_count"] = len(layers_data)

        # 2. Materials Library Presets
        if manifest.has_materials:
            m_data = [asdict(m) for m in materials]
            m_bytes = json.dumps(m_data, indent=2).encode("utf-8")
            temp_files["materials.json"] = m_bytes
            manifest.contents_summary["materials_count"] = len(materials)

        # 3. Machine Settings
        if manifest.has_machine_settings:
            ms_dict = {
                "bed_width": machine_settings.bed_width,
                "bed_height": machine_settings.bed_height,
                "max_speed_x": getattr(machine_settings, "max_speed_x", 3000.0),
                "max_speed_y": getattr(machine_settings, "max_speed_y", 3000.0),
                "accel_x": getattr(machine_settings, "accel_x", 500.0),
                "accel_y": getattr(machine_settings, "accel_y", 500.0),
                "laser_type": getattr(machine_settings, "laser_type", "Diode (3W Blue)"),
                "baud_rate": getattr(machine_settings, "baud_rate", 115200)
            }
            ms_bytes = json.dumps(ms_dict, indent=2).encode("utf-8")
            temp_files["machine_settings.json"] = ms_bytes
            manifest.contents_summary["machine_bed"] = f"{machine_settings.bed_width}x{machine_settings.bed_height}mm"

        # 4. Custom Templates
        if manifest.has_templates:
            t_bytes = json.dumps(templates, indent=2).encode("utf-8")
            temp_files["templates.json"] = t_bytes
            manifest.contents_summary["templates_count"] = len(templates)

        # Compute SHA-256 checksums
        for fname, fbytes in temp_files.items():
            manifest.checksums[fname] = hashlib.sha256(fbytes).hexdigest()

        # Add manifest.json
        manifest_bytes = json.dumps(asdict(manifest), indent=2).encode("utf-8")
        temp_files["manifest.json"] = manifest_bytes

        # Write ZIP container
        os.makedirs(os.path.dirname(os.path.abspath(export_path)), exist_ok=True)
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, fbytes in temp_files.items():
                zf.writestr(fname, fbytes)

        file_size_kb = os.path.getsize(export_path) / 1024.0
        return {
            "success": True,
            "filepath": export_path,
            "file_size_kb": round(file_size_kb, 1),
            "manifest": manifest
        }

    @classmethod
    def inspect_bundle(cls, bundle_path: str) -> Dict[str, Any]:
        """
        Inspects an .lfpak archive without modifying system state.
        Validates internal SHA256 checksums.
        """
        if not os.path.exists(bundle_path):
            return {"valid": False, "error": f"File not found: {bundle_path}"}

        if not zipfile.is_zipfile(bundle_path):
            return {"valid": False, "error": "Not a valid LaserForge bundle (.lfpak) archive."}

        try:
            with zipfile.ZipFile(bundle_path, "r") as zf:
                namelist = zf.namelist()
                if "manifest.json" not in namelist:
                    return {"valid": False, "error": "Corrupt bundle: missing manifest.json"}

                manifest_raw = zf.read("manifest.json").decode("utf-8")
                manifest_dict = json.loads(manifest_raw)

                # Verify checksums of bundled components
                checksums = manifest_dict.get("checksums", {})
                corrupted = []
                for fname, expected_hash in checksums.items():
                    if fname in namelist:
                        actual_hash = hashlib.sha256(zf.read(fname)).hexdigest()
                        if actual_hash != expected_hash:
                            corrupted.append(fname)
                    else:
                        corrupted.append(fname)

                if corrupted:
                    return {"valid": False, "error": f"Checksum verification failed for: {', '.join(corrupted)}"}

                manifest = BundleManifest(**manifest_dict)
                return {
                    "valid": True,
                    "manifest": manifest,
                    "files": namelist,
                    "file_size_kb": round(os.path.getsize(bundle_path) / 1024.0, 1)
                }
        except Exception as e:
            return {"valid": False, "error": f"Failed to inspect bundle: {e}"}

    @classmethod
    def import_bundle(
        cls,
        bundle_path: str,
        restore_project: bool = True,
        restore_materials: bool = True,
        restore_machine_settings: bool = False,
        restore_templates: bool = True,
        merge_materials: bool = True
    ) -> Dict[str, Any]:
        """
        Unpacks and restores bundle contents into LaserForge.
        """
        inspection = cls.inspect_bundle(bundle_path)
        if not inspection.get("valid", False):
            return {"success": False, "error": inspection.get("error", "Invalid bundle")}

        manifest: BundleManifest = inspection["manifest"]
        result = {
            "success": True,
            "manifest": manifest,
            "restored_project": False,
            "restored_materials_count": 0,
            "restored_machine_settings": None,
            "restored_templates_count": 0,
            "entities": [],
            "layers_dict": {}
        }

        with zipfile.ZipFile(bundle_path, "r") as zf:
            # 1. Restore Project Artwork
            if restore_project and manifest.has_project and "project.lfg" in zf.namelist():
                proj_data = json.loads(zf.read("project.lfg").decode("utf-8"))
                result["project_raw"] = proj_data
                result["restored_project"] = True

            # 2. Restore Materials Library
            if restore_materials and manifest.has_materials and "materials.json" in zf.namelist():
                mat_data = json.loads(zf.read("materials.json").decode("utf-8"))
                imported_profiles = [MaterialProfile(**item) for item in mat_data]

                db = MaterialDatabase()
                if merge_materials:
                    existing_ids = {m.id for m in db.get_all()}
                    added_count = 0
                    for prof in imported_profiles:
                        if prof.id not in existing_ids:
                            db.add_material(prof)
                            added_count += 1
                    result["restored_materials_count"] = added_count
                else:
                    db.materials = imported_profiles
                    db.save()
                    result["restored_materials_count"] = len(imported_profiles)

            # 3. Restore Machine Settings
            if restore_machine_settings and manifest.has_machine_settings and "machine_settings.json" in zf.namelist():
                ms_data = json.loads(zf.read("machine_settings.json").decode("utf-8"))
                result["restored_machine_settings"] = ms_data

            # 4. Restore Templates
            if restore_templates and manifest.has_templates and "templates.json" in zf.namelist():
                tmpl_data = json.loads(zf.read("templates.json").decode("utf-8"))
                result["restored_templates_count"] = len(tmpl_data)
                result["templates"] = tmpl_data

        return result
