"""
LaserForge Raster Image Processor.
Converts images into optimized laser raster scanlines via Floyd-Steinberg, Atkinson,
Thresholding, and Grayscale laser power modulation.
"""

from typing import List, Tuple, Optional
import numpy as np
from PIL import Image, ImageEnhance

class RasterProcessor:

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
        threshold_val: int = 128
    ) -> np.ndarray:
        """
        Processes a PIL Image and returns a 2D numpy array:
        For dithered/threshold modes: uint8 array with 1 (laser ON / burn) and 0 (laser OFF / no burn).
        For Grayscale mode: uint8 array with values 0 (white / 0 power) to 255 (black / max power).
        """
        # Calculate pixel dimensions based on line interval
        cols = max(1, int(round(target_width_mm / line_interval_mm)))
        rows = max(1, int(round(target_height_mm / line_interval_mm)))

        # Convert to Grayscale (L)
        gray = img.convert("L")

        # Adjust contrast and brightness
        if contrast != 1.0:
            enhancer = ImageEnhance.Contrast(gray)
            gray = enhancer.enhance(contrast)
        if brightness != 0.0:
            enhancer = ImageEnhance.Brightness(gray)
            gray = enhancer.enhance(1.0 + brightness)

        # Resize with high quality Lanczos filter
        resized = gray.resize((cols, rows), Image.Resampling.LANCZOS)
        arr = np.array(resized, dtype=np.float32)

        # Invert if requested
        if invert:
            arr = 255.0 - arr

        if mode == "Grayscale":
            # Direct laser power modulation: Darker pixels = higher laser power (0..255)
            # Standard image: 255 is white, 0 is black. So inverted: (255 - pixel)
            burn_power = 255.0 - arr
            burn_power = np.clip(burn_power, 0, 255).astype(np.uint8)
            return burn_power

        elif mode == "Threshold":
            # 1 = burn (dark pixel <= threshold), 0 = no burn
            result = (arr <= threshold_val).astype(np.uint8)
            return result

        elif mode == "Atkinson":
            # Atkinson error diffusion
            h, w = arr.shape
            buf = arr.copy()
            out = np.zeros((h, w), dtype=np.uint8)

            for y in range(h):
                for x in range(w):
                    old_val = buf[y, x]
                    new_val = 0.0 if old_val < 128.0 else 255.0
                    err = (old_val - new_val) / 8.0
                    out[y, x] = 1 if new_val == 0.0 else 0

                    if x + 1 < w:
                        buf[y, x + 1] += err
                    if x + 2 < w:
                        buf[y, x + 2] += err
                    if y + 1 < h:
                        if x > 0:
                            buf[y + 1, x - 1] += err
                        buf[y + 1, x] += err
                        if x + 1 < w:
                            buf[y + 1, x + 1] += err
                    if y + 2 < h:
                        buf[y + 2, x] += err

            return out

        else:
            # Default: Floyd-Steinberg Dithering
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
    def generate_raster_scanlines(
        raster_arr: np.ndarray,
        origin_x_mm: float,
        origin_y_mm: float,
        line_interval_mm: float,
        bidirectional: bool = True
    ) -> List[List[Tuple[float, float, float]]]:
        """
        Generates cutting segments for each scanline.
        Each segment is (start_x, end_x, power_ratio 0..1).
        Returns a list of scanlines, where each line has a y_mm coordinate and burning segments.
        """
        h, w = raster_arr.shape
        scanlines = []

        is_grayscale = (raster_arr.max() > 1)

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
    def dither_floyd_steinberg(img: Image.Image) -> Image.Image:
        """Converts PIL image to 1-bit Floyd-Steinberg dithered image."""
        gray = img.convert("L")
        return gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG)

    @staticmethod
    def dither_atkinson(img: Image.Image) -> Image.Image:
        """Applies Atkinson dithering and returns 1-bit PIL Image."""
        arr = np.array(img.convert("L"), dtype=np.float32)
        h, w = arr.shape
        buf = arr.copy()
        out = np.zeros((h, w), dtype=np.uint8)

        for y in range(h):
            for x in range(w):
                old_val = buf[y, x]
                new_val = 0.0 if old_val < 128.0 else 255.0
                err = (old_val - new_val) / 8.0
                out[y, x] = 0 if new_val == 0.0 else 255

                if x + 1 < w: buf[y, x + 1] += err
                if x + 2 < w: buf[y, x + 2] += err
                if y + 1 < h:
                    if x > 0: buf[y + 1, x - 1] += err
                    buf[y + 1, x] += err
                    if x + 1 < w: buf[y + 1, x + 1] += err
                if y + 2 < h: buf[y + 2, x] += err

        return Image.fromarray(out, mode="L").convert("1")

    @staticmethod
    def image_to_scanlines(img: Image.Image, pixel_size_mm: float = 0.1):
        """Converts a 1-bit or grayscale PIL image directly into laser scanline data."""
        arr = np.array(img.convert("L"))
        # 0 is black (burn), 255 is white (no burn)
        burn_mask = (arr < 128).astype(np.uint8)
        return RasterProcessor.generate_raster_scanlines(burn_mask, 0.0, 0.0, pixel_size_mm)

