"""
LaserForge Auto Image to SVG Cutout Generator.
High-precision automatic silhouette extraction, outward/inward offset contours,
smooth curve generation, and laser-ready SVG cutout export.

Designed for:
  - Laser sticker cut lines / vinyl peel borders
  - Acrylic & wooden standees with base tabs
  - Keychains, charms, pendants, and holiday ornaments with hanging loops
  - Print & Cut / Engrave & Cut dual-layer workflows (LightBurn / xTool / Glowforge style)
"""

from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field
import os
import io
import base64
import math
import cv2
import numpy as np
from PIL import Image

from laserforge.core.image_tracer import rdp_simplify_polygon, corner_preserving_smooth
from laserforge.core.models import PathEntity, ImageEntity


@dataclass
class CutoutResult:
    """Encapsulates generated cutout contours, metrics, and SVG payload."""
    contours: List[List[Tuple[float, float]]]  # Contours in mm (relative to entity origin)
    width_mm: float
    height_mm: float
    bounding_box: Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y) in mm
    mask_preview: np.ndarray  # Binary mask in uint8 (255 = cutout area)
    has_holes: bool = False
    hanging_hole_center_mm: Optional[Tuple[float, float]] = None
    svg_data: str = ""


class AutoCutoutGenerator:
    """
    Automatic subject segmentation and vector cutout generator.
    Converts raster images into high-precision, smooth laser cut paths.
    """

    @staticmethod
    def extract_subject_mask(
        img: Image.Image,
        bg_mode: str = "auto",
        color_tolerance: int = 25,
        alpha_threshold: int = 15,
        invert: bool = False
    ) -> np.ndarray:
        """
        Extracts a clean binary 2D mask (uint8: 255 = subject, 0 = background).
        Handles:
          - Alpha transparency (PNG / WEBP / transparent GIFs)
          - Uniform / light background auto-detection from border/corner sampling
          - High-contrast Otsu thresholding
        """
        # 1. Check alpha channel
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        rgba = img.convert("RGBA")
        arr = np.array(rgba, dtype=np.uint8)
        alpha = arr[:, :, 3]

        if bg_mode == "alpha" or (bg_mode == "auto" and has_alpha and np.min(alpha) < 250):
            # Alpha-based extraction
            subject = (alpha >= alpha_threshold).astype(np.uint8) * 255
            if invert:
                subject = 255 - subject
            return subject

        # Convert to RGB and Gray for color/luminance analysis
        rgb = arr[:, :, :3]
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        if bg_mode == "otsu":
            thresh_val, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            subject = (gray < thresh_val).astype(np.uint8) * 255

        elif bg_mode == "light_bg":
            # Distance from pure white
            dist_from_white = np.linalg.norm(255.0 - rgb.astype(np.float32), axis=2)
            subject = (dist_from_white > float(color_tolerance)).astype(np.uint8) * 255

        elif bg_mode == "dark_bg":
            # Distance from pure black
            dist_from_black = np.linalg.norm(rgb.astype(np.float32), axis=2)
            subject = (dist_from_black > float(color_tolerance)).astype(np.uint8) * 255

        else:
            # "auto" for opaque images: sample borders & corners
            h, w = gray.shape[:2]
            # Sample border pixels (top, bottom, left, right)
            border_samples = np.concatenate([
                rgb[0, :].reshape(-1, 3),
                rgb[h - 1, :].reshape(-1, 3),
                rgb[:, 0].reshape(-1, 3),
                rgb[:, w - 1].reshape(-1, 3)
            ], axis=0)

            bg_median = np.median(border_samples, axis=0)
            diff = np.linalg.norm(rgb.astype(np.float32) - bg_median.astype(np.float32), axis=2)
            subject = (diff > float(color_tolerance)).astype(np.uint8) * 255

            # If almost all or none detected, fall back to Otsu
            subj_ratio = np.sum(subject > 0) / float(h * w)
            if subj_ratio < 0.01 or subj_ratio > 0.98:
                thresh_val, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                subject = (gray < thresh_val).astype(np.uint8) * 255

        if invert:
            subject = 255 - subject

        return subject

    @staticmethod
    def generate_cutout(
        img: Image.Image,
        target_width_mm: float = 80.0,
        target_height_mm: Optional[float] = None,
        offset_mm: float = 2.0,
        bg_mode: str = "auto",
        color_tolerance: int = 25,
        keep_interior_holes: bool = False,
        min_hole_area_mm2: float = 3.0,
        smoothness: float = 1.0,
        corner_sharpness_deg: float = 65.0,
        smooth_iterations: int = 1,
        add_hanging_loop: bool = False,
        hanging_loop_dia_mm: float = 3.5,
        hanging_loop_collar_mm: float = 2.5,
        hanging_loop_pos: str = "top",  # "top", "top-left", "top-right"
        add_standee_tab: bool = False,
        standee_tab_w_mm: float = 15.0,
        standee_tab_h_mm: float = 4.0,
        invert_mask: bool = False
    ) -> CutoutResult:
        """
        Calculates the complete vector cutout contour for an image.
        Returns a CutoutResult object with millimeter coordinates and metrics.
        """
        orig_w, orig_h = img.size
        if target_height_mm is None or target_height_mm <= 0:
            target_height_mm = target_width_mm * (orig_h / max(1, orig_w))

        # Scale factors: pixels to millimeters and vice versa
        scale_x = target_width_mm / max(1, orig_w)
        scale_y = target_height_mm / max(1, orig_h)
        px_per_mm = (1.0 / scale_x + 1.0 / scale_y) / 2.0

        # 1. Subject extraction
        raw_mask = AutoCutoutGenerator.extract_subject_mask(
            img, bg_mode=bg_mode, color_tolerance=color_tolerance, invert=invert_mask
        )

        # 2. Add generous padding so offsets and tabs never clip at the canvas borders
        pad_mm = max(10.0, abs(offset_mm) + max(hanging_loop_collar_mm * 3, standee_tab_h_mm * 2) + 5.0)
        pad_px = int(math.ceil(pad_mm * px_per_mm))
        padded_mask = cv2.copyMakeBorder(
            raw_mask, pad_px, pad_px, pad_px, pad_px,
            cv2.BORDER_CONSTANT, value=0
        )

        # 3. Apply Offset using Euclidean Distance Transform (ultra-smooth rounded offset)
        offset_px = offset_mm * px_per_mm
        if abs(offset_px) < 0.2:
            cutout_mask = padded_mask.copy()
        elif offset_px > 0:
            # Outward offset (dilation)
            bg = 255 - padded_mask
            dist = cv2.distanceTransform(bg, cv2.DIST_L2, 5)
            cutout_mask = ((dist <= offset_px) | (padded_mask > 0)).astype(np.uint8) * 255
        else:
            # Inward offset (erosion)
            dist = cv2.distanceTransform(padded_mask, cv2.DIST_L2, 5)
            cutout_mask = (dist >= abs(offset_px)).astype(np.uint8) * 255

        # Small morphological closing to bridge subpixel gaps
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cutout_mask = cv2.morphologyEx(cutout_mask, cv2.MORPH_CLOSE, kernel_close)

        # Check if any subject exists
        ys, xs = np.where(cutout_mask > 0)
        if len(ys) == 0 or len(xs) == 0:
            # Fallback to outer bounding box
            min_x_mm, min_y_mm = 0.0, 0.0
            max_x_mm, max_y_mm = target_width_mm, target_height_mm
            rect_contour = [
                (min_x_mm, min_y_mm),
                (max_x_mm, min_y_mm),
                (max_x_mm, max_y_mm),
                (min_x_mm, max_y_mm),
                (min_x_mm, min_y_mm)
            ]
            return CutoutResult(
                contours=[rect_contour],
                width_mm=target_width_mm,
                height_mm=target_height_mm,
                bounding_box=(0.0, 0.0, target_width_mm, target_height_mm),
                mask_preview=raw_mask,
                has_holes=False
            )

        hanging_hole_center_mm: Optional[Tuple[float, float]] = None
        hanging_hole_contour: Optional[List[Tuple[float, float]]] = None

        # 4. Add Hanging Loop (Keychain / Ornament)
        if add_hanging_loop:
            r_hole_mm = hanging_loop_dia_mm / 2.0
            r_outer_mm = r_hole_mm + hanging_loop_collar_mm
            r_outer_px = int(round(r_outer_mm * px_per_mm))
            r_hole_px = int(round(r_hole_mm * px_per_mm))

            # Locate anchor point at top
            min_y_px = np.min(ys)
            top_xs = xs[ys == min_y_px]

            if hanging_loop_pos == "top-left":
                anchor_x_px = int(np.min(top_xs))
            elif hanging_loop_pos == "top-right":
                anchor_x_px = int(np.max(top_xs))
            else:  # "top"
                anchor_x_px = int(np.mean(top_xs))

            # Center loop so it overlaps with the top boundary
            loop_center_y_px = min_y_px - r_outer_px + int(round(1.5 * px_per_mm))
            loop_center_x_px = anchor_x_px

            # Draw outer collar on mask
            cv2.circle(cutout_mask, (loop_center_x_px, loop_center_y_px), r_outer_px, 255, -1)

            # Record hanging hole in mm
            hole_cx_mm = (loop_center_x_px - pad_px) * scale_x
            hole_cy_mm = (loop_center_y_px - pad_px) * scale_y
            hanging_hole_center_mm = (hole_cx_mm, hole_cy_mm)

            # Generate circular hole contour
            hole_pts = []
            steps = 36
            for s in range(steps):
                ang = (s / float(steps)) * 2.0 * math.pi
                hx = hole_cx_mm + r_hole_mm * math.cos(ang)
                hy = hole_cy_mm + r_hole_mm * math.sin(ang)
                hole_pts.append((hx, hy))
            hole_pts.append(hole_pts[0])
            hanging_hole_contour = hole_pts

        # 5. Add Standee Base Tab
        if add_standee_tab:
            tab_w_px = int(round(standee_tab_w_mm * px_per_mm))
            tab_h_px = int(round(standee_tab_h_mm * px_per_mm))

            # Re-query y positions after loop
            ys, xs = np.where(cutout_mask > 0)
            max_y_px = np.max(ys)
            bottom_xs = xs[ys == max_y_px]
            center_x_px = int(np.mean(bottom_xs))

            pt1 = (center_x_px - tab_w_px // 2, max_y_px - 2)
            pt2 = (center_x_px + tab_w_px // 2, max_y_px + tab_h_px)
            cv2.rectangle(cutout_mask, pt1, pt2, 255, -1)

        # 6. Contour Extraction
        # Hierarchy: [Next, Previous, First_Child, Parent]
        mode_ret = cv2.RETR_CCOMP if keep_interior_holes else cv2.RETR_EXTERNAL
        contours, hierarchy = cv2.findContours(cutout_mask, mode_ret, cv2.CHAIN_APPROX_NONE)

        if not contours or hierarchy is None:
            return CutoutResult(
                contours=[],
                width_mm=target_width_mm,
                height_mm=target_height_mm,
                bounding_box=(0.0, 0.0, target_width_mm, target_height_mm),
                mask_preview=raw_mask
            )

        processed_contours: List[List[Tuple[float, float]]] = []
        min_hole_px = (min_hole_area_mm2) * (px_per_mm ** 2)

        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            # If internal hole, check min hole area
            is_hole = (hierarchy[0][i][3] != -1)
            if is_hole and area < min_hole_px:
                continue
            if not is_hole and area < 20:
                continue

            # RDP Polygon Simplification
            epsilon = max(0.15, smoothness * 0.8)
            approx = cv2.approxPolyDP(c, epsilon, closed=True)
            if len(approx) < 3:
                continue

            pts = approx.reshape(-1, 2).astype(np.float64)

            # Chaikin Curve Smoothing
            if smooth_iterations > 0 and len(pts) > 4:
                pts = corner_preserving_smooth(
                    pts,
                    corner_angle_thresh_deg=corner_sharpness_deg,
                    iterations=smooth_iterations
                )

            # Convert back from padded pixel space to mm
            mm_pts = [
                ((float(p[0]) - pad_px) * scale_x, (float(p[1]) - pad_px) * scale_y)
                for p in pts
            ]
            if mm_pts[0] != mm_pts[-1]:
                mm_pts.append(mm_pts[0])

            processed_contours.append(mm_pts)

        # If hanging hole exists, append it as an inner cut loop
        if hanging_hole_contour:
            processed_contours.append(hanging_hole_contour)

        # Calculate bounding box in mm
        all_x = [p[0] for poly in processed_contours for p in poly]
        all_y = [p[1] for poly in processed_contours for p in poly]
        if all_x and all_y:
            bb = (min(all_x), min(all_y), max(all_x), max_y := max(all_y))
            total_w = bb[2] - bb[0]
            total_h = bb[3] - bb[1]
        else:
            bb = (0.0, 0.0, target_width_mm, target_height_mm)
            total_w = target_width_mm
            total_h = target_height_mm

        # Generate SVG string
        svg_str = AutoCutoutGenerator.contours_to_svg(
            processed_contours,
            bounding_box=bb,
            source_img=img,
            embed_image=False,
            target_width_mm=target_width_mm,
            target_height_mm=target_height_mm
        )

        return CutoutResult(
            contours=processed_contours,
            width_mm=total_w,
            height_mm=total_h,
            bounding_box=bb,
            mask_preview=padded_mask,
            has_holes=(len(processed_contours) > 1),
            hanging_hole_center_mm=hanging_hole_center_mm,
            svg_data=svg_str
        )

    @staticmethod
    def contours_to_svg(
        contours: List[List[Tuple[float, float]]],
        bounding_box: Tuple[float, float, float, float],
        source_img: Optional[Image.Image] = None,
        embed_image: bool = False,
        target_width_mm: float = 80.0,
        target_height_mm: float = 80.0,
        stroke_color: str = "#FF2A2A",  # LightBurn standard C02 Red for Cut
        stroke_width: float = 0.2,
        fill_color: str = "none"
    ) -> str:
        """
        Exports vector contours to clean, standard SVG XML.
        Optionally embeds base64 PNG raster image on an Engrave layer for Print & Cut.
        """
        min_x, min_y, max_x, max_y = bounding_box
        w_mm = max(1.0, max_x - min_x)
        h_mm = max(1.0, max_y - min_y)

        # Normalize paths relative to bounding box min_x, min_y
        path_data = []
        for poly in contours:
            if not poly or len(poly) < 2:
                continue
            d = [f"M {poly[0][0] - min_x:.3f} {poly[0][1] - min_y:.3f}"]
            for pt in poly[1:]:
                d.append(f"L {pt[0] - min_x:.3f} {pt[1] - min_y:.3f}")
            d.append("Z")
            path_data.append(" ".join(d))

        full_d = " ".join(path_data)

        # Optional raster image embedding for Print & Cut
        image_tag = ""
        if embed_image and source_img is not None:
            buf = io.BytesIO()
            source_img.save(buf, format="PNG")
            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
            img_x = 0.0 - min_x
            img_y = 0.0 - min_y
            image_tag = f"""  <!-- Engrave Layer (Bitmap) -->
  <g id="layer_0_engrave">
    <image x="{img_x:.3f}" y="{img_y:.3f}" width="{target_width_mm:.3f}" height="{target_height_mm:.3f}"
           href="data:image/png;base64,{b64_str}" />
  </g>
"""

        svg = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
     width="{w_mm:.2f}mm" height="{h_mm:.2f}mm"
     viewBox="0 0 {w_mm:.2f} {h_mm:.2f}">
  <title>LaserForge Cutout</title>
  <desc>Generated by LaserForge Auto Image-to-SVG Cutout Tool</desc>
{image_tag}  <!-- Cut Layer (Vector Cutout Contour) -->
  <g id="layer_1_cut">
    <path d="{full_d}" fill="{fill_color}" stroke="{stroke_color}" stroke-width="{stroke_width:.2f}" fill-rule="evenodd" />
  </g>
</svg>
"""
        return svg

    @staticmethod
    def export_svg_file(
        result: CutoutResult,
        output_filepath: str,
        source_img: Optional[Image.Image] = None,
        embed_image: bool = False,
        target_width_mm: float = 80.0,
        target_height_mm: float = 80.0,
        stroke_color: str = "#FF2A2A"
    ):
        """Saves generated cutout to an SVG file on disk."""
        svg = AutoCutoutGenerator.contours_to_svg(
            result.contours,
            bounding_box=result.bounding_box,
            source_img=source_img,
            embed_image=embed_image,
            target_width_mm=target_width_mm,
            target_height_mm=target_height_mm,
            stroke_color=stroke_color
        )
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(svg)

    @staticmethod
    def create_path_entity(
        result: CutoutResult,
        layer_id: int = 2,  # Layer 2 (C02 Red) standard cut layer
        name: str = "Cutout",
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> PathEntity:
        """Creates a ready-to-insert LaserForge PathEntity."""
        return PathEntity(
            layer_id=layer_id,
            name=name,
            x=origin_x,
            y=origin_y,
            contours=result.contours,
            closed=True
        )


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="LaserForge Auto Image to SVG Cutout Generator")
    parser.add_argument("input_image", help="Path to input image file (PNG, JPG, WEBP, etc.)")
    parser.add_argument("output_svg", nargs="?", default=None, help="Output SVG filepath (defaults to <image>_cutout.svg)")
    parser.add_argument("--offset", type=float, default=2.0, help="Cutout margin offset in mm (default: 2.0)")
    parser.add_argument("--width", type=float, default=80.0, help="Target width in mm (default: 80.0)")
    parser.add_argument("--holes", action="store_true", help="Keep interior cutout holes")
    parser.add_argument("--smooth", type=float, default=1.0, help="Curve smoothness (default: 1.0)")
    parser.add_argument("--loop", action="store_true", help="Add hanging loop for keychain / ornament")
    parser.add_argument("--standee", action="store_true", help="Add standee base tab for acrylic slot")
    parser.add_argument("--embed", action="store_true", help="Embed raster image in SVG for print-and-cut")

    args = parser.parse_args()

    if not os.path.exists(args.input_image):
        print(f"Error: Input file '{args.input_image}' not found.")
        sys.exit(1)

    out_svg = args.output_svg
    if not out_svg:
        base, _ = os.path.splitext(args.input_image)
        out_svg = f"{base}_cutout.svg"

    print(f"Loading '{args.input_image}'...")
    pil_image = Image.open(args.input_image)

    print(f"Generating cutout: offset={args.offset}mm, smooth={args.smooth}, holes={args.holes}, loop={args.loop}...")
    cutout = AutoCutoutGenerator.generate_cutout(
        pil_image,
        target_width_mm=args.width,
        offset_mm=args.offset,
        keep_interior_holes=args.holes,
        smoothness=args.smooth,
        add_hanging_loop=args.loop,
        add_standee_tab=args.standee
    )

    AutoCutoutGenerator.export_svg_file(
        cutout, out_svg,
        source_img=pil_image,
        embed_image=args.embed,
        target_width_mm=args.width
    )
    print(f"✅ Success! Cutout saved to: {out_svg}")
    print(f"   Contours: {len(cutout.contours)}, Dimensions: {cutout.width_mm:.1f} x {cutout.height_mm:.1f} mm")
