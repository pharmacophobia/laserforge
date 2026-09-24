"""
LaserForge USB Camera Vision and Bed Alignment Engine.
Provides:
- USB overhead camera video stream capture (V4L2 / OpenCV VideoCapture)
- Intrinsic lens distortion calibration using OpenCV checkerboard analysis
- Extrinsic perspective homography mapping (4-point alignment to bed coordinates)
- High-precision rectified orthophoto generation for 2D CAD background overlay
- Realistic mock/simulator mode for headless environments and automated testing
"""

import os
import glob
import json
import time
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


DEFAULT_CALIBRATION_FILE = os.path.expanduser("~/.laserforge/camera_calibration.json")


@dataclass
class CameraCalibrationData:
    device_index: Any = 0
    device_name: str = "USB Laser Camera"
    resolution: Tuple[int, int] = (1920, 1080)
    camera_matrix: Optional[np.ndarray] = None  # 3x3 intrinsic K
    distortion_coeffs: Optional[np.ndarray] = None  # 1x5 or 5x1 D
    homography_matrix: Optional[np.ndarray] = None  # 3x3 perspective H
    bed_width_mm: float = 400.0
    bed_height_mm: float = 400.0
    scale_px_per_mm: float = 3.0
    reprojection_error: float = 0.0
    calibrated_at: str = ""
    camera_fiducials: List[Tuple[float, float]] = field(default_factory=list)
    bed_fiducials_mm: List[Tuple[float, float]] = field(default_factory=list)
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    fine_scale_x: float = 1.0
    fine_scale_y: float = 1.0
    fine_rotation_deg: float = 0.0
    overlay_opacity: float = 0.55
    fiducial_inset_mm: float = 40.0
    is_fisheye: bool = False
    homography_resolution: Tuple[int, int] = (1920, 1080)

    def is_lens_calibrated(self) -> bool:
        if self.camera_matrix is None or self.distortion_coeffs is None:
            return False
        if not (0.0 <= self.reprojection_error <= 10.0):
            return False
        try:
            fx = float(self.camera_matrix[0, 0])
            fy = float(self.camera_matrix[1, 1])
            if not (10.0 <= fx and 10.0 <= fy):
                return False
            if math.isnan(fx) or math.isnan(fy) or math.isinf(fx) or math.isinf(fy):
                return False
            return True
        except Exception:
            return False

    def is_bed_aligned(self) -> bool:
        if self.homography_matrix is None:
            return False
        try:
            if self.homography_matrix.shape != (3, 3):
                return False
            det = float(np.linalg.det(self.homography_matrix))
            if det <= 1e-9 or math.isnan(det) or math.isinf(det):
                return False
            return True
        except Exception:
            return False

    def sanitize(self):
        """Discards corrupted or unphysical calibration matrices."""
        if self.camera_matrix is not None:
            if not self.is_lens_calibrated():
                self.camera_matrix = None
                self.distortion_coeffs = None
                self.reprojection_error = 0.0

        if self.homography_matrix is not None:
            if not self.is_bed_aligned():
                self.homography_matrix = None

    def reset(self, bed_width_mm: float = 400.0, bed_height_mm: float = 400.0):
        """Resets all calibration and fine-tune parameters to clean defaults."""
        self.camera_matrix = None
        self.distortion_coeffs = None
        self.homography_matrix = None
        self.reprojection_error = 0.0
        self.calibrated_at = ""
        self.camera_fiducials = []
        self.bed_fiducials_mm = []
        self.bed_width_mm = bed_width_mm
        self.bed_height_mm = bed_height_mm
        self.offset_x_mm = 0.0
        self.offset_y_mm = 0.0
        self.fine_scale_x = 1.0
        self.fine_scale_y = 1.0
        self.fine_rotation_deg = 0.0
        self.overlay_opacity = 0.55
        self.fiducial_inset_mm = 40.0
        self.homography_resolution = (1920, 1080)

    @staticmethod
    def get_default_bed_fiducials(bed_w_mm: float, bed_h_mm: float, inset_mm: float = 40.0) -> List[Tuple[float, float]]:
        """Returns standard clockwise (TL, TR, BR, BL) fiducial bed coordinates."""
        ins = min(inset_mm, min(bed_w_mm, bed_h_mm) * 0.45)
        return [
            (ins, ins),
            (bed_w_mm - ins, ins),
            (bed_w_mm - ins, bed_h_mm - ins),
            (ins, bed_h_mm - ins)
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_index": self.device_index,
            "device_name": self.device_name,
            "resolution": list(self.resolution),
            "camera_matrix": self.camera_matrix.tolist() if self.camera_matrix is not None else None,
            "distortion_coeffs": self.distortion_coeffs.tolist() if self.distortion_coeffs is not None else None,
            "homography_matrix": self.homography_matrix.tolist() if self.homography_matrix is not None else None,
            "bed_width_mm": self.bed_width_mm,
            "bed_height_mm": self.bed_height_mm,
            "scale_px_per_mm": self.scale_px_per_mm,
            "reprojection_error": self.reprojection_error,
            "calibrated_at": self.calibrated_at,
            "camera_fiducials": self.camera_fiducials,
            "bed_fiducials_mm": self.bed_fiducials_mm,
            "offset_x_mm": self.offset_x_mm,
            "offset_y_mm": self.offset_y_mm,
            "fine_scale_x": self.fine_scale_x,
            "fine_scale_y": self.fine_scale_y,
            "fine_rotation_deg": self.fine_rotation_deg,
            "overlay_opacity": self.overlay_opacity,
            "fiducial_inset_mm": self.fiducial_inset_mm,
            "homography_resolution": list(self.homography_resolution)
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CameraCalibrationData":
        k_list = d.get("camera_matrix")
        d_list = d.get("distortion_coeffs")
        h_list = d.get("homography_matrix")

        obj = cls(
            device_index=d.get("device_index", 0),
            device_name=d.get("device_name", "USB Laser Camera"),
            resolution=tuple(d.get("resolution", (1920, 1080))),
            camera_matrix=np.array(k_list, dtype=np.float64) if k_list is not None else None,
            distortion_coeffs=np.array(d_list, dtype=np.float64) if d_list is not None else None,
            homography_matrix=np.array(h_list, dtype=np.float64) if h_list is not None else None,
            bed_width_mm=d.get("bed_width_mm", 400.0),
            bed_height_mm=d.get("bed_height_mm", 400.0),
            scale_px_per_mm=d.get("scale_px_per_mm", 3.0),
            reprojection_error=d.get("reprojection_error", 0.0),
            calibrated_at=d.get("calibrated_at", ""),
            camera_fiducials=[tuple(p) for p in d.get("camera_fiducials", [])],
            bed_fiducials_mm=[tuple(p) for p in d.get("bed_fiducials_mm", [])],
            offset_x_mm=d.get("offset_x_mm", 0.0),
            offset_y_mm=d.get("offset_y_mm", 0.0),
            fine_scale_x=d.get("fine_scale_x", 1.0),
            fine_scale_y=d.get("fine_scale_y", 1.0),
            fine_rotation_deg=d.get("fine_rotation_deg", 0.0),
            overlay_opacity=d.get("overlay_opacity", 0.55),
            fiducial_inset_mm=d.get("fiducial_inset_mm", 40.0),
            homography_resolution=tuple(d.get("homography_resolution", (1920, 1080)))
        )
        obj.sanitize()
        return obj

    def save_to_file(self, filepath: str = DEFAULT_CALIBRATION_FILE):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_from_file(cls, filepath: str = DEFAULT_CALIBRATION_FILE) -> "CameraCalibrationData":
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                obj = cls.from_dict(data)
                obj.sanitize()
                return obj
            except Exception as e:
                print(f"Error loading camera calibration: {e}")
        return cls()


class CameraEngine:
    """
    Manages live camera capture, calibration, and orthophoto bed unwarping.
    """

    def __init__(self, calibration: Optional[CameraCalibrationData] = None):
        self.calibration = calibration or CameraCalibrationData.load_from_file()
        self.cap: Optional[Any] = None
        self.is_mock: bool = (self.calibration.device_index == -1)
        # Set when open_camera() silently falls back to a simulated frame after
        # failing to open the requested device; cleared on every real open attempt.
        self.fallback_from: Optional[Any] = None
        self.last_error: Optional[str] = None
        self._mock_frame_counter: int = 0
        self.live_laser_pos: Optional[Tuple[float, float]] = None
        self.live_laser_state: str = "Idle"
        self.show_live_reticle: bool = True
        if self.is_mock and not self.calibration.is_bed_aligned():
            self.compute_simulated_homography(self.calibration.bed_width_mm, self.calibration.bed_height_mm)

    def set_live_laser_position(self, x_mm: float, y_mm: float, state: str = "Idle"):
        """Updates the physical laser head position in mm for real-time vision reticle tracking."""
        self.live_laser_pos = (float(x_mm), float(y_mm))
        self.live_laser_state = state

    def laser_to_camera(self, x_mm: float, y_mm: float) -> Optional[Tuple[float, float]]:
        """
        Converts physical laser bed coordinates (X, Y) in mm into camera sensor pixel coordinates (u, v).
        Uses inverse perspective homography matrix H^-1.
        """
        if not HAS_CV2 or not self.calibration.is_bed_aligned():
            return None
        H = self.calibration.homography_matrix
        if H is None:
            return None
        try:
            H_inv = np.linalg.inv(H)
            scale = self.calibration.scale_px_per_mm
            ortho_pt = np.array([x_mm * scale, y_mm * scale, 1.0], dtype=np.float64)
            cam_pt = H_inv @ ortho_pt
            if abs(cam_pt[2]) < 1e-9:
                return None
            return (float(cam_pt[0] / cam_pt[2]), float(cam_pt[1] / cam_pt[2]))
        except Exception:
            return None

    def camera_to_laser(self, u: float, v: float) -> Optional[Tuple[float, float]]:
        """
        Converts camera sensor pixel coordinates (u, v) into physical laser bed coordinates (X, Y) in mm.
        Uses perspective homography matrix H.
        """
        if not HAS_CV2 or not self.calibration.is_bed_aligned():
            return None
        H = self.calibration.homography_matrix
        if H is None:
            return None
        try:
            scale = self.calibration.scale_px_per_mm
            cam_pt = np.array([u, v, 1.0], dtype=np.float64)
            ortho_pt = H @ cam_pt
            if abs(ortho_pt[2]) < 1e-9:
                return None
            return (float((ortho_pt[0] / ortho_pt[2]) / scale), float((ortho_pt[1] / ortho_pt[2]) / scale))
        except Exception:
            return None

    def draw_laser_reticle_on_frame(
        self,
        frame: np.ndarray,
        laser_pos_mm: Optional[Tuple[float, float]] = None,
        state: Optional[str] = None
    ) -> np.ndarray:
        """
        Draws a high-visibility real-time laser head reticle and telemetry badge
        on the camera video frame at the predicted camera sensor position.
        """
        if not HAS_CV2 or frame is None:
            return frame

        pos = laser_pos_mm or self.live_laser_pos
        if pos is None:
            return frame

        st = state or self.live_laser_state or "Idle"
        cam_pt = self.laser_to_camera(pos[0], pos[1])
        if cam_pt is None:
            if self.is_mock:
                h_f, w_f = frame.shape[:2]
                cx, cy = w_f // 2, h_f // 2
                bed_w = int(w_f * 0.70)
                bed_h = int(h_f * 0.70)
                norm_x = min(1.0, max(0.0, pos[0] / max(1.0, self.calibration.bed_width_mm)))
                norm_y = min(1.0, max(0.0, pos[1] / max(1.0, self.calibration.bed_height_mm)))
                cam_pt = (
                    (cx - bed_w // 2) + norm_x * bed_w,
                    (cy - bed_h // 2) + norm_y * bed_h
                )
            else:
                return frame

        out = frame.copy()
        u, v = int(round(cam_pt[0])), int(round(cam_pt[1]))
        h_frame, w_frame = out.shape[:2]
        if not (-50 <= u <= w_frame + 50 and -50 <= v <= h_frame + 50):
            return out

        state_colors = {
            "Run": (68, 23, 255),       # Bright Red
            "Hold": (0, 145, 255),      # Orange
            "Jog": (255, 229, 0),       # Cyan
            "Alarm": (0, 0, 213),       # Deep Red
            "Idle": (118, 230, 0),      # Bright Green
        }
        color = state_colors.get(st, (118, 230, 0))

        # Target rings
        cv2.circle(out, (u, v), 12, color, 2, cv2.LINE_AA)
        cv2.circle(out, (u, v), 24, color, 1, cv2.LINE_AA)
        cv2.circle(out, (u, v), 3, color, -1, cv2.LINE_AA)

        # Crosshairs with center aperture gap
        reticle_len = 32
        gap = 5
        cv2.line(out, (u - reticle_len, v), (u - gap, v), color, 2, cv2.LINE_AA)
        cv2.line(out, (u + gap, v), (u + reticle_len, v), color, 2, cv2.LINE_AA)
        cv2.line(out, (u, v - reticle_len), (u, v - gap), color, 2, cv2.LINE_AA)
        cv2.line(out, (u, v + gap), (u, v + reticle_len), color, 2, cv2.LINE_AA)

        # Floating HUD Badge
        hud_text_pos = f"X:{pos[0]:.1f} Y:{pos[1]:.1f}"
        hud_text_st = f"[{st}]"
        badge_x = min(w_frame - 150, max(10, u + 18))
        badge_y = min(h_frame - 35, max(25, v - 12))

        bg_p1 = (badge_x - 3, badge_y - 18)
        bg_p2 = (badge_x + 130, badge_y + 14)
        overlay = out.copy()
        cv2.rectangle(overlay, bg_p1, bg_p2, (20, 20, 24), -1)
        cv2.rectangle(overlay, bg_p1, bg_p2, color, 1)
        cv2.addWeighted(overlay, 0.80, out, 0.20, 0, out)

        cv2.putText(out, hud_text_pos, (badge_x + 4, badge_y - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
        cv2.putText(out, hud_text_st, (badge_x + 4, badge_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

        return out

    @staticmethod
    def list_available_cameras() -> List[Dict[str, Any]]:
        """
        Discovers plugged-in USB cameras via /dev/video* and OpenCV probing.
        Always provides simulated test camera option if no hardware is present.
        """
        cameras = []
        if not HAS_CV2:
            return [{"index": -1, "name": "Simulated Camera (OpenCV Missing)", "is_mock": True}]

        dev_files = sorted(glob.glob("/dev/video*"))
        tested_indices = set()

        for dev_path in dev_files:
            try:
                idx_str = dev_path.replace("/dev/video", "")
                if idx_str.isdigit():
                    idx = int(idx_str)
                    if idx in tested_indices or idx > 10:
                        continue
                    tested_indices.add(idx)

                    cap = cv2.VideoCapture(idx)
                    # A v4l2loopback / unattached device can report isOpened()
                    # yet deliver no frames. Require an actual readable frame so
                    # we don't advertise a dead device as usable.
                    ok = False
                    if cap.isOpened():
                        ok, _ = cap.read()
                    if ok:
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        cameras.append({
                            "index": idx,
                            "name": f"USB Video Camera {idx} ({w}x{h})",
                            "device_path": dev_path,
                            "is_mock": False
                        })
                    cap.release()
            except Exception:
                pass

        # Fallback probe across common indices if no /dev/video* matched.
        # Do not hardcode 0: on many systems the working camera is at a
        # higher index (e.g. a virtual/loopback device occupies 0).
        if not cameras:
            for idx in range(0, 5):
                try:
                    cap = cv2.VideoCapture(idx)
                    ok = False
                    if cap.isOpened():
                        ok, _ = cap.read()
                    if ok:
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        cameras.append({
                            "index": idx,
                            "name": f"Camera {idx} ({w}x{h})",
                            "device_path": f"/dev/video{idx}",
                            "is_mock": False
                        })
                        cap.release()
                        break
                    cap.release()
                except Exception:
                    pass

        # Add PiBridge / Network Wireless Camera
        cameras.append({
            "index": "http://laserbridge.local:8080/stream",
            "name": "PiBridge Wireless Camera (http://laserbridge.local:8080/stream)",
            "device_path": "http://laserbridge.local:8080/stream",
            "is_mock": False,
            "is_network": True
        })

        # Always append Simulated Camera for testing / development
        cameras.append({
            "index": -1,
            "name": "Simulated Overhead Bed Camera (Demo / Test Mode)",
            "device_path": "mock://overhead_bed",
            "is_mock": True
        })

        return cameras

    def open_camera(self, device_index: Any = 0, width: int = 1920, height: int = 1080) -> bool:
        """
        Opens camera stream at specified resolution. Supports physical USB index (int),
        network stream URL (str starting with http://, https://, rtsp://), or simulated (-1).
        """
        self.close_camera()
        self.fallback_from = None
        self.last_error = None

        if device_index == -1 or not HAS_CV2:
            self.is_mock = True
            self.calibration.device_index = -1
            self.calibration.device_name = "Simulated Overhead Bed Camera"
            self.calibration.resolution = (width, height)
            return True

        is_net = isinstance(device_index, str) and device_index.startswith(("http://", "https://", "rtsp://"))
        if is_net:
            try:
                self.cap = cv2.VideoCapture(device_index)
                if self.cap.isOpened():
                    self.is_mock = False
                    self.calibration.device_index = device_index
                    self.calibration.device_name = f"PiBridge Camera ({device_index})"
                    actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    self.calibration.resolution = (actual_w or width, actual_h or height)
                    return True
            except Exception as e:
                print(f"Could not open network camera {device_index}: {e}")

        try:
            target_idx = int(device_index) if not is_net else 0
            self.cap = cv2.VideoCapture(target_idx)
            if self.cap.isOpened() and self.cap.read()[0]:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.is_mock = False
                self.calibration.device_index = target_idx
                actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.calibration.resolution = (actual_w, actual_h)
                return True
        except Exception as e:
            print(f"Could not open physical camera {device_index}: {e}")

        # Fallback to simulated. This is NOT a successful open of the requested
        # device -- record why, so the UI can warn the user instead of silently
        # showing a synthetic frame as if the camera were working.
        self.is_mock = True
        self.fallback_from = device_index
        self.last_error = (
            f"Could not open camera device {device_index!r}. "
            "Falling back to a simulated demo frame."
        )
        self.calibration.device_index = -1
        self.calibration.device_name = "Simulated Overhead Bed Camera (Fallback)"
        self.calibration.resolution = (width, height)
        return True

    def close_camera(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def capture_frame(self, draw_guides: bool = False, draw_laser_reticle: bool = False) -> Optional[np.ndarray]:
        """
        Captures raw camera frame (BGR uint8) with optional alignment guides and real-time laser reticle tracking.
        """
        if self.is_mock:
            frame = self._generate_synthetic_camera_frame(draw_guides=draw_guides)
        else:
            # Auto-open camera if not currently open but a valid physical device is configured
            if self.cap is None and self.calibration.device_index >= 0 and HAS_CV2:
                self.open_camera(self.calibration.device_index, *self.calibration.resolution)

            if self.cap is None or not self.cap.isOpened():
                frame = self._generate_synthetic_camera_frame(draw_guides=draw_guides)
            else:
                try:
                    # Drain stale buffer frames on V4L2 devices to ensure a fresh image
                    for _ in range(2):
                        self.cap.grab()
                    ret, frame = self.cap.read()
                    if not ret or frame is None:
                        frame = self._generate_synthetic_camera_frame(draw_guides=draw_guides)
                except Exception as e:
                    print(f"Error capturing camera frame: {e}")
                    frame = self._generate_synthetic_camera_frame(draw_guides=draw_guides)

        if frame is not None and (draw_laser_reticle or (self.show_live_reticle and self.live_laser_pos is not None)):
            frame = self.draw_laser_reticle_on_frame(frame)

        return frame

    def undistort_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Corrects lens barrel/pincushion distortion using calibrated camera matrix K and D,
        with support for ultra-wide fisheye lens models (cv2.fisheye).
        """
        if not HAS_CV2 or not self.calibration.is_lens_calibrated():
            return frame

        try:
            if getattr(self.calibration, "is_fisheye", False):
                from laserforge.core.fisheye_camera import FisheyeRectifier, FisheyeCalibrationData
                if not hasattr(self, "_fisheye_rectifier"):
                    k = self.calibration.camera_matrix
                    d = self.calibration.distortion_coeffs
                    cal = FisheyeCalibrationData(
                        fx=float(k[0, 0]), fy=float(k[1, 1]),
                        cx=float(k[0, 2]), cy=float(k[1, 2]),
                        k1=float(d[0]) if len(d) > 0 else -0.12,
                        k2=float(d[1]) if len(d) > 1 else 0.03
                    )
                    self._fisheye_rectifier = FisheyeRectifier(cal)
                return self._fisheye_rectifier.undistort(frame)

            return cv2.undistort(
                frame,
                self.calibration.camera_matrix,
                self.calibration.distortion_coeffs
            )
        except Exception as e:
            print(f"Error undistorting frame: {e}")
            return frame

    def rectify_bed_image(self, frame: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """
        Generates a top-down, rectified orthophoto image of the laser workbed in RGB format.
        Output dimensions match (bed_width_mm * scale_px_per_mm, bed_height_mm * scale_px_per_mm).
        """
        if frame is None:
            frame = self.capture_frame()
        if frame is None or not HAS_CV2:
            return None

        # 1. Undistort lens
        undist = self.undistort_frame(frame)

        # 2. Perspective warp to bed
        out_w = max(10, int(round(self.calibration.bed_width_mm * self.calibration.scale_px_per_mm)))
        out_h = max(10, int(round(self.calibration.bed_height_mm * self.calibration.scale_px_per_mm)))

        try:
            if self.calibration.is_bed_aligned():
                H = self.calibration.homography_matrix
                homo_w, homo_h = getattr(self.calibration, "homography_resolution", (1920, 1080))
                if (undist.shape[1], undist.shape[0]) != (homo_w, homo_h) and homo_w > 0 and homo_h > 0:
                    undist_for_warp = cv2.resize(undist, (homo_w, homo_h), interpolation=cv2.INTER_LINEAR)
                else:
                    undist_for_warp = undist
                warped = cv2.warpPerspective(undist_for_warp, H, (out_w, out_h))
            else:
                # Fallback resize if not yet homography-calibrated
                warped = cv2.resize(undist, (out_w, out_h))

            # Convert BGR -> RGB for Qt / PIL
            return cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
        except Exception as e:
            print(f"Error rectifying bed image: {e}")
            try:
                resized = cv2.resize(undist, (out_w, out_h))
                return cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            except Exception:
                return None

    # -------------------------------------------------------------------------
    # Lens Calibration Routine
    # -------------------------------------------------------------------------
    @staticmethod
    def detect_chessboard_corners(
        frame: np.ndarray, pattern_size: Tuple[int, int] = (9, 6)
    ) -> Tuple[bool, Optional[np.ndarray], np.ndarray]:
        """
        Finds chessboard corners with sub-pixel refinement.
        Returns (found, corners, visual_debug_frame).
        """
        if not HAS_CV2:
            return False, None, frame

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
        ret, corners = cv2.findChessboardCorners(gray, pattern_size, flags)

        vis = frame.copy()
        if ret and corners is not None:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners_subpix = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(vis, pattern_size, corners_subpix, ret)
            return True, corners_subpix, vis

        return False, None, vis

    def calibrate_lens_from_snapshots(
        self,
        corner_list: List[np.ndarray],
        pattern_size: Tuple[int, int] = (9, 6),
        square_size_mm: float = 25.0
    ) -> Tuple[bool, float, str]:
        """
        Computes camera intrinsic matrix K and distortion coefficients D.
        Requires at least 3 captured snapshots with detected corners (5-15 recommended).
        """
        if not HAS_CV2:
            return False, 0.0, "OpenCV is not available"

        if len(corner_list) < 3:
            return False, 0.0, f"Need at least 3 valid calibration snapshots (captured {len(corner_list)})"

        objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2) * square_size_mm

        objpoints = [objp for _ in range(len(corner_list))]
        imgpoints = corner_list
        w, h = self.calibration.resolution

        try:
            ret_err, K, D, _, _ = cv2.calibrateCamera(
                objpoints, imgpoints, (w, h), None, None
            )

            self.calibration.camera_matrix = K
            self.calibration.distortion_coeffs = D
            self.calibration.reprojection_error = round(float(ret_err), 3)
            self.calibration.calibrated_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.calibration.save_to_file()
            return True, self.calibration.reprojection_error, "Success"
        except Exception as e:
            return False, 0.0, str(e)

    # -------------------------------------------------------------------------
    # Bed Homography Alignment
    # -------------------------------------------------------------------------
    def compute_bed_homography(
        self,
        camera_pts: List[Tuple[float, float]],
        bed_pts_mm: List[Tuple[float, float]]
    ) -> bool:
        """
        Calculates the 3x3 perspective homography matrix H mapping undistorted camera
        pixel coordinates directly to laser bed orthophoto pixels.
        camera_pts: 4 points [(u1, v1), (u2, v2), (u3, v3), (u4, v4)]
        bed_pts_mm: 4 points [(X1, Y1), (X2, Y2), (X3, Y3), (X4, Y4)] in bed mm
        """
        if not HAS_CV2 or len(camera_pts) != 4 or len(bed_pts_mm) != 4:
            return False

        scale = self.calibration.scale_px_per_mm
        src = np.array(camera_pts, dtype=np.float32)
        dst = np.array([[x * scale, y * scale] for x, y in bed_pts_mm], dtype=np.float32)

        try:
            H = cv2.getPerspectiveTransform(src, dst)
            self.calibration.homography_matrix = H
            self.calibration.camera_fiducials = camera_pts
            self.calibration.bed_fiducials_mm = bed_pts_mm
            self.calibration.homography_resolution = tuple(self.calibration.resolution)
            self.calibration.save_to_file()
            return True
        except Exception as e:
            print(f"Homography error: {e}")
            return False

    def compute_simulated_homography(
        self,
        bed_width_mm: float = 400.0,
        bed_height_mm: float = 400.0
    ) -> bool:
        """
        Calculates perspective homography for the synthetic simulated camera view
        mapping simulated camera fiducials directly to standard bed coordinates.
        """
        w, h = self.calibration.resolution
        cx, cy = w // 2, h // 2
        bed_w = int(w * 0.70)
        bed_h = int(h * 0.70)

        # 4 Bed corners in camera view with slight perspective tilt (matching _generate_synthetic_camera_frame)
        p1 = (cx - bed_w // 2, cy - bed_h // 2 + 30)
        p2 = (cx + bed_w // 2, cy - bed_h // 2 + 20)
        p3 = (cx + bed_w // 2 - 20, cy + bed_h // 2)
        p4 = (cx - bed_w // 2 + 20, cy + bed_h // 2)

        # 4 alignment crosshairs matching _generate_synthetic_camera_frame
        fids = [
            (float(p1[0] + 50), float(p1[1] + 50)),
            (float(p2[0] - 50), float(p2[1] + 50)),
            (float(p3[0] - 50), float(p3[1] - 50)),
            (float(p4[0] + 50), float(p4[1] - 50))
        ]
        bed_fids = self.calibration.get_default_bed_fiducials(
            bed_width_mm, bed_height_mm, self.calibration.fiducial_inset_mm
        )
        return self.compute_bed_homography(fids, bed_fids)

    # -------------------------------------------------------------------------
    # Synthetic Simulator Frame Generator (Demo Mode)
    # -------------------------------------------------------------------------
    def _generate_synthetic_camera_frame(self, draw_guides: bool = False) -> np.ndarray:
        """
        Renders a realistic overhead laser bed camera view with wood workpiece,
        laser head marker, and optional alignment calibration crosshairs.
        """
        w, h = self.calibration.resolution
        self._mock_frame_counter += 1

        # Base camera frame (metal honeycomb bed background)
        frame = np.full((h, w, 3), 42, dtype=np.uint8)

        # Draw honeycomb / laser bed frame in perspective
        cx, cy = w // 2, h // 2
        bed_w = int(w * 0.70)
        bed_h = int(h * 0.70)

        # 4 Bed corners in camera view with slight perspective tilt
        p1 = (cx - bed_w // 2, cy - bed_h // 2 + 30)
        p2 = (cx + bed_w // 2, cy - bed_h // 2 + 20)
        p3 = (cx + bed_w // 2 - 20, cy + bed_h // 2)
        p4 = (cx - bed_w // 2 + 20, cy + bed_h // 2)
        bed_poly = np.array([p1, p2, p3, p4], dtype=np.int32)

        if HAS_CV2:
            cv2.fillPoly(frame, [bed_poly], (58, 62, 70))
            cv2.polylines(frame, [bed_poly], True, (0, 229, 255), 2)

            # Draw a sample basswood workpiece on the bed
            wood_poly = np.array([
                (cx - 150, cy - 80),
                (cx + 180, cy - 75),
                (cx + 170, cy + 120),
                (cx - 160, cy + 115)
            ], dtype=np.int32)
            cv2.fillPoly(frame, [wood_poly], (137, 186, 215)) # Warm wood tone in BGR
            cv2.polylines(frame, [wood_poly], True, (60, 100, 140), 1)

            # Draw 4 alignment crosshair fiducial marks on bed
            fids = [
                (p1[0] + 50, p1[1] + 50),
                (p2[0] - 50, p2[1] + 50),
                (p3[0] - 50, p3[1] - 50),
                (p4[0] + 50, p4[1] - 50)
            ]
            for idx, (fx, fy) in enumerate(fids):
                cv2.circle(frame, (fx, fy), 8, (0, 0, 255), -1)
                cv2.circle(frame, (fx, fy), 18, (0, 255, 255), 2)
                cv2.putText(frame, f"P{idx+1}", (fx + 12, fy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            # Watermark overlay
            cv2.putText(frame, "LaserForge Live Camera Feed [SIMULATOR MODE]", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 229, 255), 2)
            cv2.putText(frame, f"FPS: 30.0 | Frame: {self._mock_frame_counter}", (20, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)

        return frame
