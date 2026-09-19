"""
LaserForge Multi-Camera Workbed Panoramic Stitching Engine.

Provides:
- Support for dual and multi-camera arrays covering wide-format laser beds (>900 mm).
- Independent intrinsic lens undistortion and perspective homography calibration per camera slot.
- Sub-pixel perspective warping into unified laser bed coordinate millimeter space.
- Advanced photometric seam blending:
  - Linear feathering (distance-weighted linear interpolation across the overlap seam)
  - Distance transform Voronoi blending (smooth gradient weighting)
  - Max-priority & Hard-seam blending
- Synchronized multi-stream frame capture and synthetic multi-camera simulator.
- JSON persistent configuration to ~/.laserforge/multi_camera_config.json.
"""

import os
import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional, Dict, Any, Union
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData

DEFAULT_MULTI_CAMERA_CONFIG_PATH = os.path.expanduser("~/.laserforge/multi_camera_config.json")


@dataclass
class CameraSlotConfig:
    """Configuration for a single camera in a multi-camera array."""
    slot_id: str = "cam_left"
    name: str = "Left Bed Camera"
    device_index: int = 0
    resolution: Tuple[int, int] = (1920, 1080)
    target_bounds_mm: Tuple[float, float, float, float] = (0.0, 0.0, 550.0, 600.0)  # (min_x, min_y, max_x, max_y)
    calibration: Optional[CameraCalibrationData] = None
    enabled: bool = True
    flip_horizontal: bool = False
    flip_vertical: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "name": self.name,
            "device_index": self.device_index,
            "resolution": list(self.resolution),
            "target_bounds_mm": list(self.target_bounds_mm),
            "calibration": self.calibration.to_dict() if self.calibration else None,
            "enabled": self.enabled,
            "flip_horizontal": self.flip_horizontal,
            "flip_vertical": self.flip_vertical,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraSlotConfig":
        cal_data = None
        if data.get("calibration"):
            cal_data = CameraCalibrationData.from_dict(data["calibration"])
        return cls(
            slot_id=data.get("slot_id", "cam_1"),
            name=data.get("name", "Camera Slot"),
            device_index=data.get("device_index", 0),
            resolution=tuple(data.get("resolution", (1920, 1080))),
            target_bounds_mm=tuple(data.get("target_bounds_mm", (0.0, 0.0, 500.0, 500.0))),
            calibration=cal_data,
            enabled=data.get("enabled", True),
            flip_horizontal=data.get("flip_horizontal", False),
            flip_vertical=data.get("flip_vertical", False),
        )


@dataclass
class MultiCameraConfig:
    """Master configuration for the multi-camera stitching system."""
    slots: List[CameraSlotConfig] = field(default_factory=list)
    bed_width_mm: float = 1000.0
    bed_height_mm: float = 600.0
    scale_px_per_mm: float = 2.5
    blend_mode: str = "LinearFeather"  # 'LinearFeather', 'DistanceTransform', 'MaxPriority', 'HardSeam'
    feather_overlap_mm: float = 40.0
    enabled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slots": [s.to_dict() for s in self.slots],
            "bed_width_mm": self.bed_width_mm,
            "bed_height_mm": self.bed_height_mm,
            "scale_px_per_mm": self.scale_px_per_mm,
            "blend_mode": self.blend_mode,
            "feather_overlap_mm": self.feather_overlap_mm,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultiCameraConfig":
        slots = [CameraSlotConfig.from_dict(s) for s in data.get("slots", [])]
        return cls(
            slots=slots,
            bed_width_mm=data.get("bed_width_mm", 1000.0),
            bed_height_mm=data.get("bed_height_mm", 600.0),
            scale_px_per_mm=data.get("scale_px_per_mm", 2.5),
            blend_mode=data.get("blend_mode", "LinearFeather"),
            feather_overlap_mm=data.get("feather_overlap_mm", 40.0),
            enabled=data.get("enabled", False),
        )

    def save_to_file(self, path: str = DEFAULT_MULTI_CAMERA_CONFIG_PATH):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as e:
            print(f"[LaserForge MultiCamera] Failed to save config to {path}: {e}")

    @classmethod
    def load_from_file(cls, path: str = DEFAULT_MULTI_CAMERA_CONFIG_PATH) -> "MultiCameraConfig":
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls.from_dict(data)
            except Exception as e:
                print(f"[LaserForge MultiCamera] Failed to load config from {path}: {e}")
        return cls._create_default_dual_setup()

    @classmethod
    def _create_default_dual_setup(cls) -> "MultiCameraConfig":
        """Generates a standard dual-camera configuration (Left / Right) for wide beds."""
        left_slot = CameraSlotConfig(
            slot_id="cam_left",
            name="Left Bed Camera (0 - 550 mm)",
            device_index=0,
            resolution=(1920, 1080),
            target_bounds_mm=(0.0, 0.0, 550.0, 600.0),
            calibration=CameraCalibrationData(
                device_index=0,
                device_name="Left Camera",
                resolution=(1920, 1080),
                bed_width_mm=1000.0,
                bed_height_mm=600.0,
                scale_px_per_mm=2.5,
            )
        )
        right_slot = CameraSlotConfig(
            slot_id="cam_right",
            name="Right Bed Camera (450 - 1000 mm)",
            device_index=1,
            resolution=(1920, 1080),
            target_bounds_mm=(450.0, 0.0, 1000.0, 600.0),
            calibration=CameraCalibrationData(
                device_index=1,
                device_name="Right Camera",
                resolution=(1920, 1080),
                bed_width_mm=1000.0,
                bed_height_mm=600.0,
                scale_px_per_mm=2.5,
            )
        )
        return cls(
            slots=[left_slot, right_slot],
            bed_width_mm=1000.0,
            bed_height_mm=600.0,
            scale_px_per_mm=2.5,
            blend_mode="LinearFeather",
            feather_overlap_mm=40.0,
            enabled=False
        )


class MultiCameraEngine:
    """
    Manages multi-camera arrays, synchronized image capture, individual slot homography,
    and perspective seamless composite orthophoto stitching for large-format laser cutters.
    """

    def __init__(self, config: Optional[MultiCameraConfig] = None):
        self.config = config or MultiCameraConfig.load_from_file()
        self._camera_engines: Dict[str, CameraEngine] = {}
        self._init_camera_engines()

    def _init_camera_engines(self):
        """Initializes individual CameraEngine wrappers for each configured slot."""
        self._camera_engines.clear()
        for slot in self.config.slots:
            eng = CameraEngine(calibration=slot.calibration)
            if eng.calibration.homography_matrix is None:
                # Pre-seed simulated homography for slots in simulated/mock mode
                self._compute_slot_simulated_homography(slot, eng)
            self._camera_engines[slot.slot_id] = eng

    def _compute_slot_simulated_homography(self, slot: CameraSlotConfig, engine: CameraEngine):
        """Generates realistic perspective homography for simulated wide-bed slots."""
        w, h = slot.resolution
        cx, cy = w // 2, h // 2
        bed_w = int(w * 0.75)
        bed_h = int(h * 0.75)

        # 4 corners in camera sensor space
        p1 = (cx - bed_w // 2, cy - bed_h // 2 + 25)
        p2 = (cx + bed_w // 2, cy - bed_h // 2 + 15)
        p3 = (cx + bed_w // 2 - 15, cy + bed_h // 2)
        p4 = (cx - bed_w // 2 + 15, cy + bed_h // 2)
        cam_fids = [
            (float(p1[0] + 40), float(p1[1] + 40)),
            (float(p2[0] - 40), float(p2[1] + 40)),
            (float(p3[0] - 40), float(p3[1] - 40)),
            (float(p4[0] + 40), float(p4[1] - 40))
        ]

        # 4 corners in bed mm space mapped to slot bounds
        min_x, min_y, max_x, max_y = slot.target_bounds_mm
        ins = 30.0
        bed_fids = [
            (min_x + ins, min_y + ins),
            (max_x - ins, min_y + ins),
            (max_x - ins, max_y - ins),
            (min_x + ins, max_y - ins)
        ]
        engine.compute_bed_homography(cam_fids, bed_fids)

    def get_slot_engine(self, slot_id: str) -> Optional[CameraEngine]:
        return self._camera_engines.get(slot_id)

    def open_all_cameras(self) -> Dict[str, bool]:
        """Opens streaming captures for all enabled camera slots."""
        results = {}
        for slot in self.config.slots:
            if slot.enabled and slot.slot_id in self._camera_engines:
                eng = self._camera_engines[slot.slot_id]
                res = eng.open_camera(slot.device_index, slot.resolution[0], slot.resolution[1])
                results[slot.slot_id] = res
        return results

    def close_all_cameras(self):
        """Closes and releases all camera streams."""
        for eng in self._camera_engines.values():
            eng.close_camera()

    def capture_slot_frame(self, slot_id: str, draw_guides: bool = False) -> Optional[np.ndarray]:
        """Captures a single frame from the specified camera slot."""
        eng = self._camera_engines.get(slot_id)
        if eng is None:
            return None
        frame = eng.capture_frame(draw_guides=draw_guides)
        if frame is not None:
            # Check slot mirroring/flips
            slot = next((s for s in self.config.slots if s.slot_id == slot_id), None)
            if slot and HAS_CV2:
                if slot.flip_horizontal and slot.flip_vertical:
                    frame = cv2.flip(frame, -1)
                elif slot.flip_horizontal:
                    frame = cv2.flip(frame, 1)
                elif slot.flip_vertical:
                    frame = cv2.flip(frame, 0)
        return frame

    def capture_all_frames(self) -> Dict[str, np.ndarray]:
        """Captures synchronized frames across all enabled camera slots."""
        frames = {}
        for slot in self.config.slots:
            if slot.enabled:
                f = self.capture_slot_frame(slot.slot_id)
                if f is not None:
                    frames[slot.slot_id] = f
        return frames

    def is_calibrated(self) -> bool:
        """Returns True if every enabled camera slot has a valid homography alignment."""
        for slot in self.config.slots:
            if slot.enabled:
                eng = self._camera_engines.get(slot.slot_id)
                if not eng or not eng.calibration.is_bed_aligned():
                    return False
        return True

    # -------------------------------------------------------------------------
    # Panoramic Workbed Stitching Pipeline
    # -------------------------------------------------------------------------
    def stitch_orthophoto(
        self,
        frames: Optional[Dict[str, np.ndarray]] = None,
        draw_seams: bool = False
    ) -> Optional[np.ndarray]:
        """
        Warps and stitches multiple camera feeds into a single unified high-resolution
        orthophoto of the complete laser workbed in exact millimeter scale.
        """
        if not HAS_CV2:
            return None

        captured_frames = frames if frames is not None else self.capture_all_frames()
        if not captured_frames:
            return None

        scale = self.config.scale_px_per_mm
        total_w_px = max(10, int(round(self.config.bed_width_mm * scale)))
        total_h_px = max(10, int(round(self.config.bed_height_mm * scale)))

        # Accumulated composite canvases (Float32 for accurate blend weight accumulation)
        accum_img = np.zeros((total_h_px, total_w_px, 3), dtype=np.float32)
        accum_weights = np.zeros((total_h_px, total_w_px), dtype=np.float32)

        warped_layers = []

        for slot in self.config.slots:
            if not slot.enabled or slot.slot_id not in captured_frames:
                continue

            frame = captured_frames[slot.slot_id]
            eng = self._camera_engines.get(slot.slot_id)
            if not eng or not eng.calibration.is_bed_aligned():
                continue

            # 1. Undistort frame
            undistorted = eng.undistort_frame(frame)

            # 2. Warp into full-bed orthophoto coordinate space
            H = eng.calibration.homography_matrix
            warped = cv2.warpPerspective(
                undistorted, H, (total_w_px, total_h_px),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0)
            )

            # 3. Create coverage mask for this slot's valid projected region
            mask = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
            _, valid_mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)

            # 4. Compute blend weight map based on configured strategy
            weight_map = self._compute_slot_weights(valid_mask, slot)
            warped_layers.append((slot.slot_id, warped, valid_mask, weight_map))

            # 5. Accumulate weighted colors
            for ch in range(3):
                accum_img[:, :, ch] += warped[:, :, ch].astype(np.float32) * weight_map
            accum_weights += weight_map

        # Normalize accumulated composite by total weight
        mask_nonzero = (accum_weights > 1e-4)
        stitched = np.zeros((total_h_px, total_w_px, 3), dtype=np.uint8)
        for ch in range(3):
            stitched[:, :, ch] = np.where(
                mask_nonzero,
                np.clip(accum_img[:, :, ch] / np.maximum(1e-4, accum_weights), 0, 255).astype(np.uint8),
                0
            )

        # Optional: draw visual seam demarcation lines for setup verification
        if draw_seams and len(warped_layers) > 1:
            stitched = self._draw_seam_lines(stitched, warped_layers)

        return stitched

    def _compute_slot_weights(self, valid_mask: np.ndarray, slot: CameraSlotConfig) -> np.ndarray:
        """
        Computes the spatial blend weighting matrix for a warped camera layer.
        """
        mode = self.config.blend_mode
        if mode == "HardSeam":
            return (valid_mask > 0).astype(np.float32)

        elif mode == "MaxPriority":
            return (valid_mask > 0).astype(np.float32) * 1.0

        elif mode == "DistanceTransform":
            # Distance from mask boundary for smooth feathered Voronoi blend
            dist = cv2.distanceTransform(valid_mask, cv2.DIST_L2, 5)
            max_d = float(np.max(dist)) if np.max(dist) > 0 else 1.0
            return dist / max_d

        else:  # LinearFeather (default)
            feather_px = max(5.0, self.config.feather_overlap_mm * self.config.scale_px_per_mm)
            dist = cv2.distanceTransform(valid_mask, cv2.DIST_L2, 5)
            weights = np.clip(dist / feather_px, 0.0, 1.0).astype(np.float32)
            return weights

    def _draw_seam_lines(
        self,
        composite: np.ndarray,
        warped_layers: List[Tuple[str, np.ndarray, np.ndarray, np.ndarray]]
    ) -> np.ndarray:
        """Overlays semi-transparent seam boundary contours and slot labels on the composite."""
        annotated = composite.copy()
        colors = [(0, 229, 255), (255, 0, 119), (0, 255, 128), (255, 234, 0)]
        for idx, (slot_id, _, mask, _) in enumerate(warped_layers):
            c = colors[idx % len(colors)]
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(annotated, contours, -1, c, 2)
            # Find centroid of mask to place slot tag
            m = cv2.moments(mask)
            if m["m00"] > 0:
                cx = int(m["m10"] / m["m00"])
                cy = int(m["m01"] / m["m00"])
                cv2.putText(annotated, slot_id.upper(), (cx - 40, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, c, 2, cv2.LINE_AA)
        return annotated

    def generate_synthetic_stitched_test_pattern(self) -> np.ndarray:
        """Generates a multi-camera synthetic test canvas simulating a dual camera bed."""
        w_px = int(round(self.config.bed_width_mm * self.config.scale_px_per_mm))
        h_px = int(round(self.config.bed_height_mm * self.config.scale_px_per_mm))
        canvas = np.full((h_px, w_px, 3), 36, dtype=np.uint8)

        # Draw grid
        step = int(50.0 * self.config.scale_px_per_mm)
        for x in range(0, w_px, step):
            cv2.line(canvas, (x, 0), (x, h_px), (50, 50, 60), 1)
        for y in range(0, h_px, step):
            cv2.line(canvas, (0, y), (w_px, y), (50, 50, 60), 1)

        # Draw left test target
        cv2.circle(canvas, (int(w_px * 0.25), int(h_px * 0.5)), 40, (0, 229, 255), 3)
        cv2.putText(canvas, "CAM 1 (LEFT)", (int(w_px * 0.25) - 60, int(h_px * 0.5) - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 229, 255), 2)

        # Draw right test target
        cv2.circle(canvas, (int(w_px * 0.75), int(h_px * 0.5)), 40, (255, 0, 119), 3)
        cv2.putText(canvas, "CAM 2 (RIGHT)", (int(w_px * 0.75) - 60, int(h_px * 0.5) - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 119), 2)

        # Overlap zone in the center
        seam_x = w_px // 2
        overlap_w = int(self.config.feather_overlap_mm * self.config.scale_px_per_mm)
        p1 = (seam_x - overlap_w // 2, 0)
        p2 = (seam_x + overlap_w // 2, h_px)
        overlay = canvas.copy()
        cv2.rectangle(overlay, p1, p2, (0, 100, 140), -1)
        cv2.addWeighted(overlay, 0.35, canvas, 0.65, 0, canvas)
        cv2.line(canvas, (seam_x, 0), (seam_x, h_px), (0, 255, 128), 1, cv2.LINE_AA)
        cv2.putText(canvas, "SEAM OVERLAP", (seam_x - 55, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 128), 1)

        return canvas
