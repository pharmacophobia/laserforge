"""
LaserForge Image to SVG Vector Tracer.
High-performance, professional-grade bitmap to vector converter (LightBurn Trace Image engine).
Uses OpenCV topological contour extraction (Suzuki-Abe algorithm), adaptive Gaussian binarization,
Canny edge sketch detection, sub-pixel Ramer-Douglas-Peucker polygon simplification, and
corner-preserving Chaikin curve smoothing.
"""

from __future__ import annotations
from typing import List, Tuple, Dict, Optional, Any
import math

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None

import numpy as np
from PIL import Image


def otsu_threshold(gray_arr: np.ndarray) -> int:
    """Computes the optimal binarization threshold using Otsu's method via OpenCV."""
    if gray_arr.size == 0:
        return 128
    if len(gray_arr.shape) == 3:
        gray = cv2.cvtColor(gray_arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = gray_arr.astype(np.uint8)
    thresh_val, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return int(thresh_val)


def rdp_simplify_polygon(pts: List[Tuple[float, float]], epsilon: float = 1.0) -> List[Tuple[float, float]]:
    """Simplifies a closed polygon using OpenCV's fast Ramer-Douglas-Peucker algorithm."""
    if len(pts) <= 3 or epsilon <= 0.01:
        return pts

    # Ensure array is in (N, 1, 2) shape
    arr = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(arr, epsilon, closed=True)
    res = simplified.reshape(-1, 2)
    return [(float(p[0]), float(p[1])) for p in res]


def calculate_polygon_area(pts: List[Tuple[float, float]]) -> float:
    """Calculates 2D polygon area using Green's Theorem / Shoelace formula."""
    if len(pts) < 3:
        return 0.0
    arr = np.array(pts, dtype=np.float32)
    return float(abs(cv2.contourArea(arr)))


def corner_preserving_smooth(
    pts: np.ndarray,
    corner_angle_thresh_deg: float = 65.0,
    iterations: int = 1
) -> np.ndarray:
    """
    Subdivides and smooths organic curves while preserving sharp corners (turning angle >= threshold).
    pts: Nx2 numpy array representing a closed polygon.
    Optimized: Fast vectorized NumPy Chaikin subdivision, hypot-based norms, and pre-computed cosine threshold.
    """
    p = np.asarray(pts, dtype=np.float64)
    if len(p) <= 3 or iterations <= 0:
        return p

    if abs(p[0, 0] - p[-1, 0]) < 1e-4 and abs(p[0, 1] - p[-1, 1]) < 1e-4:
        p = p[:-1]

    n = len(p)
    if n <= 3:
        return np.vstack([p, p[:1]])

    cos_thresh = math.cos(math.radians(corner_angle_thresh_deg))

    # Detect hard corners using fast vector differences and hypot (turning angle >= threshold <=> cos(dot) <= cos_thresh)
    v_in = p - np.vstack([p[-1:], p[:-1]])
    v_out = np.vstack([p[1:], p[:1]]) - p
    norm_in = np.hypot(v_in[:, 0], v_in[:, 1])
    norm_out = np.hypot(v_out[:, 0], v_out[:, 1])
    norm_in[norm_in == 0] = 1.0
    norm_out[norm_out == 0] = 1.0

    dot = np.clip((v_in[:, 0] * v_out[:, 0] + v_in[:, 1] * v_out[:, 1]) / (norm_in * norm_out), -1.0, 1.0)
    hard_corners = (dot <= cos_thresh)

    for _ in range(iterations):
        m = len(p)
        prev_p = np.vstack([p[-1:], p[:-1]])
        next_p = np.vstack([p[1:], p[:1]])
        q = 0.25 * prev_p + 0.75 * p
        r = 0.75 * p + 0.25 * next_p

        if not np.any(hard_corners):
            # Pure vectorized Chaikin interleave
            res = np.empty((m * 2, 2), dtype=p.dtype)
            res[0::2] = q
            res[1::2] = r
            p = res
        else:
            out = []
            for i in range(m):
                if hard_corners[i]:
                    out.append(p[i])
                else:
                    out.append(q[i])
                    out.append(r[i])
            p = np.array(out, dtype=p.dtype)

        if len(p) > n:
            v_in = p - np.vstack([p[-1:], p[:-1]])
            v_out = np.vstack([p[1:], p[:1]]) - p
            norm_in = np.hypot(v_in[:, 0], v_in[:, 1])
            norm_out = np.hypot(v_out[:, 0], v_out[:, 1])
            norm_in[norm_in == 0] = 1.0
            norm_out[norm_out == 0] = 1.0
            dot = np.clip((v_in[:, 0] * v_out[:, 0] + v_in[:, 1] * v_out[:, 1]) / (norm_in * norm_out), -1.0, 1.0)
            hard_corners = (dot <= cos_thresh)

    return np.vstack([p, p[:1]])


class ImageTracer:
    """Professional OpenCV-accelerated bitmap to vector / SVG tracer."""

    @staticmethod
    def get_binary_mask(
        img: Image.Image,
        threshold: Optional[int] = None,
        mode: str = "feature",
        invert: bool = False,
        blur_radius: float = 0.5,
        adaptive_block_size: int = 15,
        adaptive_c: float = 4.0,
        contrast: float = 0.0,
        brightness: float = 0.0,
        high_pass: float = 0.0,
        clahe: bool = False,
        edge_dilation: int = 1
    ) -> np.ndarray:
        """
        Binarizes a PIL image into a clean 2D uint8 mask (0 or 255).
        Foreground (cut lines/burn area) = 255, background = 0.
        Supports:
          - Alpha transparency compositing onto clean white background
          - Contrast & Brightness adjustments
          - Local Contrast Enhancement (CLAHE)
          - High-Pass frequency filter (removes uneven lighting/shadows)
          - Feature Outlines (Sobel gradient magnitude) for extracting internal features
          - Standard Otsu / manual global thresholding
          - Adaptive Gaussian thresholding
          - Canny Edge detection
        """
        # 1. Alpha composite onto clean white background to avoid transparent black blobs
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            composite = Image.alpha_composite(bg, img.convert("RGBA"))
            gray = np.array(composite.convert("L"), dtype=np.uint8)
        else:
            gray = np.array(img.convert("L"), dtype=np.uint8)

        # 2. Bilateral / edge-preserving denoising (clamped d to prevent quadratic stalling)
        if blur_radius > 0.1:
            k = min(9, max(3, int(blur_radius * 2) | 1))
            gray = cv2.bilateralFilter(gray, d=k, sigmaColor=40, sigmaSpace=k)

        # 3. Contrast & Brightness adjustment (-100 to +100) via fast C++ SIMD cv2.convertScaleAbs
        if contrast != 0.0 or brightness != 0.0:
            alpha = max(0.0, (contrast + 100.0) / 100.0)
            beta = brightness * 1.28
            gray = cv2.convertScaleAbs(gray, alpha=alpha, beta=beta)

        # 4. CLAHE (Contrast Limited Adaptive Histogram Equalization)
        if clahe:
            clahe_obj = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            gray = clahe_obj.apply(gray)

        # 5. High-Pass frequency filter (removes broad shadows and lighting gradients)
        if high_pass > 0.5:
            k_hp = max(3, int(high_pass * 2) | 1)
            blur_hp = cv2.GaussianBlur(gray, (k_hp, k_hp), 0)
            hp = gray.astype(np.int16) - blur_hp.astype(np.int16) + 128
            gray = np.clip(hp, 0, 255).astype(np.uint8)

        # 6. Extraction Engine
        if mode in ("feature", "gradient"):
            # Feature Outlines: Gradient magnitude extracts the physical outlines between all features
            sx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            sy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            mag = cv2.magnitude(sx, sy)
            mag_u8 = np.clip(mag, 0, 255).astype(np.uint8)
            t = threshold if threshold is not None else 30
            thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            _, binary = cv2.threshold(mag_u8, t, 255, thresh_type)
            if edge_dilation > 0:
                kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (edge_dilation * 2 + 1, edge_dilation * 2 + 1))
                binary = cv2.dilate(binary, kd)
        elif mode == "adaptive":
            bs = max(3, int(adaptive_block_size) | 1)
            thresh_type = cv2.THRESH_BINARY if invert else cv2.THRESH_BINARY_INV
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, thresh_type, bs, int(adaptive_c))
        elif mode == "edge":
            t = threshold if threshold is not None else 100
            t_low = max(10, t // 2)
            t_high = min(255, max(30, t))
            edges = cv2.Canny(gray, t_low, t_high)
            if edge_dilation > 0:
                kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (edge_dilation * 2 + 1, edge_dilation * 2 + 1))
                edges = cv2.dilate(edges, kd)
            binary = cv2.bitwise_not(edges) if invert else edges
        else:
            # Standard Global Threshold
            if threshold is None:
                thresh_val, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                threshold = int(thresh_val)
            # Auto-detect if image has dark background (e.g. sketch on black background)
            is_dark_bg = False
            if mode == "sketch" and gray.size > 4:
                corners = [gray[0, 0], gray[0, -1], gray[-1, 0], gray[-1, -1]]
                is_dark_bg = (float(np.mean(corners)) < 128.0)

            if is_dark_bg:
                thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            else:
                thresh_type = cv2.THRESH_BINARY if invert else cv2.THRESH_BINARY_INV
            _, binary = cv2.threshold(gray, threshold, 255, thresh_type)

        return binary

    @staticmethod
    def trace_image(
        img: Optional[Image.Image] = None,
        threshold: Optional[int] = None,
        mode: str = "feature",
        invert: bool = False,
        blur_radius: float = 0.5,
        smoothness: float = 0.8,
        corner_sharpness_deg: float = 65.0,
        smooth_iterations: int = 1,
        min_area_pixels: float = 10.0,
        ignore_holes: bool = False,
        ignore_border: bool = True,
        adaptive_block_size: int = 15,
        adaptive_c: float = 4.0,
        contrast: float = 0.0,
        brightness: float = 0.0,
        high_pass: float = 0.0,
        clahe: bool = False,
        edge_dilation: int = 1,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        binary_mask: Optional[np.ndarray] = None
    ) -> List[List[Tuple[float, float]]]:
        """
        Traces a PIL image into vector contours.
        Returns a list of closed polygon loops [(x, y), ...].
        """
        if binary_mask is not None:
            binary = binary_mask
        else:
            if img is None:
                raise ValueError("Either img or binary_mask must be provided")
            binary = ImageTracer.get_binary_mask(
                img,
                threshold=threshold,
                mode=mode,
                invert=invert,
                blur_radius=blur_radius,
                adaptive_block_size=adaptive_block_size,
                adaptive_c=adaptive_c,
                contrast=contrast,
                brightness=brightness,
                high_pass=high_pass,
                clahe=clahe,
                edge_dilation=edge_dilation
            )

        img_h, img_w = binary.shape[:2]
        mode_ret = cv2.RETR_EXTERNAL if ignore_holes else cv2.RETR_TREE
        contours, hierarchy = cv2.findContours(binary, mode_ret, cv2.CHAIN_APPROX_SIMPLE)

        if not contours or hierarchy is None:
            return []

        scale_vec = np.array([scale_x, scale_y], dtype=np.float64)
        offset_vec = np.array([offset_x, offset_y], dtype=np.float64)
        epsilon = max(0.1, smoothness * 0.75)
        border_thresh = 0.98 * (img_w * img_h)

        processed_contours = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area_pixels:
                continue

            # Ignore full-image border frame if requested
            if ignore_border:
                bx, by, bw, bh = cv2.boundingRect(c)
                if (abs(bx) <= 2 and abs(by) <= 2 and abs(bw - img_w) <= 4 and abs(bh - img_h) <= 4) or area >= border_thresh:
                    continue

            # Subpixel polygon simplification via Ramer-Douglas-Peucker
            approx = cv2.approxPolyDP(c, epsilon, closed=True)
            if len(approx) < 3:
                continue

            pts = approx.reshape(-1, 2).astype(np.float64)

            # Corner-preserving curve smoothing
            if smooth_iterations > 0 and len(pts) > 4:
                pts = corner_preserving_smooth(
                    pts,
                    corner_angle_thresh_deg=corner_sharpness_deg,
                    iterations=smooth_iterations
                )

            # Vectorized scale to mm / destination coordinates and offset
            scaled = (pts * scale_vec + offset_vec).tolist()
            if scaled[0] != scaled[-1]:
                scaled.append(scaled[0])

            processed_contours.append(scaled)

        return processed_contours

    @staticmethod
    def trace_centerline(
        img: Optional[Image.Image] = None,
        binary_mask: Optional[np.ndarray] = None,
        threshold: int = 128,
        mode: str = "sketch",
        invert: bool = False,
        blur_radius: int = 1,
        adaptive_block_size: int = 11,
        adaptive_c: int = 2,
        contrast: float = 1.0,
        brightness: float = 0.0,
        high_pass: bool = False,
        clahe: bool = False,
        edge_dilation: int = 0,
        min_length_pixels: float = 4.0,
        smoothness: float = 1.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0
    ) -> List[List[Tuple[float, float]]]:
        """
        Extracts single-stroke centerline vector paths from raster images using
        morphological skeletonization. Ideal for signatures, handwriting, line art,
        and single-pass laser score cutting.
        """
        if binary_mask is not None:
            binary = binary_mask
        else:
            if img is None:
                raise ValueError("Either img or binary_mask must be provided")
            binary = ImageTracer.get_binary_mask(
                img,
                threshold=threshold,
                mode=mode,
                invert=invert,
                blur_radius=blur_radius,
                adaptive_block_size=adaptive_block_size,
                adaptive_c=adaptive_c,
                contrast=contrast,
                brightness=brightness,
                high_pass=high_pass,
                clahe=clahe,
                edge_dilation=edge_dilation
            )

        fg = (binary > 127)
        if not np.any(fg):
            return []

        try:
            import skimage.morphology
            skel = skimage.morphology.skeletonize(fg)
        except ImportError:
            # Morphological thinning using OpenCV
            src = (fg.astype(np.uint8) * 255)
            skel_arr = np.zeros(src.shape, dtype=np.uint8)
            element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
            curr = src.copy()
            for _ in range(500):
                eroded = cv2.erode(curr, element)
                temp = cv2.dilate(eroded, element)
                temp = cv2.subtract(curr, temp)
                skel_arr = cv2.bitwise_or(skel_arr, temp)
                curr = eroded
                if cv2.countNonZero(curr) == 0:
                    break
            skel = (skel_arr > 0)

        y_indices, x_indices = np.where(skel)
        if len(y_indices) == 0:
            return []

        pts_set = set(zip(x_indices, y_indices))
        adj: Dict[Tuple[int, int], List[Tuple[int, int]]] = {p: [] for p in pts_set}
        for x, y in pts_set:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nbr = (x + dx, y + dy)
                    if nbr in pts_set:
                        adj[(x, y)].append(nbr)

        visited_edges = set()
        paths: List[List[Tuple[float, float]]] = []

        # Find key nodes: endpoints (deg == 1) and junctions (deg >= 3)
        key_nodes = [p for p, nbrs in adj.items() if len(nbrs) != 2]

        # 1. Walk from key nodes
        for start_node in key_nodes:
            for nbr in adj[start_node]:
                edge_id = tuple(sorted([start_node, nbr]))
                if edge_id in visited_edges:
                    continue

                curr_path = [start_node, nbr]
                visited_edges.add(edge_id)
                prev = start_node
                curr = nbr

                while True:
                    next_nodes = [n for n in adj[curr] if n != prev]
                    if len(next_nodes) != 1:
                        break
                    next_n = next_nodes[0]
                    next_edge = tuple(sorted([curr, next_n]))
                    if next_edge in visited_edges:
                        break
                    visited_edges.add(next_edge)
                    curr_path.append(next_n)
                    prev, curr = curr, next_n

                if len(curr_path) >= 2:
                    paths.append([(float(px), float(py)) for px, py in curr_path])

        # 2. Walk isolated closed loops
        for p in pts_set:
            for nbr in adj[p]:
                edge_id = tuple(sorted([p, nbr]))
                if edge_id in visited_edges:
                    continue

                curr_path = [p, nbr]
                visited_edges.add(edge_id)
                prev = p
                curr = nbr

                while True:
                    next_nodes = [n for n in adj[curr] if n != prev]
                    if not next_nodes:
                        break
                    next_n = next_nodes[0]
                    next_edge = tuple(sorted([curr, next_n]))
                    if next_edge in visited_edges:
                        if next_n == p:
                            curr_path.append(p)
                        break
                    visited_edges.add(next_edge)
                    curr_path.append(next_n)
                    prev, curr = curr, next_n

                if len(curr_path) >= 2:
                    paths.append([(float(px), float(py)) for px, py in curr_path])

        # Post-process: RDP simplify and scale to mm
        processed = []
        epsilon = max(0.2, smoothness * 0.75)
        for path in paths:
            if len(path) < 2:
                continue
            arr = np.array(path, dtype=np.float32).reshape(-1, 1, 2)
            closed = (path[0] == path[-1])
            simplified = cv2.approxPolyDP(arr, epsilon, closed=closed).reshape(-1, 2)
            if len(simplified) < 2:
                continue

            diffs = simplified[1:] - simplified[:-1]
            dist = float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))
            if dist < min_length_pixels:
                continue

            scaled = [
                (offset_x + float(pt[0]) * scale_x, offset_y + float(pt[1]) * scale_y)
                for pt in simplified
            ]
            processed.append(scaled)

        return processed

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
            if not poly or len(poly) < 2:
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
        mode: str = "threshold",
        invert: bool = False,
        smoothness: float = 1.0,
        blur_radius: float = 0.5,
        min_area_pixels: float = 10.0,
        ignore_holes: bool = False
    ):
        """Direct file-to-file image to SVG vectorizer."""
        with Image.open(input_image_path) as img:
            orig_w, orig_h = img.size

            if target_width_mm is None and target_height_mm is None:
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
                mode=mode,
                invert=invert,
                blur_radius=blur_radius,
                smoothness=smoothness,
                min_area_pixels=min_area_pixels,
                ignore_holes=ignore_holes,
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
