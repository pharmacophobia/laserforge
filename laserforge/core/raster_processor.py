"""
LaserForge Raster Image & Advanced Photograph Processor.
Converts photographs and graphics into optimized laser raster scanlines via
Floyd-Steinberg, Atkinson, Jarvis-Judice-Ninke, Stucki, Halftone Screen,
Thresholding, and Grayscale laser power modulation.
Includes unsharp masking, adaptive histogram equalization (CLAHE), gamma curves,
and material engraving simulation.
"""

from typing import List, Tuple, Optional, Dict, Any
import math
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from laserforge.core.gpu_accelerator import GPUAccelerator

try:
    import numba
    HAS_NUMBA = True

    @numba.jit(nopython=True, fastmath=True)
    def _numba_floyd_steinberg(arr: np.ndarray) -> np.ndarray:
        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = old_val - new_val
                out[y, x] = 1 if new_val == 0.0 else 0
                if x + 1 < w: buf[y, x + 1] += err * (7.0 / 16.0)
                if y + 1 < h:
                    if x > 0: buf[y + 1, x - 1] += err * (3.0 / 16.0)
                    buf[y + 1, x] += err * (5.0 / 16.0)
                    if x + 1 < w: buf[y + 1, x + 1] += err * (1.0 / 16.0)
        return out

    @numba.jit(nopython=True, fastmath=True)
    def _numba_atkinson(arr: np.ndarray) -> np.ndarray:
        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = (old_val - new_val) / 8.0
                out[y, x] = 1 if new_val == 0.0 else 0
                if x + 1 < w: buf[y, x + 1] += err
                if x + 2 < w: buf[y, x + 2] += err
                if y + 1 < h:
                    if x > 0: buf[y + 1, x - 1] += err
                    buf[y + 1, x] += err
                    if x + 1 < w: buf[y + 1, x + 1] += err
                if y + 2 < h: buf[y + 2, x] += err
        return out

    @numba.jit(nopython=True, fastmath=True)
    def _numba_jarvis(arr: np.ndarray) -> np.ndarray:
        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        div = 48.0
        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = old_val - new_val
                out[y, x] = 1 if new_val == 0.0 else 0
                if x + 1 < w: buf[y, x + 1] += err * (7.0 / div)
                if x + 2 < w: buf[y, x + 2] += err * (5.0 / div)
                if y + 1 < h:
                    if x >= 2: buf[y + 1, x - 2] += err * (3.0 / div)
                    if x >= 1: buf[y + 1, x - 1] += err * (5.0 / div)
                    buf[y + 1, x] += err * (7.0 / div)
                    if x + 1 < w: buf[y + 1, x + 1] += err * (5.0 / div)
                    if x + 2 < w: buf[y + 1, x + 2] += err * (3.0 / div)
                if y + 2 < h:
                    if x >= 2: buf[y + 2, x - 2] += err * (1.0 / div)
                    if x >= 1: buf[y + 2, x - 1] += err * (3.0 / div)
                    buf[y + 2, x] += err * (5.0 / div)
                    if x + 1 < w: buf[y + 2, x + 1] += err * (3.0 / div)
                    if x + 2 < w: buf[y + 2, x + 2] += err * (1.0 / div)
        return out

    @numba.jit(nopython=True, fastmath=True)
    def _numba_stucki(arr: np.ndarray) -> np.ndarray:
        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        div = 42.0
        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = old_val - new_val
                out[y, x] = 1 if new_val == 0.0 else 0
                if x + 1 < w: buf[y, x + 1] += err * (8.0 / div)
                if x + 2 < w: buf[y, x + 2] += err * (4.0 / div)
                if y + 1 < h:
                    if x >= 2: buf[y + 1, x - 2] += err * (2.0 / div)
                    if x >= 1: buf[y + 1, x - 1] += err * (4.0 / div)
                    buf[y + 1, x] += err * (8.0 / div)
                    if x + 1 < w: buf[y + 1, x + 1] += err * (4.0 / div)
                    if x + 2 < w: buf[y + 1, x + 2] += err * (2.0 / div)
                if y + 2 < h:
                    if x >= 2: buf[y + 2, x - 2] += err * (1.0 / div)
                    if x >= 1: buf[y + 2, x - 1] += err * (2.0 / div)
                    buf[y + 2, x] += err * (4.0 / div)
                    if x + 1 < w: buf[y + 2, x + 1] += err * (2.0 / div)
                    if x + 2 < w: buf[y + 2, x + 2] += err * (1.0 / div)
        return out

    @numba.jit(nopython=True, fastmath=True)
    def _numba_extract_segments(raster_arr: np.ndarray, origin_x_mm: float, line_interval_mm: float, bidirectional: bool, is_grayscale: bool):
        h, w = raster_arr.shape
        max_segs = h * (w // 2 + 1)
        out_row = np.empty(max_segs, dtype=np.int32)
        out_x1 = np.empty(max_segs, dtype=np.float32)
        out_x2 = np.empty(max_segs, dtype=np.float32)
        out_p = np.empty(max_segs, dtype=np.float32)
        out_rev = np.empty(max_segs, dtype=np.bool_)
        count = 0

        for row in range(h):
            rev = bidirectional and (row % 2 == 1)
            in_seg = False
            start_col = 0
            seg_power = 0.0

            col_start = (w - 1) if rev else 0
            col_end = -1 if rev else w
            col_step = -1 if rev else 1

            for col in range(col_start, col_end, col_step):
                val = raster_arr[row, col]
                burn = (val > 0)
                if burn:
                    if not in_seg:
                        in_seg = True
                        start_col = col
                        seg_power = (val / 255.0) if is_grayscale else 1.0
                    else:
                        if is_grayscale and abs((val / 255.0) - seg_power) > 0.05:
                            x1 = origin_x_mm + (start_col * line_interval_mm)
                            x2 = origin_x_mm + (col * line_interval_mm)
                            out_row[count] = row
                            out_x1[count] = x1
                            out_x2[count] = x2
                            out_p[count] = seg_power
                            out_rev[count] = rev
                            count += 1
                            start_col = col
                            seg_power = val / 255.0
                else:
                    if in_seg:
                        in_seg = False
                        x1 = origin_x_mm + (start_col * line_interval_mm)
                        x2 = origin_x_mm + (col * line_interval_mm)
                        out_row[count] = row
                        out_x1[count] = x1
                        out_x2[count] = x2
                        out_p[count] = seg_power
                        out_rev[count] = rev
                        count += 1

            if in_seg:
                col = -1 if rev else w
                x1 = origin_x_mm + (start_col * line_interval_mm)
                x2 = origin_x_mm + (col * line_interval_mm)
                out_row[count] = row
                out_x1[count] = x1
                out_x2[count] = x2
                out_p[count] = seg_power
                out_rev[count] = rev
                count += 1

        return out_row[:count], out_x1[:count], out_x2[:count], out_p[:count], out_rev[:count]

except ImportError:
    HAS_NUMBA = False



class RasterProcessor:

    MATERIAL_PRESETS = {
        "Wood / Birch Plywood": {
            "mode": "Floyd-Steinberg",
            "contrast": 1.15,
            "brightness": 0.05,
            "gamma": 1.4,
            "sharpen": 1.2,
            "invert": False,
            "equalize": False,
            "bg_color": (215, 186, 137),  # Warm basswood
            "burn_color": (44, 22, 8),     # Charred dark brown
        },
        "Black Slate Coaster": {
            "mode": "Jarvis",
            "contrast": 1.35,
            "brightness": 0.10,
            "gamma": 1.2,
            "sharpen": 1.5,
            "invert": True,  # Slate engraves white on dark stone
            "equalize": True,
            "bg_color": (30, 30, 36),     # Dark slate
            "burn_color": (240, 240, 245), # Crisp white stone etch
        },
        "Anodized Aluminum (Black)": {
            "mode": "Atkinson",
            "contrast": 1.40,
            "brightness": 0.05,
            "gamma": 1.1,
            "sharpen": 1.4,
            "invert": True,  # Vaporizes dark anodize to raw silver
            "equalize": False,
            "bg_color": (26, 26, 26),     # Matte black metal
            "burn_color": (255, 255, 255), # Raw bright silver
        },
        "White Ceramic Tile (Norton Method)": {
            "mode": "Stucki",
            "contrast": 1.45,
            "brightness": -0.05,
            "gamma": 1.3,
            "sharpen": 1.8,
            "invert": True,
            "equalize": True,
            "bg_color": (248, 249, 250),  # White porcelain
            "burn_color": (17, 17, 17),    # Fused titanium black
        },
        "Dark Acrylic": {
            "mode": "Halftone",
            "contrast": 1.20,
            "brightness": 0.0,
            "gamma": 1.1,
            "sharpen": 1.0,
            "invert": True,  # Frosted white vapor
            "equalize": False,
            "bg_color": (20, 20, 20),     # Glossy dark acrylic
            "burn_color": (224, 224, 224), # Frosted white mark
        },
        "Leather / Leatherette": {
            "mode": "Atkinson",
            "contrast": 0.95,
            "brightness": 0.05,
            "gamma": 1.5,  # Soft gamma to prevent over-charring
            "sharpen": 0.8,
            "invert": False,
            "equalize": False,
            "bg_color": (141, 85, 36),    # Saddle tan leather
            "burn_color": (31, 15, 4),     # Deep scorched brown
        },
        "High-Contrast Portrait": {
            "mode": "Jarvis",
            "contrast": 1.30,
            "brightness": 0.0,
            "gamma": 1.35,
            "sharpen": 1.6,
            "invert": False,
            "equalize": True,
            "bg_color": (225, 200, 160),
            "burn_color": (30, 15, 5),
        }
    }

    @staticmethod
    def process_image(
        img: Image.Image,
        target_width_mm: float,
        target_height_mm: float,
        line_interval_mm: float = 0.1,
        mode: str = "Floyd-Steinberg",
        invert: bool = False,
        contrast: float = 1.0,
        brightness: float = 0.0,
        threshold_val: int = 128,
        gamma: float = 1.0,
        sharpen: float = 0.0,
        equalize: bool = False,
        white_clip: int = 255,
        black_clip: int = 0,
        halftone_cell_size: float = 6.0,
        halftone_angle_deg: float = 45.0
    ) -> np.ndarray:
        """
        Processes a PIL Image with advanced laser photographic preparation and returns a 2D numpy array:
        - For 1-bit modes (Floyd-Steinberg, Atkinson, Jarvis, Stucki, Halftone, Threshold):
          uint8 array where 1 = laser ON (burn) and 0 = laser OFF (no burn).
        - For Grayscale mode:
          uint8 array with values 0 (0% laser power) to 255 (100% max laser power).
        """
        cols = max(1, int(round(target_width_mm / line_interval_mm)))
        rows = max(1, int(round(target_height_mm / line_interval_mm)))

        # Convert to Grayscale (L)
        gray = img.convert("L")

        # 1. Equalization / CLAHE (Adaptive Histogram Equalization for balanced exposure)
        if equalize:
            if HAS_CV2:
                cv_img = np.array(gray)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                gray = Image.fromarray(clahe.apply(cv_img))
            else:
                from PIL import ImageOps
                gray = ImageOps.equalize(gray)

        # 2. Contrast and Brightness
        if contrast != 1.0:
            enhancer = ImageEnhance.Contrast(gray)
            gray = enhancer.enhance(contrast)
        if brightness != 0.0:
            enhancer = ImageEnhance.Brightness(gray)
            gray = enhancer.enhance(1.0 + brightness)

        # 3. Sharpening / Unsharp Masking (High frequency edge enhancement, CUDA / OpenCV accelerated)
        if sharpen > 0.0:
            if GPUAccelerator.is_cuda_active():
                sharp_arr = GPUAccelerator.cuda_unsharp_mask(np.array(gray), amount=sharpen, radius=1.5)
                gray = Image.fromarray(sharp_arr)
            elif HAS_CV2:
                cv_img = np.array(gray, dtype=np.float32)
                blur = cv2.GaussianBlur(cv_img, (0, 0), sigmaX=1.5)
                # unsharp mask = img + sharpen * (img - blur)
                cv_sharp = cv_img + sharpen * (cv_img - blur)
                cv_sharp = np.clip(cv_sharp, 0, 255).astype(np.uint8)
                gray = Image.fromarray(cv_sharp)
            else:
                radius = 1.5
                percent = int(sharpen * 100)
                gray = gray.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent))

        # 4. Resize with high quality Lanczos filter
        resized = gray.resize((cols, rows), Image.Resampling.LANCZOS)
        arr = np.array(resized, dtype=np.float32)

        # 5. Gamma Correction: I_out = 255 * (I_in / 255) ^ (1 / gamma)
        # Gamma > 1 lifts midtones (prevents muddy solid dark burns on wood)
        if gamma != 1.0 and gamma > 0.01:
            arr = 255.0 * np.power(np.clip(arr / 255.0, 0.0, 1.0), 1.0 / gamma)

        # 6. White & Black Cutoff Clipping
        if black_clip > 0 or white_clip < 255:
            span = max(1.0, float(white_clip - black_clip))
            arr = np.clip((arr - black_clip) / span * 255.0, 0.0, 255.0)

        # 7. Invert if requested (Laser marks light on dark material, e.g. slate or anodized aluminum)
        if invert:
            arr = 255.0 - arr

        # Mode Selection
        normalized_mode = mode.lower().replace(" ", "").replace("-", "").replace("_", "")

        if "grayscale" in normalized_mode:
            # Grayscale PWM: 255 is white in image, so burn power is 255 - pixel
            burn_power = 255.0 - arr
            return np.clip(burn_power, 0, 255).astype(np.uint8)

        elif "threshold" in normalized_mode:
            # Binary threshold: dark pixel <= threshold_val burns
            return (arr <= threshold_val).astype(np.uint8)

        elif "atkinson" in normalized_mode:
            return RasterProcessor._dither_atkinson_arr(arr)

        elif "jarvis" in normalized_mode or "jjn" in normalized_mode:
            return RasterProcessor._dither_jarvis_arr(arr)

        elif "stucki" in normalized_mode:
            return RasterProcessor._dither_stucki_arr(arr)

        elif "halftone" in normalized_mode:
            return RasterProcessor._dither_halftone_arr(arr, halftone_cell_size, halftone_angle_deg)

        elif "ordered" in normalized_mode or "bayer" in normalized_mode:
            return GPUAccelerator.cuda_ordered_dither(arr)

        else:
            # Default: Floyd-Steinberg
            return RasterProcessor._dither_floyd_steinberg_arr(arr)

    @staticmethod
    def _dither_floyd_steinberg_arr(arr: np.ndarray) -> np.ndarray:
        """Floyd-Steinberg error diffusion on a 2D float array (Numba accelerated)."""
        if HAS_NUMBA:
            try:
                return _numba_floyd_steinberg(arr)
            except Exception:
                pass

        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)

        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = old_val - new_val
                out[y, x] = 1 if new_val == 0.0 else 0

                if x + 1 < w:
                    buf[y, x + 1] += err * (7.0 / 16.0)
                if y + 1 < h:
                    if x > 0:
                        buf[y + 1, x - 1] += err * (3.0 / 16.0)
                    buf[y + 1, x] += err * (5.0 / 16.0)
                    if x + 1 < w:
                        buf[y + 1, x + 1] += err * (1.0 / 16.0)

        return out

    @staticmethod
    def _dither_atkinson_arr(arr: np.ndarray) -> np.ndarray:
        """Atkinson error diffusion algorithm (Numba accelerated)."""
        if HAS_NUMBA:
            try:
                return _numba_atkinson(arr)
            except Exception:
                pass

        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)

        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = (old_val - new_val) / 8.0
                out[y, x] = 1 if new_val == 0.0 else 0

                if x + 1 < w: buf[y, x + 1] += err
                if x + 2 < w: buf[y, x + 2] += err
                if y + 1 < h:
                    if x > 0: buf[y + 1, x - 1] += err
                    buf[y + 1, x] += err
                    if x + 1 < w: buf[y + 1, x + 1] += err
                if y + 2 < h: buf[y + 2, x] += err

        return out

    @staticmethod
    def _dither_jarvis_arr(arr: np.ndarray) -> np.ndarray:
        """
        Jarvis, Judice, and Ninke (JJN) 12-neighbor error diffusion (Numba accelerated).
        Produces the smoothest tonal transitions for portraits and fine art on laser diode engravers.
        """
        if HAS_NUMBA:
            try:
                return _numba_jarvis(arr)
            except Exception:
                pass

        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        div = 48.0

        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = old_val - new_val
                out[y, x] = 1 if new_val == 0.0 else 0

                # Row y
                if x + 1 < w: buf[y, x + 1] += err * (7.0 / div)
                if x + 2 < w: buf[y, x + 2] += err * (5.0 / div)

                # Row y + 1
                if y + 1 < h:
                    if x >= 2: buf[y + 1, x - 2] += err * (3.0 / div)
                    if x >= 1: buf[y + 1, x - 1] += err * (5.0 / div)
                    buf[y + 1, x] += err * (7.0 / div)
                    if x + 1 < w: buf[y + 1, x + 1] += err * (5.0 / div)
                    if x + 2 < w: buf[y + 1, x + 2] += err * (3.0 / div)

                # Row y + 2
                if y + 2 < h:
                    if x >= 2: buf[y + 2, x - 2] += err * (1.0 / div)
                    if x >= 1: buf[y + 2, x - 1] += err * (3.0 / div)
                    buf[y + 2, x] += err * (5.0 / div)
                    if x + 1 < w: buf[y + 2, x + 1] += err * (3.0 / div)
                    if x + 2 < w: buf[y + 2, x + 2] += err * (1.0 / div)

        return out

    @staticmethod
    def _dither_stucki_arr(arr: np.ndarray) -> np.ndarray:
        """
        Stucki error diffusion algorithm (Numba accelerated).
        Faster decaying diffusion than JJN, preserving ultra-crisp edges and photographic textures.
        """
        if HAS_NUMBA:
            try:
                return _numba_stucki(arr)
            except Exception:
                pass

        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        div = 42.0

        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = old_val - new_val
                out[y, x] = 1 if new_val == 0.0 else 0

                # Row y
                if x + 1 < w: buf[y, x + 1] += err * (8.0 / div)
                if x + 2 < w: buf[y, x + 2] += err * (4.0 / div)

                # Row y + 1
                if y + 1 < h:
                    if x >= 2: buf[y + 1, x - 2] += err * (2.0 / div)
                    if x >= 1: buf[y + 1, x - 1] += err * (4.0 / div)
                    buf[y + 1, x] += err * (8.0 / div)
                    if x + 1 < w: buf[y + 1, x + 1] += err * (4.0 / div)
                    if x + 2 < w: buf[y + 1, x + 2] += err * (2.0 / div)

                # Row y + 2
                if y + 2 < h:
                    if x >= 2: buf[y + 2, x - 2] += err * (1.0 / div)
                    if x >= 1: buf[y + 2, x - 1] += err * (2.0 / div)
                    buf[y + 2, x] += err * (4.0 / div)
                    if x + 1 < w: buf[y + 2, x + 1] += err * (2.0 / div)
                    if x + 2 < w: buf[y + 2, x + 2] += err * (1.0 / div)

        return out

    @staticmethod
    def _dither_halftone_arr(arr: np.ndarray, cell_size: float = 6.0, angle_deg: float = 45.0) -> np.ndarray:
        """
        High-speed vectorized Amplitude Modulated (AM) Halftone Dot Screening.
        Generates circular laser burn dots angled at 45 degrees, ideal for graphic arts, wood, and stone.
        """
        h, w = arr.shape
        cell_size = max(2.0, float(cell_size))
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        y_coords, x_coords = np.mgrid[0:h, 0:w].astype(np.float32)

        # Rotated coordinate space
        rot_x = x_coords * cos_a - y_coords * sin_a
        rot_y = x_coords * sin_a + y_coords * cos_a

        # Local offset within grid cell [-cell_size/2, cell_size/2]
        cell_x = (rot_x % cell_size) - (cell_size / 2.0)
        cell_y = (rot_y % cell_size) - (cell_size / 2.0)
        dist_sq = cell_x**2 + cell_y**2

        max_radius_sq = (cell_size / 2.0) ** 2

        # Darkness ratio: 0 (white / no burn) to 1 (black / full burn)
        darkness = np.clip(1.0 - (arr / 255.0), 0.0, 1.0)
        dot_radius_sq = darkness * max_radius_sq

        return (dist_sq <= dot_radius_sq).astype(np.uint8)

    @staticmethod
    def generate_simulated_burn_preview(
        raster_arr: np.ndarray,
        material_name: str = "Wood / Birch Plywood",
        custom_bg: Optional[Tuple[int, int, int]] = None,
        custom_burn: Optional[Tuple[int, int, int]] = None
    ) -> Image.Image:
        """
        Generates a realistic RGB preview image simulating the laser burn on the specified material substrate.
        """
        preset = RasterProcessor.MATERIAL_PRESETS.get(material_name, RasterProcessor.MATERIAL_PRESETS["Wood / Birch Plywood"])
        bg_rgb = custom_bg or preset["bg_color"]
        burn_rgb = custom_burn or preset["burn_color"]

        h, w = raster_arr.shape
        img_rgb = np.zeros((h, w, 3), dtype=np.uint8)

        # Fill background
        img_rgb[:, :, 0] = bg_rgb[0]
        img_rgb[:, :, 1] = bg_rgb[1]
        img_rgb[:, :, 2] = bg_rgb[2]

        is_grayscale = (raster_arr.max() > 1)

        if is_grayscale:
            # Continuous tone alpha blending
            alpha = (raster_arr / 255.0)[:, :, np.newaxis]
            burn_arr = np.array(burn_rgb, dtype=np.float32)
            bg_arr = np.array(bg_rgb, dtype=np.float32)
            blended = (alpha * burn_arr + (1.0 - alpha) * bg_arr).astype(np.uint8)
            return Image.fromarray(blended)
        else:
            # 1-bit burn mask
            mask = (raster_arr > 0)
            img_rgb[mask, 0] = burn_rgb[0]
            img_rgb[mask, 1] = burn_rgb[1]
            img_rgb[mask, 2] = burn_rgb[2]
            return Image.fromarray(img_rgb)

    @staticmethod
    def generate_raster_scanlines(
        raster_arr: np.ndarray,
        origin_x_mm: float,
        origin_y_mm: float,
        line_interval_mm: float,
        bidirectional: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Generates cutting segments for each scanline.
        Each segment is (start_x, end_x, power_ratio 0..1, reverse_flag).
        Returns a list of scanline dicts with row, y_mm, and burning segments.
        """
        h, w = raster_arr.shape
        scanlines = []
        is_grayscale = bool(raster_arr.max() > 1)

        if HAS_NUMBA:
            try:
                rows, x1_arr, x2_arr, p_arr, rev_arr = _numba_extract_segments(
                    raster_arr, float(origin_x_mm), float(line_interval_mm), bool(bidirectional), bool(is_grayscale)
                )
                curr_row = -1
                curr_line = None
                n_segs = len(rows)
                for i in range(n_segs):
                    r = int(rows[i])
                    if r != curr_row:
                        curr_row = r
                        y_mm = origin_y_mm + (r * line_interval_mm)
                        curr_line = {
                            "row": r,
                            "y_mm": y_mm,
                            "reverse": bool(rev_arr[i]),
                            "segments": []
                        }
                        scanlines.append(curr_line)
                    curr_line["segments"].append((float(x1_arr[i]), float(x2_arr[i]), float(p_arr[i]), bool(rev_arr[i])))
                return scanlines
            except Exception:
                scanlines = []

        for row in range(h):
            y_mm = origin_y_mm + (row * line_interval_mm)
            line_segments = []

            # Determine scan direction (alternate if bidirectional)
            reverse = bidirectional and (row % 2 == 1)
            col_indices = range(w - 1, -1, -1) if reverse else range(w)

            # Extract burning runs
            in_segment = False
            seg_start_col = 0
            seg_power = 0.0

            for col in col_indices:
                val = raster_arr[row, col]
                burn = (val > 0)

                if burn:
                    if not in_segment:
                        in_segment = True
                        seg_start_col = col
                        seg_power = (val / 255.0) if is_grayscale else 1.0
                    else:
                        if is_grayscale and abs((val / 255.0) - seg_power) > 0.05:
                            # Close previous segment on noticeable power change
                            x1 = origin_x_mm + (seg_start_col * line_interval_mm)
                            x2 = origin_x_mm + (col * line_interval_mm)
                            line_segments.append((x1, x2, seg_power, reverse))
                            seg_start_col = col
                            seg_power = val / 255.0
                else:
                    if in_segment:
                        in_segment = False
                        x1 = origin_x_mm + (seg_start_col * line_interval_mm)
                        x2 = origin_x_mm + (col * line_interval_mm)
                        line_segments.append((x1, x2, seg_power, reverse))

            if in_segment:
                col = -1 if reverse else w
                x1 = origin_x_mm + (seg_start_col * line_interval_mm)
                x2 = origin_x_mm + (col * line_interval_mm)
                line_segments.append((x1, x2, seg_power, reverse))

            if line_segments:
                scanlines.append({
                    "row": row,
                    "y_mm": y_mm,
                    "reverse": reverse,
                    "segments": line_segments
                })

        return scanlines

    @staticmethod
    def calculate_overscan_distance(
        feed_mm_per_min: float,
        accel_mm_per_sec2: float = 1000.0,
        mode: str = "Acceleration",
        pct: float = 2.5,
        fixed_mm: float = 2.0,
        cluster_width_mm: float = 50.0,
        multiplier: float = 1.2
    ) -> float:
        """
        Calculates the required lead-in/lead-out overscan distance in mm.
        Modes:
          - 'Acceleration': Physics-based d = multiplier * (v^2 / (2 * a))
          - 'Percentage': d = cluster_width * (pct / 100)
          - 'Fixed' / 'Distance': d = fixed_mm
        """
        norm_mode = (mode or "").lower()
        if "accel" in norm_mode:
            v_mm_s = max(0.1, feed_mm_per_min / 60.0)
            a_mm_s2 = max(10.0, accel_mm_per_sec2)
            d = multiplier * (v_mm_s ** 2) / (2.0 * a_mm_s2)
            return max(0.2, round(d, 3))
        elif "pct" in norm_mode or "percent" in norm_mode:
            d = cluster_width_mm * (pct / 100.0)
            return max(0.2, round(d, 3))
        else:
            return max(0.2, round(fixed_mm, 3))

    @staticmethod
    def cluster_scanline_segments(
        segments: List[Tuple[float, float, float, bool]],
        skip_threshold_mm: float = 8.0
    ) -> List[List[Tuple[float, float, float, bool]]]:
        """
        Groups adjacent burning segments on a scanline into clusters.
        If the gap between consecutive segments is >= skip_threshold_mm,
        starts a new cluster (enabling fast G0 rapid white-space skipping).
        If the gap is < skip_threshold_mm, segments remain in the same cluster
        and will be traversed with laser OFF at continuous cutting feed rate.
        """
        if not segments:
            return []

        clusters: List[List[Tuple[float, float, float, bool]]] = []
        curr_cluster: List[Tuple[float, float, float, bool]] = [segments[0]]

        for next_seg in segments[1:]:
            prev_seg = curr_cluster[-1]
            # Gap distance between end of prev segment and start of next segment
            gap = abs(next_seg[0] - prev_seg[1])
            if skip_threshold_mm > 0 and gap >= skip_threshold_mm:
                clusters.append(curr_cluster)
                curr_cluster = [next_seg]
            else:
                curr_cluster.append(next_seg)

        if curr_cluster:
            clusters.append(curr_cluster)

        return clusters

    @staticmethod
    def extract_raster_islands(
        raster_arr: np.ndarray,
        origin_x_mm: float,
        origin_y_mm: float,
        line_interval_mm: float,
        min_separation_mm: float = 12.0
    ) -> List[Dict[str, Any]]:
        """
        Segments a raster image into discrete spatial burning islands for Flood Fill engraving.
        If non-burning gaps between objects exceed min_separation_mm, the image is partitioned
        into individual sub-images, avoiding wasted laser head sweeps across empty air.

        Returns a list of dicts:
          - 'sub_array': trimmed np.ndarray of burn values
          - 'origin_x_mm': world X coordinate of top-left corner
          - 'origin_y_mm': world Y coordinate of top-left corner
          - 'width_mm': physical width in mm
          - 'height_mm': physical height in mm
        """
        h, w = raster_arr.shape
        burn_mask = (raster_arr > 0).astype(np.uint8)
        if not np.any(burn_mask):
            return []

        # If OpenCV is unavailable or image is too small to partition, return single full image
        sep_px = int(round(max(2.0, min_separation_mm) / max(0.01, line_interval_mm)))
        if not HAS_CV2 or sep_px <= 2 or w < sep_px:
            return [{
                "sub_array": raster_arr,
                "origin_x_mm": origin_x_mm,
                "origin_y_mm": origin_y_mm,
                "width_mm": w * line_interval_mm,
                "height_mm": h * line_interval_mm,
            }]

        try:
            # Dilate burn mask to merge nearby details into continuous islands
            kw = max(3, sep_px)
            kh = max(3, sep_px // 2)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh))
            dilated = cv2.dilate(burn_mask, kernel)

            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dilated, connectivity=8)
            islands = []
            for lbl in range(1, num_labels):
                lx, ly, lw, lh, area = stats[lbl]
                if area < 4:
                    continue

                # Extract only pixels belonging to this component
                comp_mask = (labels[ly:ly+lh, lx:lx+lw] == lbl)
                sub = np.where(comp_mask, raster_arr[ly:ly+lh, lx:lx+lw], 0)

                # Tight trim to exact non-zero boundaries
                rows = np.any(sub > 0, axis=1)
                cols = np.any(sub > 0, axis=0)
                if not np.any(rows) or not np.any(cols):
                    continue

                r_min, r_max = np.where(rows)[0][[0, -1]]
                c_min, c_max = np.where(cols)[0][[0, -1]]

                trimmed = sub[r_min:r_max+1, c_min:c_max+1]
                island_x = origin_x_mm + (lx + c_min) * line_interval_mm
                island_y = origin_y_mm + (ly + r_min) * line_interval_mm

                islands.append({
                    "sub_array": trimmed,
                    "origin_x_mm": island_x,
                    "origin_y_mm": island_y,
                    "width_mm": trimmed.shape[1] * line_interval_mm,
                    "height_mm": trimmed.shape[0] * line_interval_mm,
                })

            if not islands:
                return [{
                    "sub_array": raster_arr,
                    "origin_x_mm": origin_x_mm,
                    "origin_y_mm": origin_y_mm,
                    "width_mm": w * line_interval_mm,
                    "height_mm": h * line_interval_mm,
                }]

            return islands

        except Exception:
            # Safe fallback to unpartitioned image
            return [{
                "sub_array": raster_arr,
                "origin_x_mm": origin_x_mm,
                "origin_y_mm": origin_y_mm,
                "width_mm": w * line_interval_mm,
                "height_mm": h * line_interval_mm,
            }]

    @staticmethod
    def dither_floyd_steinberg(img: Image.Image) -> Image.Image:
        """Converts PIL image to 1-bit Floyd-Steinberg dithered image."""
        gray = img.convert("L")
        return gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG)

    @staticmethod
    def dither_atkinson(img: Image.Image) -> Image.Image:
        """Applies Atkinson dithering and returns 1-bit PIL Image."""
        arr = np.array(img.convert("L"), dtype=np.float32)
        out = RasterProcessor._dither_atkinson_arr(arr)
        mono = np.where(out == 1, 0, 255).astype(np.uint8)
        return Image.fromarray(mono, mode="L").convert("1")

    @staticmethod
    def dither_jarvis(img: Image.Image) -> Image.Image:
        """Applies Jarvis-Judice-Ninke dithering and returns 1-bit PIL Image."""
        arr = np.array(img.convert("L"), dtype=np.float32)
        out = RasterProcessor._dither_jarvis_arr(arr)
        mono = np.where(out == 1, 0, 255).astype(np.uint8)
        return Image.fromarray(mono, mode="L").convert("1")

    @staticmethod
    def dither_stucki(img: Image.Image) -> Image.Image:
        """Applies Stucki dithering and returns 1-bit PIL Image."""
        arr = np.array(img.convert("L"), dtype=np.float32)
        out = RasterProcessor._dither_stucki_arr(arr)
        mono = np.where(out == 1, 0, 255).astype(np.uint8)
        return Image.fromarray(mono, mode="L").convert("1")

    @staticmethod
    def dither_halftone(img: Image.Image, cell_size: float = 6.0, angle_deg: float = 45.0) -> Image.Image:
        """Applies Halftone AM screening and returns 1-bit PIL Image."""
        arr = np.array(img.convert("L"), dtype=np.float32)
        out = RasterProcessor._dither_halftone_arr(arr, cell_size, angle_deg)
        mono = np.where(out == 1, 0, 255).astype(np.uint8)
        return Image.fromarray(mono, mode="L").convert("1")

    @staticmethod
    def image_to_scanlines(img: Image.Image, pixel_size_mm: float = 0.1):
        """Converts a 1-bit or grayscale PIL image directly into laser scanline data."""
        arr = np.array(img.convert("L"))
        burn_mask = (arr < 128).astype(np.uint8)
        return RasterProcessor.generate_raster_scanlines(burn_mask, 0.0, 0.0, pixel_size_mm)
