"""
LaserForge Ultra-Wide Fisheye Lens Calibration & Rectification Engine.

Provides lens un-distortion and camera rectification for wide-angle laser enclosure
lid cameras (120° to 170° FOV) using the OpenCV Fisheye camera model:
- Fisheye distortion coefficients (k1, k2, k3, k4) and camera intrinsic matrix K
- Real-time zero-copy undistortion mapping (cv2.fisheye.initUndistortRectifyMap)
- Automatic FOV scaling to prevent black vignette border clipping
- Checkerboard pattern detection and camera matrix solver
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
import numpy as np
import cv2


@dataclass
class FisheyeCalibrationData:
    """Fisheye camera matrix and distortion parameters."""
    k1: float = -0.12
    k2: float = 0.03
    k3: float = 0.00
    k4: float = 0.00
    fx: float = 800.0
    fy: float = 800.0
    cx: float = 640.0
    cy: float = 360.0
    balance: float = 0.0   # 0.0 = retain all pixels, 1.0 = zoom in to crop borders


class FisheyeRectifier:
    """
    Applies high-speed hardware-accelerated undistortion to wide-angle laser camera frames.
    """
    def __init__(self, calib: Optional[FisheyeCalibrationData] = None):
        self.calib = calib or FisheyeCalibrationData()
        self._map1: Optional[np.ndarray] = None
        self._map2: Optional[np.ndarray] = None
        self._cached_shape: Optional[Tuple[int, int]] = None

    def update_calibration(self, calib: FisheyeCalibrationData):
        self.calib = calib
        self._map1 = None
        self._map2 = None
        self._cached_shape = None

    def _init_maps(self, width: int, height: int):
        """Precomputes lookup tables (LUT) for instant 60 FPS cv2.remap."""
        c = self.calib
        cx = c.cx if c.cx > 0 else width / 2.0
        cy = c.cy if c.cy > 0 else height / 2.0
        fx = c.fx if c.fx > 0 else max(width, height) * 0.75
        fy = c.fy if c.fy > 0 else max(width, height) * 0.75

        K = np.array([
            [fx, 0.0, cx],
            [0.0, fy, cy],
            [0.0, 0.0, 1.0]
        ], dtype=np.float64)

        D = np.array([c.k1, c.k2, c.k3, c.k4], dtype=np.float64)

        # Generate new camera matrix based on balance parameter
        dim = (width, height)
        new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
            K, D, dim, np.eye(3), balance=c.balance
        )

        self._map1, self._map2 = cv2.fisheye.initUndistortRectifyMap(
            K, D, np.eye(3), new_K, dim, cv2.CV_16SC2
        )
        self._cached_shape = (width, height)

    def undistort(self, frame: np.ndarray) -> np.ndarray:
        """
        Removes fisheye barrel distortion from a BGR or grayscale video frame.
        """
        if frame is None or frame.size == 0:
            return frame

        h, w = frame.shape[:2]
        if self._map1 is None or self._cached_shape != (w, h):
            self._init_maps(w, h)

        return cv2.remap(
            frame, self._map1, self._map2,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT
        )

    @classmethod
    def calibrate_from_checkerboard(
        cls,
        images: List[np.ndarray],
        pattern_size: Tuple[int, int] = (9, 6),
        square_size_mm: float = 25.0
    ) -> Optional[FisheyeCalibrationData]:
        """
        Computes fisheye camera parameters from a series of checkerboard images.
        """
        subpix_criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
        calibration_flags = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC + cv2.fisheye.CALIB_CHECK_COND + cv2.fisheye.CALIB_FIX_SKEW

        objp = np.zeros((1, pattern_size[0] * pattern_size[1], 3), np.float32)
        objp[0, :, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2) * square_size_mm

        objpoints = []
        imgpoints = []
        img_shape = None

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            if img_shape is None:
                img_shape = gray.shape[::-1]

            ret, corners = cv2.findChessboardCorners(gray, pattern_size, cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK + cv2.CALIB_CB_NORMALIZE_IMAGE)
            if ret:
                objpoints.append(objp)
                refined = cv2.cornerSubPix(gray, corners, (3, 3), (-1, -1), subpix_criteria)
                imgpoints.append(refined)

        if len(objpoints) < 3 or img_shape is None:
            return None

        N_OK = len(objpoints)
        K = np.zeros((3, 3))
        D = np.zeros((4, 1))
        rvecs = [np.zeros((1, 1, 3), dtype=np.float64) for _ in range(N_OK)]
        tvecs = [np.zeros((1, 1, 3), dtype=np.float64) for _ in range(N_OK)]

        rms, _, _, _, _ = cv2.fisheye.calibrate(
            objpoints,
            imgpoints,
            img_shape,
            K,
            D,
            rvecs,
            tvecs,
            calibration_flags,
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
        )

        return FisheyeCalibrationData(
            k1=float(D[0, 0]),
            k2=float(D[1, 0]),
            k3=float(D[2, 0]),
            k4=float(D[3, 0]),
            fx=float(K[0, 0]),
            fy=float(K[1, 1]),
            cx=float(K[0, 2]),
            cy=float(K[1, 2])
        )
