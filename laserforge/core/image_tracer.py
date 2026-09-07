"""
LaserForge Image to SVG Vector Tracer.
Converts bitmap images (PNG, JPG, BMP, WebP) into clean, smooth vector paths and SVG files.
Uses Marching Squares contour extraction, Otsu auto-thresholding, and Ramer-Douglas-Peucker
curve simplification.
"""

from typing import List, Tuple, Dict, Optional, Any
import math
import numpy as np
from PIL import Image, ImageFilter, ImageOps


def otsu_threshold(gray_arr: np.ndarray) -> int:
    """Computes the optimal binarization threshold using Otsu's method."""
    hist, _ = np.histogram(gray_arr, bins=256, range=(0, 256))
    total = gray_arr.size
    if total == 0:
        return 128

    current_max = 0.0
    threshold = 128
    sum_total = np.dot(np.arange(256), hist)
    sum_b = 0.0
    weight_b = 0

    for i in range(256):
        weight_b += hist[i]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += i * hist[i]
        mean_b = sum_b / weight_b
        mean_f = (sum_total - sum_b) / weight_f
        var_between = float(weight_b) * float(weight_f) * ((mean_b - mean_f) ** 2)
        if var_between > current_max:
            current_max = var_between
            threshold = i

    return threshold


def rdp_simplify_polygon(pts: List[Tuple[float, float]], epsilon: float = 1.0) -> List[Tuple[float, float]]:
    """Simplifies a closed polygon using Ramer-Douglas-Peucker algorithm."""
    if len(pts) <= 4 or epsilon <= 0.01:
        return pts

    p_arr = np.array(pts)
    # Split closed polygon at the point farthest from start
    dists = np.linalg.norm(p_arr - p_arr[0], axis=1)
    split_idx = int(np.argmax(dists))
    if split_idx <= 1 or split_idx >= len(pts) - 2:
        split_idx = len(pts) // 2

    def rdp_open(points: np.ndarray, eps: float) -> np.ndarray:
        if len(points) <= 2:
            return points
        p1 = points[0]
        p2 = points[-1]
        line = p2 - p1
        norm = np.linalg.norm(line)
        if norm == 0:
            d = np.linalg.norm(points[1:-1] - p1, axis=1)
        else:
            u = line / norm
            v = points[1:-1] - p1
            proj = np.dot(v, u)
            proj_pts = p1 + np.outer(proj, u)
            d = np.linalg.norm(points[1:-1] - proj_pts, axis=1)

        if len(d) == 0:
            return np.array([points[0], points[-1]])

        max_i = int(np.argmax(d))
        if d[max_i] > eps:
            left = rdp_open(points[:max_i + 2], eps)
            right = rdp_open(points[max_i + 1:], eps)
            return np.vstack((left[:-1], right))
        else:
            return np.array([points[0], points[-1]])

    half1 = rdp_open(p_arr[:split_idx + 1], epsilon)
    half2 = rdp_open(p_arr[split_idx:], epsilon)
    res = np.vstack((half1[:-1], half2))
    return [(float(p[0]), float(p[1])) for p in res]


def calculate_polygon_area(pts: List[Tuple[float, float]]) -> float:
    """Calculates signed 2D polygon area using Shoelace formula."""
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i in range(len(pts) - 1):
        area += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(area) / 2.0


class ImageTracer:
    """High-performance bitmap to vector / SVG converter."""

    @staticmethod
    def trace_image(
        img: Image.Image,
        threshold: Optional[int] = None,
        invert: bool = False,
        blur_radius: float = 0.0,
        smoothness: float = 1.0,
        min_area_pixels: float = 10.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0
    ) -> List[List[Tuple[float, float]]]:
        """
        Traces a PIL image into vector contours.
        Returns a list of closed polygon loops [(x, y), ...].
        """
        # Convert to Grayscale
        gray = img.convert("L")

        # Optional Gaussian Blur for noise removal
        if blur_radius > 0.1:
            gray = gray.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        arr = np.array(gray, dtype=np.uint8)

        # Automatic or user threshold
        if threshold is None:
            threshold = otsu_threshold(arr)

        # Binarize: True = black/dark pixel (burn area), False = white/light background
        if invert:
            binary = (arr > threshold)
        else:
            binary = (arr <= threshold)


        # Extract raw contours via Marching Squares
        raw_polygons = ImageTracer._marching_squares(binary)

        # Filter noise and simplify curves
        processed_contours = []
        for poly in raw_polygons:
            area = calculate_polygon_area(poly)
            if area < min_area_pixels:
                continue

            # RDP curve simplification
            simplified = rdp_simplify_polygon(poly, epsilon=smoothness)
            if len(simplified) < 3:
                continue

            # Ensure closed loop
            if simplified[0] != simplified[-1]:
                simplified.append(simplified[0])

            # Apply coordinate scaling (e.g. pixels to mm) and offset
            scaled_poly = [
                (offset_x + pt[0] * scale_x, offset_y + pt[1] * scale_y)
                for pt in simplified
            ]
            processed_contours.append(scaled_poly)

        return processed_contours

    @staticmethod
    def _marching_squares(binary_grid: np.ndarray) -> List[List[Tuple[float, float]]]:
        """Extracts directed boundary contours using Marching Squares table."""
        # Pad grid by 1 pixel on all sides to guarantee closed outer boundary
        padded = np.pad(binary_grid, 1, mode="constant", constant_values=False).astype(np.uint8)

        tl = padded[:-1, :-1]
        tr = padded[:-1, 1:]
        br = padded[1:, 1:]
        bl = padded[1:, :-1]

        cases = (tl << 3) | (tr << 2) | (br << 1) | bl

        next_pt: Dict[Tuple[float, float], Tuple[float, float]] = {}
        rows, cols = np.where((cases > 0) & (cases < 15))

        for r, c in zip(rows, cols):
            case = int(cases[r, c])
            x = float(c - 1)
            y = float(r - 1)

            N = (x + 0.5, y)
            E = (x + 1.0, y + 0.5)
            S = (x + 0.5, y + 1.0)
            W = (x, y + 0.5)

            segs = []
            if case == 1:   segs = [(W, S)]
            elif case == 2: segs = [(S, E)]
            elif case == 3: segs = [(W, E)]
            elif case == 4: segs = [(E, N)]
            elif case == 5: segs = [(W, N), (E, S)]
            elif case == 6: segs = [(S, N)]
            elif case == 7: segs = [(W, N)]
            elif case == 8: segs = [(N, W)]
            elif case == 9: segs = [(N, S)]
            elif case == 10: segs = [(N, E), (S, W)]
            elif case == 11: segs = [(N, E)]
            elif case == 12: segs = [(E, W)]
            elif case == 13: segs = [(E, S)]
            elif case == 14: segs = [(S, W)]

            for p1, p2 in segs:
                next_pt[p1] = p2

        # Trace and assemble directed edges into closed polygon loops
        visited = set()
        polygons = []

        for start in list(next_pt.keys()):
            if start in visited:
                continue

            poly = [start]
            visited.add(start)
            curr = next_pt.get(start)

            while curr and curr not in visited and curr in next_pt:
                visited.add(curr)
                poly.append(curr)
                curr = next_pt.get(curr)

            if curr == start and len(poly) >= 3:
                poly.append(start)
                polygons.append(poly)

        return polygons

    @staticmethod
    def contours_to_svg(
        contours: List[List[Tuple[float, float]]],
        width_mm: float,
        height_mm: float,
        stroke_color: str = "#000000",
        stroke_width: float = 0.2,
        fill_color: str = "none"
    ) -> str:
        """Serializes vector contours into a standard SVG document string."""
        path_data = []
        for poly in contours:
            if not poly:
                continue
            d = [f"M {poly[0][0]:.3f} {poly[0][1]:.3f}"]
            for pt in poly[1:]:
                d.append(f"L {pt[0]:.3f} {pt[1]:.3f}")
            d.append("Z")
            path_data.append(" ".join(d))

        full_d = " ".join(path_data)

        svg = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
     width="{width_mm:.2f}mm" height="{height_mm:.2f}mm"
     viewBox="0 0 {width_mm:.2f} {height_mm:.2f}">
  <g id="traced_vectors">
    <path d="{full_d}" fill="{fill_color}" stroke="{stroke_color}" stroke-width="{stroke_width:.2f}" fill-rule="evenodd" />
  </g>
</svg>
"""
        return svg

    @staticmethod
    def export_svg_file(
        contours: List[List[Tuple[float, float]]],
        output_filepath: str,
        width_mm: float,
        height_mm: float,
        stroke_color: str = "#000000",
        fill_color: str = "none"
    ):
        """Saves vector contours directly to an SVG file."""
        svg_str = ImageTracer.contours_to_svg(
            contours, width_mm, height_mm,
            stroke_color=stroke_color, fill_color=fill_color
        )
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(svg_str)

    @staticmethod
    def trace_file_to_svg_file(
        input_image_path: str,
        output_svg_path: str,
        target_width_mm: Optional[float] = None,
        target_height_mm: Optional[float] = None,
        threshold: Optional[int] = None,
        invert: bool = False,
        smoothness: float = 1.0,
        blur_radius: float = 0.5,
        min_area_pixels: float = 10.0
    ):
        """Direct file-to-file image to SVG vectorizer."""
        with Image.open(input_image_path) as img:
            orig_w, orig_h = img.size

            if target_width_mm is None and target_height_mm is None:
                # Default 100mm width maintaining aspect ratio
                target_width_mm = 100.0
                target_height_mm = target_width_mm * (orig_h / max(1, orig_w))
            elif target_height_mm is None:
                target_height_mm = target_width_mm * (orig_h / max(1, orig_w))
            elif target_width_mm is None:
                target_width_mm = target_height_mm * (orig_w / max(1, orig_h))

            scale_x = target_width_mm / max(1, orig_w)
            scale_y = target_height_mm / max(1, orig_h)

            contours = ImageTracer.trace_image(
                img,
                threshold=threshold,
                invert=invert,
                blur_radius=blur_radius,
                smoothness=smoothness,
                min_area_pixels=min_area_pixels,
                scale_x=scale_x,
                scale_y=scale_y
            )

            ImageTracer.export_svg_file(contours, output_svg_path, target_width_mm, target_height_mm)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 -m laserforge.core.image_tracer <input_image> <output_svg> [threshold] [smoothness] [width_mm]")
        sys.exit(1)

    in_file = sys.argv[1]
    out_file = sys.argv[2]
    thresh = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else None
    smooth = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    w_mm = float(sys.argv[5]) if len(sys.argv) > 5 else 100.0

    print(f"Tracing '{in_file}' to '{out_file}' (smoothness={smooth}, width={w_mm}mm)...")
    ImageTracer.trace_file_to_svg_file(in_file, out_file, target_width_mm=w_mm, threshold=thresh, smoothness=smooth)
    print(f"Successfully created {out_file}")

