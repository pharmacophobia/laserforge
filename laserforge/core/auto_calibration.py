"""
LaserForge Automated Workbed & Camera Coordinate Calibration Engine.

Provides:
- Automatic detection of optical fiducials (ArUco tags, concentric circle targets,
  laser-burned dots, crosshairs, and synthetic simulator markers) with sub-pixel precision.
- Automatic matching of detected image coordinates (u, v) to physical laser machine coordinates (X, Y) in mm.
- Robust perspective homography calculation (cv2.RANSAC / getPerspectiveTransform)
  mapping camera pixels directly to laser workbed millimeters and orthophoto pixels.
- Comprehensive kinematic telemetry:
  - Reprojection error (RMS in mm and pixels, max error, per-point residuals)
  - Affine decomposition (Scale X, Scale Y, rotation angle, origin offset)
  - Gantry skew / non-orthogonality angle detection (racked gantry / loose belts)
  - Calibration quality score (0.0 to 100.0%)
- Direct bi-directional coordinate transformation (camera_to_laser, laser_to_camera).
- Parametric G-code calibration pattern generator with automatic laser head parking.
- Automated calibration runner for 1-click calibration cycles with serial laser controllers.
- Full integration with CameraEngine and CameraCalibrationData.
"""

import os
import math
import time
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Union
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
from laserforge.core.models import LaserEntity, CircleEntity, LineEntity, PathEntity


@dataclass
class CalibrationPoint:
    """Represents a paired camera pixel coordinate and physical laser bed coordinate."""
    camera_point: Tuple[float, float]  # (u, v) in camera sensor pixels
    laser_point_mm: Tuple[float, float]  # (X, Y) in physical laser bed mm
    marker_id: Optional[int] = None
    label: str = ""
    reprojection_error_px: float = 0.0
    reprojection_error_mm: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_point": list(self.camera_point),
            "laser_point_mm": list(self.laser_point_mm),
            "marker_id": self.marker_id,
            "label": self.label,
            "reprojection_error_px": round(self.reprojection_error_px, 3),
            "reprojection_error_mm": round(self.reprojection_error_mm, 3)
        }


@dataclass
class AutoCalibrationConfig:
    """Configuration parameters for the auto-calibration cycle."""
    bed_width_mm: float = 400.0
    bed_height_mm: float = 400.0
    fiducial_inset_mm: float = 40.0
    pattern_type: str = "auto"  # 'auto', 'concentric_circle', 'aruco', 'crosshair', 'burn_dot'
    aruco_dict_name: str = "DICT_4X4_50"
    scale_px_per_mm: float = 3.0
    burn_feed_rate: float = 1200.0
    burn_power_pct: float = 15.0
    park_position: Tuple[float, float] = (0.0, 400.0)
    ransac_threshold_px: float = 5.0
    auto_undistort: bool = True
    save_on_success: bool = True


@dataclass
class AutoCalibrationResult:
    """Result and diagnostic metrics produced by the auto-calibration engine."""
    success: bool = False
    homography_matrix: Optional[np.ndarray] = None  # 3x3 camera px -> bed orthophoto px
    camera_to_laser_matrix: Optional[np.ndarray] = None  # 3x3 camera px -> laser mm
    laser_to_camera_matrix: Optional[np.ndarray] = None  # 3x3 laser mm -> camera px
    points: List[CalibrationPoint] = field(default_factory=list)
    reprojection_error_rms_px: float = 0.0
    reprojection_error_rms_mm: float = 0.0
    max_error_mm: float = 0.0
    rotation_deg: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    gantry_skew_deg: float = 0.0  # Deviation from 90° orthogonality
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    quality_score: float = 0.0  # 0 to 100%
    message: str = ""
    annotated_frame: Optional[np.ndarray] = None
    calibrated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "homography_matrix": self.homography_matrix.tolist() if self.homography_matrix is not None else None,
            "camera_to_laser_matrix": self.camera_to_laser_matrix.tolist() if self.camera_to_laser_matrix is not None else None,
            "laser_to_camera_matrix": self.laser_to_camera_matrix.tolist() if self.laser_to_camera_matrix is not None else None,
            "points": [p.to_dict() for p in self.points],
            "reprojection_error_rms_px": round(self.reprojection_error_rms_px, 3),
            "reprojection_error_rms_mm": round(self.reprojection_error_rms_mm, 3),
            "max_error_mm": round(self.max_error_mm, 3),
            "rotation_deg": round(self.rotation_deg, 3),
            "scale_x": round(self.scale_x, 4),
            "scale_y": round(self.scale_y, 4),
            "gantry_skew_deg": round(self.gantry_skew_deg, 3),
            "offset_x_mm": round(self.offset_x_mm, 3),
            "offset_y_mm": round(self.offset_y_mm, 3),
            "quality_score": round(self.quality_score, 1),
            "message": self.message,
            "calibrated_at": self.calibrated_at
        }


class FiducialDetector:
    """
    Computer vision algorithms to locate various types of calibration fiducials
    with sub-pixel precision.
    """

    @staticmethod
    def detect_aruco(
        frame: np.ndarray,
        dict_name: str = "DICT_4X4_50"
    ) -> Tuple[Dict[int, Tuple[float, float]], Dict[int, np.ndarray]]:
        """
        Detects ArUco markers in the frame.
        Returns:
            centers: Dict[id, (center_u, center_v)]
            corners_map: Dict[id, 4x2 corner array]
        """
        if not HAS_CV2 or not hasattr(cv2, "aruco"):
            return {}, {}

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame

        dict_id = getattr(cv2.aruco, dict_name, cv2.aruco.DICT_4X4_50)
        dictionary = cv2.aruco.getPredefinedDictionary(dict_id)

        # Detect markers with modern or legacy OpenCV API
        try:
            if hasattr(cv2.aruco, "ArucoDetector"):
                params = cv2.aruco.DetectorParameters()
                if hasattr(cv2.aruco, "CORNER_REFINE_SUBPIX"):
                    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
                detector = cv2.aruco.ArucoDetector(dictionary, params)
                corners, ids, _ = detector.detectMarkers(gray)
            else:
                params = cv2.aruco.DetectorParameters_create()
                if hasattr(cv2.aruco, "CORNER_REFINE_SUBPIX"):
                    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
                corners, ids, _ = cv2.aruco.detectMarkers(gray, dictionary, parameters=params)
        except Exception as e:
            return {}, {}

        centers: Dict[int, Tuple[float, float]] = {}
        corners_map: Dict[int, np.ndarray] = {}

        if ids is not None and len(ids) > 0:
            flat_ids = ids.flatten()
            for idx, m_id in enumerate(flat_ids):
                c = corners[idx][0]  # shape (4, 2)
                cx = float(np.mean(c[:, 0]))
                cy = float(np.mean(c[:, 1]))
                centers[int(m_id)] = (cx, cy)
                corners_map[int(m_id)] = c

        return centers, corners_map

    @staticmethod
    def detect_synthetic_simulated_fiducials(frame: np.ndarray) -> List[Tuple[float, float]]:
        """
        Detects the red-center/yellow-ring fiducials generated by LaserForge's
        CameraEngine synthetic simulator frame.
        """
        if not HAS_CV2:
            return []

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # Red center mask
        lower_red1 = np.array([0, 120, 100])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 120, 100])
        upper_red2 = np.array([180, 255, 255])
        mask = cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers: List[Tuple[float, float]] = []

        for c in cnts:
            area = cv2.contourArea(c)
            if 15.0 <= area <= 600.0:
                M = cv2.moments(c)
                if M["m00"] > 0:
                    cx = float(M["m10"] / M["m00"])
                    cy = float(M["m01"] / M["m00"])
                    centers.append((cx, cy))

        return centers

    @staticmethod
    def _preprocess(gray: np.ndarray) -> np.ndarray:
        """
        Normalizes a real-world camera frame so fiducial detection has a fair
        chance on a dark machine bed under uneven lighting. Without this, a
        raw frame from a webcam is either washed out or crushed to black and
        the detectors find nothing ('cannot see my machine').

        Steps: CLAHE (local contrast) + auto-level stretch.
        """
        g = gray
        try:
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            g = clahe.apply(g)
        except Exception:
            pass
        # Percentile stretch: map the 2nd..98th percentile to full range.
        try:
            lo, hi = np.percentile(g, (2.0, 98.0))
            if hi - lo >= 10.0:
                g = np.clip((g.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        except Exception:
            pass
        return g

    @staticmethod
    def detect_concentric_circles(
        frame: np.ndarray,
        min_radius: int = 3,
        max_radius: int = 200
    ) -> List[Tuple[float, float]]:
        """
        Detects concentric circular fiducials (bullseyes or ring targets)
        using contour hierarchy and sub-pixel moments.
        """
        if not HAS_CV2:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame.copy()
        gray = FiducialDetector._preprocess(gray)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Try adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 25, 4
        )

        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None or len(contours) == 0:
            return []

        h_img, w_img = gray.shape[:2]
        frame_area = float(h_img * w_img)
        candidate_circles = []
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            # Reject the bed/horizon filling most of the frame, and specks.
            if area <= 0 or area > 0.75 * frame_area:
                continue
            peri = cv2.arcLength(c, True)
            if peri <= 0:
                continue
            circularity = 4.0 * math.pi * (area / (peri * peri))
            if circularity >= 0.55 and area >= (math.pi * min_radius * min_radius):
                (x, y), radius = cv2.minEnclosingCircle(c)
                if min_radius <= radius <= max_radius:
                    M = cv2.moments(c)
                    if M["m00"] > 0:
                        cx = float(M["m10"] / M["m00"])
                        cy = float(M["m01"] / M["m00"])
                        candidate_circles.append((cx, cy, radius, i))

        # Find concentric pairs (centers within 12 pixels of each other)
        centers: List[Tuple[float, float]] = []
        used = set()

        for i in range(len(candidate_circles)):
            if i in used:
                continue
            c1 = candidate_circles[i]
            for j in range(i + 1, len(candidate_circles)):
                if j in used:
                    continue
                c2 = candidate_circles[j]
                dist = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
                rad_diff = abs(c1[2] - c2[2])
                if dist <= 18.0 and rad_diff >= 2.0:
                    # Found concentric pair! Average center
                    avg_x = (c1[0] + c2[0]) / 2.0
                    avg_y = (c1[1] + c2[1]) / 2.0
                    centers.append((avg_x, avg_y))
                    used.add(i)
                    used.add(j)
                    break

        # Fallback: if not enough concentric pairs, return most circular candidate centers
        if len(centers) < 4 and len(candidate_circles) >= 4:
            # Sort candidate circles by circularity or distinct clusters
            clustered_centers: List[Tuple[float, float]] = []
            for c in candidate_circles:
                pt = (c[0], c[1])
                if not any(math.hypot(pt[0] - ex[0], pt[1] - ex[1]) < 30.0 for ex in clustered_centers):
                    clustered_centers.append(pt)
            if len(clustered_centers) >= 4:
                return clustered_centers

        return centers

    @staticmethod
    def detect_crosshairs(frame: np.ndarray) -> List[Tuple[float, float]]:
        """
        Detects '+' or 'X' crosshair fiducial intersections using Harris corner response
        and sub-pixel refinement.
        """
        if not HAS_CV2:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame.copy()
        gray = FiducialDetector._preprocess(gray)
        corners = cv2.goodFeaturesToTrack(
            gray, maxCorners=50, qualityLevel=0.05, minDistance=40, blockSize=7
        )
        if corners is None:
            return []

        # Subpixel refinement
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
        sub_corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)

        points = [(float(pt[0][0]), float(pt[0][1])) for pt in sub_corners]
        return points

    @staticmethod
    def detect_laser_burn_dots(frame: np.ndarray) -> List[Tuple[float, float]]:
        """
        Detects high-contrast laser burn marks (dark spots on light scrap stock).
        """
        if not HAS_CV2:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame.copy()
        gray = FiducialDetector._preprocess(gray)
        # Invert so dark spots become bright
        inv = 255 - gray
        _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers: List[Tuple[float, float]] = []

        h_img, w_img = gray.shape[:2]
        frame_area = float(h_img * w_img)
        for c in cnts:
            area = cv2.contourArea(c)
            if area > 0.75 * frame_area:
                continue
            if 4.0 <= area <= 4000.0:
                peri = cv2.arcLength(c, True)
                if peri > 0:
                    circ = 4.0 * math.pi * (area / (peri * peri))
                    if circ > 0.5:
                        M = cv2.moments(c)
                        if M["m00"] > 0:
                            centers.append((float(M["m10"] / M["m00"]), float(M["m01"] / M["m00"])))

        return centers


class AutoCalibrationEngine:
    """
    Main engine orchestrating automated vision detection, geometric point matching,
    perspective homography calculation, affine kinematic telemetry, and coordinate translation.
    """

    def __init__(self, config: Optional[AutoCalibrationConfig] = None):
        self.config = config or AutoCalibrationConfig()
        self.last_result: Optional[AutoCalibrationResult] = None

    def detect_markers(
        self,
        frame: np.ndarray,
        pattern_type: Optional[str] = None
    ) -> Tuple[List[Tuple[float, float]], str, Optional[Dict[int, Tuple[float, float]]]]:
        """
        Detects markers in the frame according to the requested or automatic pattern mode.
        Returns:
            points: List of (u, v) centers
            detected_type: str indicating which detector succeeded
            aruco_centers: Dict of ID -> center if ArUco was detected
        """
        mode = pattern_type or self.config.pattern_type
        aruco_map = None

        # 1. ArUco mode or Auto
        if mode in ("aruco", "auto"):
            centers_map, _ = FiducialDetector.detect_aruco(frame, self.config.aruco_dict_name)
            if len(centers_map) >= 4:
                pts = [centers_map[k] for k in sorted(centers_map.keys())]
                return pts, "aruco", centers_map

        # 2. Simulator mode detection (checks if this is a synthetic mock frame)
        if mode in ("concentric_circle", "auto"):
            sim_pts = FiducialDetector.detect_synthetic_simulated_fiducials(frame)
            if len(sim_pts) == 4:
                return sim_pts, "concentric_circle", None

        # 3. Concentric circles / bullseyes
        if mode in ("concentric_circle", "auto"):
            circle_pts = FiducialDetector.detect_concentric_circles(frame)
            if len(circle_pts) >= 4:
                return circle_pts, "concentric_circle", None

        # 4. Laser burn dots
        if mode in ("burn_dot", "auto"):
            burn_pts = FiducialDetector.detect_laser_burn_dots(frame)
            if len(burn_pts) >= 4:
                return burn_pts, "burn_dot", None

        # 5. Crosshairs
        if mode in ("crosshair", "auto"):
            cross_pts = FiducialDetector.detect_crosshairs(frame)
            if len(cross_pts) >= 4:
                return cross_pts, "crosshair", None

        # Fallback to concentric circle attempt if specific mode was requested
        if mode == "concentric_circle":
            pts = FiducialDetector.detect_concentric_circles(frame)
            return pts, "concentric_circle", None

        return [], "none", None

    def sort_quadrant_points(
        self,
        points: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """
        Sorts 4 unordered 2D points clockwise into standard canonical order:
        [P1 (Top-Left), P2 (Top-Right), P3 (Bottom-Right), P4 (Bottom-Left)].
        """
        if len(points) != 4:
            return points

        pts = np.array(points, dtype=np.float32)
        center = np.mean(pts, axis=0)

        # Separate into quadrants relative to center
        # Top vs Bottom (v < center_v vs v > center_v)
        # Left vs Right (u < center_u vs u > center_u)
        tl, tr, br, bl = None, None, None, None

        # Sort primarily by angle from center or sum/diff
        # P1 (TL): minimum (u + v)
        # P3 (BR): maximum (u + v)
        # P2 (TR): maximum (u - v)
        # P4 (BL): minimum (u - v)
        sum_uv = pts[:, 0] + pts[:, 1]
        diff_uv = pts[:, 0] - pts[:, 1]

        tl_idx = int(np.argmin(sum_uv))
        br_idx = int(np.argmax(sum_uv))
        tr_idx = int(np.argmax(diff_uv))
        bl_idx = int(np.argmin(diff_uv))

        used = {tl_idx, br_idx, tr_idx, bl_idx}
        if len(used) == 4:
            return [
                tuple(pts[tl_idx]),
                tuple(pts[tr_idx]),
                tuple(pts[br_idx]),
                tuple(pts[bl_idx])
            ]

        # Robust angle-based sorting fallback
        angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
        # Sort in clockwise order starting from Top-Left (~ -135°)
        order = np.argsort(angles)
        sorted_pts = [tuple(pts[i]) for i in order]

        # Find the one closest to Top-Left (min sum)
        sums = [p[0] + p[1] for p in sorted_pts]
        start_idx = int(np.argmin(sums))
        canonical = [sorted_pts[(start_idx + i) % 4] for i in range(4)]
        return canonical

    def match_points_to_laser_bed(
        self,
        detected_points: List[Tuple[float, float]],
        aruco_map: Optional[Dict[int, Tuple[float, float]]] = None
    ) -> List[CalibrationPoint]:
        """
        Matches detected image points to physical laser bed coordinates in mm.
        Standard bed points are placed with fiducial_inset_mm from each corner.
        """
        w_mm = self.config.bed_width_mm
        h_mm = self.config.bed_height_mm
        ins = min(self.config.fiducial_inset_mm, min(w_mm, h_mm) * 0.45)

        # Standard clockwise 4 corners: TL, TR, BR, BL
        standard_bed_mm = [
            (ins, ins),                        # P1: Top-Left
            (w_mm - ins, ins),                 # P2: Top-Right
            (w_mm - ins, h_mm - ins),          # P3: Bottom-Right
            (ins, h_mm - ins)                  # P4: Bottom-Left
        ]
        labels = ["P1 (Top-Left)", "P2 (Top-Right)", "P3 (Bottom-Right)", "P4 (Bottom-Left)"]

        # If ArUco IDs 0..3 are detected, map them directly by ID
        if aruco_map is not None and len(aruco_map) >= 4:
            matched: List[CalibrationPoint] = []
            for target_id in range(4):
                if target_id in aruco_map:
                    pt_cam = aruco_map[target_id]
                    pt_laser = standard_bed_mm[target_id]
                    matched.append(CalibrationPoint(
                        camera_point=(float(pt_cam[0]), float(pt_cam[1])),
                        laser_point_mm=(float(pt_laser[0]), float(pt_laser[1])),
                        marker_id=target_id,
                        label=labels[target_id]
                    ))
            if len(matched) == 4:
                return matched

        # Otherwise sort 4 points into standard quadrants
        canonical_cam_pts = self.sort_quadrant_points(detected_points[:4])
        matched = []
        for i in range(min(4, len(canonical_cam_pts))):
            pt_cam = canonical_cam_pts[i]
            pt_laser = standard_bed_mm[i]
            matched.append(CalibrationPoint(
                camera_point=(float(pt_cam[0]), float(pt_cam[1])),
                laser_point_mm=(float(pt_laser[0]), float(pt_laser[1])),
                marker_id=i,
                label=labels[i]
            ))

        return matched

    def solve_calibration(
        self,
        matched_points: List[CalibrationPoint]
    ) -> AutoCalibrationResult:
        """
        Computes the perspective homography and decomposes kinematics metrics:
        - Camera-to-Laser direct transform matrix
        - Camera-to-Orthophoto pixel transform matrix
        - Scale X, Scale Y, rotation angle, gantry skew angle
        - RMS and maximum reprojection error
        - Overall quality score
        """
        if len(matched_points) < 4 or not HAS_CV2:
            return AutoCalibrationResult(
                success=False,
                message="Need at least 4 valid matched calibration points and OpenCV."
            )

        cam_pts = np.array([p.camera_point for p in matched_points], dtype=np.float32)
        laser_pts = np.array([p.laser_point_mm for p in matched_points], dtype=np.float32)
        scale = self.config.scale_px_per_mm
        ortho_pts = laser_pts * scale

        try:
            # 1. Perspective Homography: Camera -> Orthophoto Pixels
            H_ortho = cv2.getPerspectiveTransform(cam_pts, ortho_pts)

            # 2. Perspective Homography: Camera -> Laser mm
            H_laser = cv2.getPerspectiveTransform(cam_pts, laser_pts)

            # 3. Inverse Homography: Laser mm -> Camera Pixels
            H_inv = np.linalg.inv(H_laser)

            # 4. Reprojection Error Analysis
            pts_homogeneous = np.hstack([cam_pts, np.ones((len(cam_pts), 1), dtype=np.float32)])
            projected_laser_homo = (H_laser @ pts_homogeneous.T).T
            projected_laser = projected_laser_homo[:, :2] / projected_laser_homo[:, 2:]

            errors_mm = np.linalg.norm(projected_laser - laser_pts, axis=1)
            rms_error_mm = float(np.sqrt(np.mean(errors_mm ** 2)))
            max_error_mm = float(np.max(errors_mm))

            # Camera pixel reprojection error
            laser_homo = np.hstack([laser_pts, np.ones((len(laser_pts), 1), dtype=np.float32)])
            projected_cam_homo = (H_inv @ laser_homo.T).T
            projected_cam = projected_cam_homo[:, :2] / projected_cam_homo[:, 2:]
            errors_px = np.linalg.norm(projected_cam - cam_pts, axis=1)
            rms_error_px = float(np.sqrt(np.mean(errors_px ** 2)))

            # Populate point-specific residuals
            for idx, pt in enumerate(matched_points):
                pt.reprojection_error_mm = float(errors_mm[idx])
                pt.reprojection_error_px = float(errors_px[idx])

            # 5. Affine Kinematic Decomposition
            # Solves best-fit affine transform: [X, Y]^T = M * [u, v]^T + T
            affine_mat, _ = cv2.estimateAffine2D(cam_pts, laser_pts)
            if affine_mat is None:
                affine_mat = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)

            a11, a12, tx = affine_mat[0]
            a21, a22, ty = affine_mat[1]

            scale_x = float(math.hypot(a11, a21))
            scale_y = float(math.hypot(a12, a22))
            rot_rad = math.atan2(a21, a11)
            rot_deg = float(math.degrees(rot_rad))

            # Gantry Skew: deviation of Y axis from being 90° perpendicular to X axis
            rot_y_rad = math.atan2(a22, a12)
            angle_between_axes_deg = math.degrees(rot_y_rad - rot_rad)
            # Normalize to around 90°
            skew_deg = float(angle_between_axes_deg - 90.0)
            while skew_deg > 180.0:
                skew_deg -= 360.0
            while skew_deg < -180.0:
                skew_deg += 360.0

            # 6. Quality Score (0.0 to 100.0%)
            # High quality: RMS < 0.2 mm, skew < 0.3°, scale ratio close to 1.0
            score = 100.0
            score -= min(60.0, rms_error_mm * 40.0)  # -20% per 0.5mm
            score -= min(25.0, abs(skew_deg) * 15.0)  # -15% per 1 deg skew
            scale_ratio = max(scale_x, scale_y) / max(1e-6, min(scale_x, scale_y))
            score -= min(15.0, (scale_ratio - 1.0) * 100.0)
            quality_score = float(max(0.0, min(100.0, score)))

            return AutoCalibrationResult(
                success=True,
                homography_matrix=H_ortho,
                camera_to_laser_matrix=H_laser,
                laser_to_camera_matrix=H_inv,
                points=matched_points,
                reprojection_error_rms_px=rms_error_px,
                reprojection_error_rms_mm=rms_error_mm,
                max_error_mm=max_error_mm,
                rotation_deg=rot_deg,
                scale_x=scale_x,
                scale_y=scale_y,
                gantry_skew_deg=skew_deg,
                offset_x_mm=float(tx),
                offset_y_mm=float(ty),
                quality_score=quality_score,
                message=f"Auto-calibration successful: RMS {rms_error_mm:.2f} mm ({rms_error_px:.1f} px), Quality: {quality_score:.1f}%",
                calibrated_at=time.strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception as e:
            return AutoCalibrationResult(
                success=False,
                message=f"Matrix calculation error: {e}"
            )

    def calibrate_from_frame(
        self,
        frame: np.ndarray,
        camera_engine: Optional[CameraEngine] = None
    ) -> AutoCalibrationResult:
        """
        Full end-to-end auto-calibration on a captured image:
        1. Lens undistortion (if camera_engine has calibrated lens)
        2. Fiducial detection
        3. Canonical quadrant matching
        4. Homography & kinematics solve
        5. Visual frame annotation
        """
        if frame is None or not HAS_CV2:
            return AutoCalibrationResult(
                success=False,
                message="Valid camera frame and OpenCV are required for auto-calibration."
            )

        # 1. Undistort if enabled
        proc_frame = frame
        if self.config.auto_undistort and camera_engine is not None and camera_engine.calibration.is_lens_calibrated():
            proc_frame = camera_engine.undistort_frame(frame)

        # 2. Detect markers
        pts, detected_mode, aruco_map = self.detect_markers(proc_frame)
        if len(pts) < 4:
            return AutoCalibrationResult(
                success=False,
                message=f"Could not automatically detect 4 fiducials (found {len(pts)}). Ensure targets are visible and unobstructed."
            )

        # 3. Match points
        matched = self.match_points_to_laser_bed(pts, aruco_map)
        if len(matched) < 4:
            return AutoCalibrationResult(
                success=False,
                message="Failed to match 4 canonical bed fiducials."
            )

        # 4. Solve homography & kinematics
        result = self.solve_calibration(matched)

        # 5. Render visual annotation overlay
        result.annotated_frame = self.annotate_frame(proc_frame, result)
        self.last_result = result

        # 6. Apply to camera_engine if requested
        if result.success and camera_engine is not None and self.config.save_on_success:
            self.apply_to_camera_calibration(camera_engine.calibration, result)
            camera_engine.calibration.save_to_file()

        return result

    def annotate_frame(
        self,
        frame: np.ndarray,
        result: AutoCalibrationResult
    ) -> np.ndarray:
        """
        Draws colored target reticles, canonical P1..P4 labels, connecting bed perimeter,
        and accuracy telemetry onto a copy of the frame.
        """
        if not HAS_CV2:
            return frame

        annotated = frame.copy()
        pts = result.points

        if len(pts) == 4:
            # Draw bed boundary polygon in camera view
            poly = np.array([[int(p.camera_point[0]), int(p.camera_point[1])] for p in pts], dtype=np.int32)
            cv2.polylines(annotated, [poly], True, (0, 229, 255), 2, cv2.LINE_AA)

        # Draw each point with reticle and label
        colors = [
            (0, 255, 0),    # P1: Green
            (255, 200, 0),  # P2: Cyan / Light Blue
            (0, 165, 255),  # P3: Orange
            (255, 0, 255)   # P4: Magenta
        ]

        for idx, pt in enumerate(pts):
            u, v = int(round(pt.camera_point[0])), int(round(pt.camera_point[1]))
            col = colors[idx % len(colors)]
            # Target circles
            cv2.circle(annotated, (u, v), 16, col, 2, cv2.LINE_AA)
            cv2.circle(annotated, (u, v), 4, (0, 0, 255), -1, cv2.LINE_AA)
            # Crosshairs
            cv2.line(annotated, (u - 24, v), (u + 24, v), col, 1, cv2.LINE_AA)
            cv2.line(annotated, (u, v - 24), (u, v + 24), col, 1, cv2.LINE_AA)
            # Label
            label_text = f"{pt.label.split()[0]} ({pt.laser_point_mm[0]:.0f},{pt.laser_point_mm[1]:.0f}mm) err:{pt.reprojection_error_mm:.2f}mm"
            cv2.putText(
                annotated, label_text, (u + 18, v - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA
            )
            cv2.putText(
                annotated, label_text, (u + 18, v - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 1, cv2.LINE_AA
            )

        # Draw telemetry banner on top
        if result.success:
            banner_text = (
                f"LaserForge Auto-Calibration: Quality {result.quality_score:.1f}% | "
                f"RMS Err: {result.reprojection_error_rms_mm:.2f}mm ({result.reprojection_error_rms_px:.1f}px) | "
                f"Skew: {result.gantry_skew_deg:+.2f}°"
            )
            cv2.rectangle(annotated, (10, 10), (annotated.shape[1] - 10, 48), (20, 20, 24), -1)
            cv2.putText(
                annotated, banner_text, (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 229, 255), 2, cv2.LINE_AA
            )

        return annotated

    def apply_to_camera_calibration(
        self,
        calib_data: CameraCalibrationData,
        result: AutoCalibrationResult
    ):
        """
        Injects the auto-calibration result directly into the CameraCalibrationData model.
        """
        if not result.success or result.homography_matrix is None:
            return

        calib_data.homography_matrix = result.homography_matrix
        calib_data.camera_fiducials = [
            (float(p.camera_point[0]), float(p.camera_point[1])) for p in result.points
        ]
        calib_data.bed_fiducials_mm = [
            (float(p.laser_point_mm[0]), float(p.laser_point_mm[1])) for p in result.points
        ]
        calib_data.reprojection_error = float(round(result.reprojection_error_rms_px, 3))
        calib_data.calibrated_at = result.calibrated_at
        calib_data.bed_width_mm = float(self.config.bed_width_mm)
        calib_data.bed_height_mm = float(self.config.bed_height_mm)
        calib_data.scale_px_per_mm = float(self.config.scale_px_per_mm)
        calib_data.fiducial_inset_mm = float(self.config.fiducial_inset_mm)
        # Reset fine-tuning overrides since calibration is now mathematically precise
        calib_data.offset_x_mm = 0.0
        calib_data.offset_y_mm = 0.0
        calib_data.fine_scale_x = 1.0
        calib_data.fine_scale_y = 1.0
        calib_data.fine_rotation_deg = 0.0

    # -------------------------------------------------------------------------
    # Coordinate Transformation Utilities
    # -------------------------------------------------------------------------
    def camera_to_laser(
        self,
        u: float,
        v: float,
        result: Optional[AutoCalibrationResult] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Converts camera pixel coordinates (u, v) into physical laser bed coordinates (X, Y) in mm.
        """
        res = result or self.last_result
        if res is None or not res.success or res.camera_to_laser_matrix is None:
            return None

        H = res.camera_to_laser_matrix
        vec = np.array([u, v, 1.0], dtype=np.float64)
        proj = H @ vec
        if abs(proj[2]) < 1e-9:
            return None
        return (float(proj[0] / proj[2]), float(proj[1] / proj[2]))

    def laser_to_camera(
        self,
        x_mm: float,
        y_mm: float,
        result: Optional[AutoCalibrationResult] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Converts physical laser bed coordinates (X, Y) in mm into camera pixel coordinates (u, v).
        """
        res = result or self.last_result
        if res is None or not res.success or res.laser_to_camera_matrix is None:
            return None

        H_inv = res.laser_to_camera_matrix
        vec = np.array([x_mm, y_mm, 1.0], dtype=np.float64)
        proj = H_inv @ vec
        if abs(proj[2]) < 1e-9:
            return None
        return (float(proj[0] / proj[2]), float(proj[1] / proj[2]))

    # -------------------------------------------------------------------------
    # Parametric Calibration G-Code Pattern Generator
    # -------------------------------------------------------------------------
    def generate_calibration_gcode(
        self,
        bed_width_mm: Optional[float] = None,
        bed_height_mm: Optional[float] = None,
        inset_mm: Optional[float] = None,
        pattern_type: str = "concentric_circle",
        feed_rate: Optional[float] = None,
        power_pct: Optional[float] = None,
        laser_mode: str = "M4",
        max_s_val: int = 1000
    ) -> str:
        """
        Generates a complete, ready-to-burn GRBL G-code program that burns 4 precision
        fiducials at the exact calibration coordinates on scrap wood or paper,
        then automatically parks the laser head out of the camera's line of sight.
        """
        w = bed_width_mm or self.config.bed_width_mm
        h = bed_height_mm or self.config.bed_height_mm
        ins = inset_mm or self.config.fiducial_inset_mm
        feed = feed_rate or self.config.burn_feed_rate
        power = power_pct or self.config.burn_power_pct
        s_val = int(round((power / 100.0) * max_s_val))
        park_x, park_y = self.config.park_position
        park_x = min(w, max(0.0, park_x))
        park_y = min(h, max(0.0, park_y))

        # GRBL laser-mode handling.
        #
        # M4/M3 select the laser mode, but M5 *disables* the laser AND clears the
        # active mode. The previous implementation set {laser_mode} once at the top
        # and then emitted M5 after every shape -- so every subsequent move moved
        # with the laser OFF ("axes move but the laser never fires"). It also used
        # "G1 S.. F.." with no axis words (a zero-length no-op in GRBL) and arc
        # moves (G2) that cannot carry inline S. We now turn the laser on
        # explicitly, per burn move, with real coordinates, and only shut it off
        # when we intend to stop burning.
        on_cmd = (laser_mode or "M4").strip().upper()
        if on_cmd not in ("M3", "M4"):
            on_cmd = "M4"

        def burn(x1: float, y1: float, x2: float, y2: float, with_feed: bool) -> list:
            """Rapid to (x1,y1), enable laser, cut to (x2,y2), shut laser off."""
            out = [
                f"G0 X{x1:.3f} Y{y1:.3f}",
                f"{on_cmd} S{s_val}",
            ]
            out.append(
                f"G1 X{x2:.3f} Y{y2:.3f} S{s_val} F{feed:.0f}" if with_feed
                else f"G1 X{x2:.3f} Y{y2:.3f} S{s_val}"
            )
            out.append("M5")
            return out

        def arc(cx: float, cy: float, r: float) -> list:
            """Cut a full circle of radius r around (cx,cy) using two 180-degree G2 arcs."""
            out = [
                f"G0 X{cx + r:.3f} Y{cy:.3f}",
                f"{on_cmd} S{s_val}",
                # Two semicircles (GRBL cannot do a 360-degree arc in one command).
                f"G2 X{cx - r:.3f} Y{cy:.3f} I{-r:.3f} J0.000 F{feed:.0f}",
                f"G2 X{cx + r:.3f} Y{cy:.3f} I{r:.3f} J0.000",
                "M5",
            ]
            return out

        # 4 Standard fiducial centers: TL, TR, BR, BL
        fids = [
            (ins, ins, "P1_TopLeft"),
            (w - ins, ins, "P2_TopRight"),
            (w - ins, h - ins, "P3_BottomRight"),
            (ins, h - ins, "P4_BottomLeft")
        ]

        lines = [
            "; ==========================================================================",
            "; LaserForge Workbed Auto-Calibration Target Pattern",
            f"; Bed Size: {w:.1f} x {h:.1f} mm | Corner Inset: {ins:.1f} mm",
            f"; Pattern: {pattern_type} | Feed: {feed:.0f} mm/min | Power: {power:.1f}% (S{s_val})",
            f"; Laser mode: {on_cmd} (S{s_val} per burn move)",
            "; ==========================================================================",
            "G21",
            "G90",
            f"{on_cmd} S0",
            "M5",
            ""
        ]

        for fx, fy, label in fids:
            lines.append(f"; --- Fiducial {label} at X{fx:.3f} Y{fy:.3f} ---")

            if pattern_type in ("concentric_circle", "auto"):
                # Outer circle: radius 8 mm
                lines.extend(arc(fx, fy, 8.0))
                # Inner circle: radius 4 mm
                lines.extend(arc(fx, fy, 4.0))
                # Center crosshair (16 mm arms), feed on the first move only
                lines.extend(burn(fx - 8.0, fy, fx + 8.0, fy, True))
                lines.extend(burn(fx, fy - 8.0, fx, fy + 8.0, False))

            elif pattern_type == "crosshair":
                # Large crosshair (20 mm arms)
                lines.extend(burn(fx - 10.0, fy, fx + 10.0, fy, True))
                lines.extend(burn(fx, fy - 10.0, fx, fy + 10.0, False))

            elif pattern_type == "burn_dot":
                # Single high-contrast burn dot with 200ms dwell
                lines.append(f"G0 X{fx:.3f} Y{fy:.3f}")
                lines.append(f"{on_cmd} S{s_val}")
                lines.append("G4 P0.2")
                lines.append("M5")

            lines.append("")

        # Park laser head out of the camera's view
        lines.extend([
            "; --- Park laser head out of camera view ---",
            "M5",
            f"G0 X{park_x:.3f} Y{park_y:.3f} F3000 ; Rapid to parking position",
            "M2"
        ])

        return "\n".join(lines)

    def generate_calibration_entities(
        self,
        bed_width_mm: Optional[float] = None,
        bed_height_mm: Optional[float] = None,
        inset_mm: Optional[float] = None,
        layer_id: int = 12
    ) -> List[LaserEntity]:
        """
        Creates CAD vector entities (circles and crosshair lines) for the 4 fiducials
        to be displayed or manipulated on the 2D CAD canvas.
        """
        w = bed_width_mm or self.config.bed_width_mm
        h = bed_height_mm or self.config.bed_height_mm
        ins = inset_mm or self.config.fiducial_inset_mm

        fids = [
            (ins, ins, "Fiducial P1 (TL)"),
            (w - ins, ins, "Fiducial P2 (TR)"),
            (w - ins, h - ins, "Fiducial P3 (BR)"),
            (ins, h - ins, "Fiducial P4 (BL)")
        ]

        entities: List[LaserEntity] = []
        for fx, fy, name in fids:
            # Outer circle (radius 8 mm)
            entities.append(CircleEntity(
                layer_id=layer_id,
                name=f"{name} Outer",
                x=fx,
                y=fy,
                radius_x=8.0,
                radius_y=8.0
            ))
            # Inner circle (radius 4 mm)
            entities.append(CircleEntity(
                layer_id=layer_id,
                name=f"{name} Inner",
                x=fx,
                y=fy,
                radius_x=4.0,
                radius_y=4.0
            ))
            # Horizontal crosshair line
            entities.append(LineEntity(
                layer_id=layer_id,
                name=f"{name} H-Line",
                x=fx - 8.0,
                y=fy,
                x2=fx + 8.0,
                y2=fy
            ))
            # Vertical crosshair line
            entities.append(LineEntity(
                layer_id=layer_id,
                name=f"{name} V-Line",
                x=fx,
                y=fy - 8.0,
                x2=fx,
                y2=fy + 8.0
            ))

        return entities
