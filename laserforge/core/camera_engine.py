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
    device_index: int = 0
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

    def is_lens_calibrated(self) -> bool:
        return self.camera_matrix is not None and self.distortion_coeffs is not None

    def is_bed_aligned(self) -> bool:
        return self.homography_matrix is not None

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
            "bed_fiducials_mm": self.bed_fiducials_mm
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CameraCalibrationData":
        k_list = d.get("camera_matrix")
        d_list = d.get("distortion_coeffs")
        h_list = d.get("homography_matrix")

        return cls(
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
            bed_fiducials_mm=[tuple(p) for p in d.get("bed_fiducials_mm", [])]
        )

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
                return cls.from_dict(data)
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
        self.is_mock: bool = False
        self._mock_frame_counter: int = 0

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
                    if cap.isOpened():
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

        # Fallback probe for index 0 if no /dev/video* matched
        if not cameras:
            try:
                cap = cv2.VideoCapture(0)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cameras.append({
                        "index": 0,
                        "name": f"Default USB Camera ({w}x{h})",
                        "device_path": "/dev/video0",
                        "is_mock": False
                    })
                    cap.release()
            except Exception:
                pass

        # Always append Simulated Camera for testing / development
        cameras.append({
            "index": -1,
            "name": "Simulated Overhead Bed Camera (Demo / Test Mode)",
            "device_path": "mock://overhead_bed",
            "is_mock": True
        })

        return cameras

    def open_camera(self, device_index: int = 0, width: int = 1920, height: int = 1080) -> bool:
        """
        Opens camera stream at specified resolution.
        """
        self.close_camera()

        if device_index == -1 or not HAS_CV2:
            self.is_mock = True
            self.calibration.device_index = -1
            self.calibration.device_name = "Simulated Overhead Bed Camera"
            self.calibration.resolution = (width, height)
            return True

        try:
            self.cap = cv2.VideoCapture(device_index)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.is_mock = False
                self.calibration.device_index = device_index
                actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.calibration.resolution = (actual_w, actual_h)
                return True
        except Exception as e:
            print(f"Could not open physical camera {device_index}: {e}")

        # Fallback to simulated
        self.is_mock = True
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

    def capture_frame(self, draw_guides: bool = False) -> Optional[np.ndarray]:
        """
        Captures raw camera frame (BGR uint8).
        """
        if self.is_mock:
            return self._generate_synthetic_camera_frame(draw_guides=draw_guides)

        # Auto-open camera if not currently open but a valid physical device is configured
        if self.cap is None and self.calibration.device_index >= 0 and HAS_CV2:
            self.open_camera(self.calibration.device_index, *self.calibration.resolution)

        if self.cap is None or not self.cap.isOpened():
            return self._generate_synthetic_camera_frame(draw_guides=draw_guides)

        try:
            # Drain stale buffer frames on V4L2 devices to ensure a fresh image
            for _ in range(2):
                self.cap.grab()
            ret, frame = self.cap.read()
            if not ret or frame is None:
                return self._generate_synthetic_camera_frame(draw_guides=draw_guides)
            return frame
        except Exception as e:
            print(f"Error capturing camera frame: {e}")
            return self._generate_synthetic_camera_frame(draw_guides=draw_guides)

    def undistort_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Corrects lens barrel/pincushion distortion using calibrated camera matrix K and D.
        """
        if not HAS_CV2 or not self.calibration.is_lens_calibrated():
            return frame

        try:
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
                warped = cv2.warpPerspective(undist, H, (out_w, out_h))
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
            self.calibration.save_to_file()
            return True
        except Exception as e:
            print(f"Homography error: {e}")
            return False

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
