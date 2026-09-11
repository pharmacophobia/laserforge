"""
LaserForge Hardware GPU Acceleration Subsystem.
Leverages NVIDIA CUDA (via PyTorch), OpenCL (via OpenCV), and OpenGL (via Qt)
to accelerate raster image processing, photo engraving dithering, topological vector tracing,
toolpath optimization, and 60-120 FPS interactive canvas rendering.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import math
import numpy as np

# PyTorch CUDA detection
try:
    import torch
    import torch.nn.functional as F
    HAS_TORCH = True
    HAS_CUDA = torch.cuda.is_available()
except ImportError:
    HAS_TORCH = False
    HAS_CUDA = False

# OpenCV OpenCL detection
try:
    import cv2
    HAS_CV2 = True
    HAS_OPENCL = cv2.ocl.haveOpenCL()
    if HAS_OPENCL:
        try:
            cv2.ocl.setUseOpenCL(True)
        except Exception:
            pass
except ImportError:
    HAS_CV2 = False
    HAS_OPENCL = False

# PyQt6 OpenGL detection
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False


# 8x8 Bayer Matrix for GPU Ordered Dithering (normalized to [0, 255])
BAYER_8X8 = np.array([
    [ 0, 32,  8, 40,  2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44,  4, 36, 14, 46,  6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [ 3, 35, 11, 43,  1, 33,  9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47,  7, 39, 13, 45,  5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21]
], dtype=np.float32) * (255.0 / 64.0)


@dataclass
class GPUHardwareInfo:
    cuda_available: bool
    device_name: str
    total_vram_gb: float
    cuda_driver_version: str
    opencl_available: bool
    opengl_available: bool

    def summary_short(self) -> str:
        if self.cuda_available:
            return f"⚡ GPU: {self.device_name} ({self.total_vram_gb:.1f} GB VRAM, CUDA + OpenGL)"
        elif self.opengl_available:
            return "⚡ GPU: OpenGL Hardware Accelerated (CPU Compute)"
        else:
            return "🖥️ CPU Mode: Software Rasterizer"


class GPUAccelerator:
    """
    Orchestrates GPU compute resources across CUDA, OpenCL, and OpenGL.
    Provides thread-safe, high-speed accelerated operations with silent CPU fallback.
    """

    _instance: Optional["GPUHardwareInfo"] = None

    @classmethod
    def get_hardware_info(cls) -> GPUHardwareInfo:
        if cls._instance is None:
            dev_name = "None"
            vram_gb = 0.0
            cuda_ver = "None"

            if HAS_TORCH and HAS_CUDA:
                try:
                    dev_name = torch.cuda.get_device_name(0)
                    props = torch.cuda.get_device_properties(0)
                    vram_gb = props.total_memory / (1024 ** 3)
                    cuda_ver = torch.version.cuda or "Active"
                except Exception:
                    pass

            cls._instance = GPUHardwareInfo(
                cuda_available=HAS_CUDA,
                device_name=dev_name,
                total_vram_gb=vram_gb,
                cuda_driver_version=cuda_ver,
                opencl_available=HAS_OPENCL,
                opengl_available=HAS_OPENGL,
            )
        return cls._instance

    @staticmethod
    def is_cuda_active() -> bool:
        return HAS_TORCH and HAS_CUDA

    @staticmethod
    def is_opencl_active() -> bool:
        return HAS_CV2 and HAS_OPENCL

    @staticmethod
    def is_opengl_active() -> bool:
        return HAS_OPENGL

    # -------------------------------------------------------------
    # CUDA Accelerated Image Pre-Processing & Filters
    # -------------------------------------------------------------
    @classmethod
    def cuda_unsharp_mask(
        cls, image_np: np.ndarray, amount: float = 1.5, radius: float = 1.5
    ) -> np.ndarray:
        """
        Applies Unsharp Mask sharpening using 2D separable Gaussian convolution on CUDA GPU.
        Falls back to CPU if CUDA is unavailable.
        """
        if not (HAS_TORCH and HAS_CUDA and image_np.size > 0):
            return cls._cpu_unsharp_mask(image_np, amount, radius)

        try:
            h, w = image_np.shape[:2]
            is_gray = len(image_np.shape) == 2
            device = torch.device("cuda:0")

            # Format to float tensor (B, C, H, W)
            if is_gray:
                tensor = torch.from_numpy(image_np.astype(np.float32)).unsqueeze(0).unsqueeze(0).to(device)
            else:
                tensor = torch.from_numpy(image_np.astype(np.float32)).permute(2, 0, 1).unsqueeze(0).to(device)

            # Generate 1D Gaussian kernel
            sigma = max(0.1, radius)
            kernel_size = int(math.ceil(sigma * 4.0))
            if kernel_size % 2 == 0:
                kernel_size += 1
            kernel_size = max(3, kernel_size)

            x = torch.arange(kernel_size, dtype=torch.float32, device=device) - (kernel_size - 1) / 2.0
            kernel_1d = torch.exp(-0.5 * (x / sigma) ** 2)
            kernel_1d = kernel_1d / kernel_1d.sum()

            channels = 1 if is_gray else tensor.shape[1]
            k_x = kernel_1d.view(1, 1, 1, kernel_size).repeat(channels, 1, 1, 1)
            k_y = kernel_1d.view(1, 1, kernel_size, 1).repeat(channels, 1, 1, 1)

            pad = kernel_size // 2
            blurred = F.conv2d(tensor, k_x, padding=(0, pad), groups=channels)
            blurred = F.conv2d(blurred, k_y, padding=(pad, 0), groups=channels)

            # High pass sharpening
            sharpened = tensor + amount * (tensor - blurred)
            sharpened = torch.clamp(sharpened, 0.0, 255.0).to(torch.uint8)

            if is_gray:
                out = sharpened.squeeze().cpu().numpy()
            else:
                out = sharpened.squeeze().permute(1, 2, 0).cpu().numpy()
            return out

        except Exception:
            # Silent fallback to CPU if GPU out of memory or error
            return cls._cpu_unsharp_mask(image_np, amount, radius)

    @classmethod
    def cuda_adjust_gamma_contrast(
        cls, image_np: np.ndarray, gamma: float = 1.0, contrast: float = 1.0
    ) -> np.ndarray:
        """
        Applies elementwise non-linear gamma curve and contrast adjustment in parallel on CUDA.
        """
        if not (HAS_TORCH and HAS_CUDA and image_np.size > 0):
            return cls._cpu_adjust_gamma_contrast(image_np, gamma, contrast)

        try:
            device = torch.device("cuda:0")
            tensor = torch.from_numpy(image_np.astype(np.float32)).to(device)

            # Normalize to [0, 1]
            norm = tensor / 255.0

            # Gamma curve
            if abs(gamma - 1.0) > 0.01 and gamma > 0:
                norm = torch.pow(norm, 1.0 / gamma)

            # Centered contrast
            if abs(contrast - 1.0) > 0.01:
                norm = (norm - 0.5) * contrast + 0.5

            result = torch.clamp(norm * 255.0, 0.0, 255.0).to(torch.uint8)
            return result.cpu().numpy()

        except Exception:
            return cls._cpu_adjust_gamma_contrast(image_np, gamma, contrast)

    @classmethod
    def cuda_ordered_dither(cls, image_np: np.ndarray) -> np.ndarray:
        """
        GPU-accelerated Bayer 8x8 ordered dithering.
        Tiles the Bayer threshold matrix across the image tensor and evaluates millions of pixels simultaneously.
        Returns binary uint8 array (1 for laser burn pixel, 0 for empty).
        """
        if not (HAS_TORCH and HAS_CUDA and image_np.size > 0):
            return cls._cpu_ordered_dither(image_np)

        try:
            device = torch.device("cuda:0")
            h, w = image_np.shape[:2]

            # Convert to grayscale float tensor
            if len(image_np.shape) == 3:
                r, g, b = image_np[:, :, 0], image_np[:, :, 1], image_np[:, :, 2]
                gray_np = 0.299 * r + 0.587 * g + 0.114 * b
            else:
                gray_np = image_np

            tensor = torch.from_numpy(gray_np.astype(np.float32)).to(device)

            # Invert: darker areas require more laser burns
            inverted = 255.0 - tensor

            # Tile Bayer matrix to image dimensions
            bayer_tensor = torch.from_numpy(BAYER_8X8).to(device)
            rep_y = int(math.ceil(h / 8.0))
            rep_x = int(math.ceil(w / 8.0))
            tiled_bayer = bayer_tensor.repeat(rep_y, rep_x)[:h, :w]

            # Binary comparison on GPU: 1 if pixel is dark enough to trigger laser burn
            dithered = (inverted > tiled_bayer).to(torch.uint8)
            return dithered.cpu().numpy()

        except Exception:
            return cls._cpu_ordered_dither(image_np)

    @classmethod
    def cuda_pairwise_distance_matrix(cls, pts: np.ndarray) -> np.ndarray:
        """
        Computes NxN pairwise Euclidean distance matrix for path optimization on CUDA.
        """
        if not (HAS_TORCH and HAS_CUDA and pts.shape[0] > 0):
            # CPU fallback via vectorization
            d = pts[:, np.newaxis, :] - pts[np.newaxis, :, :]
            return np.sqrt((d ** 2).sum(axis=-1))

        try:
            device = torch.device("cuda:0")
            tensor_pts = torch.from_numpy(pts.astype(np.float32)).to(device)
            # torch.cdist computes pairwise Euclidean distance on CUDA
            dist_mat = torch.cdist(tensor_pts, tensor_pts, p=2.0)
            return dist_mat.cpu().numpy()
        except Exception:
            d = pts[:, np.newaxis, :] - pts[np.newaxis, :, :]
            return np.sqrt((d ** 2).sum(axis=-1))

    # -------------------------------------------------------------
    # CPU Fallback Implementations
    # -------------------------------------------------------------
    @staticmethod
    def _cpu_unsharp_mask(image_np: np.ndarray, amount: float, radius: float) -> np.ndarray:
        if HAS_CV2 and image_np.size > 0:
            k = int(math.ceil(radius * 4.0)) | 1
            blurred = cv2.GaussianBlur(image_np, (k, k), radius)
            sharpened = cv2.addWeighted(image_np, 1.0 + amount, blurred, -amount, 0)
            return np.clip(sharpened, 0, 255).astype(np.uint8)
        return image_np

    @staticmethod
    def _cpu_adjust_gamma_contrast(image_np: np.ndarray, gamma: float, contrast: float) -> np.ndarray:
        arr = image_np.astype(np.float32) / 255.0
        if abs(gamma - 1.0) > 0.01 and gamma > 0:
            arr = np.power(arr, 1.0 / gamma)
        if abs(contrast - 1.0) > 0.01:
            arr = (arr - 0.5) * contrast + 0.5
        return np.clip(arr * 255.0, 0, 255).astype(np.uint8)

    @staticmethod
    def _cpu_ordered_dither(image_np: np.ndarray) -> np.ndarray:
        h, w = image_np.shape[:2]
        if len(image_np.shape) == 3:
            gray = 0.299 * image_np[:, :, 0] + 0.587 * image_np[:, :, 1] + 0.114 * image_np[:, :, 2]
        else:
            gray = image_np.astype(np.float32)

        inverted = 255.0 - gray
        rep_y = int(math.ceil(h / 8.0))
        rep_x = int(math.ceil(w / 8.0))
        tiled = np.tile(BAYER_8X8, (rep_y, rep_x))[:h, :w]
        return (inverted > tiled).astype(np.uint8)
