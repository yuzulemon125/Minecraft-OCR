from __future__ import annotations

import numpy as np
from PIL import Image


def otsu_threshold(gray: np.ndarray) -> int:
    values = np.clip(gray, 0, 255).astype(np.uint8)
    histogram = np.bincount(values.ravel(), minlength=256).astype(np.float64)
    total = values.size
    if total == 0:
        return 127

    sum_total = np.dot(np.arange(256), histogram)
    sum_background = 0.0
    weight_background = 0.0
    best_variance = -1.0
    best_threshold = 127

    for threshold in range(256):
        weight_background += histogram[threshold]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += threshold * histogram[threshold]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        variance = (
            weight_background
            * weight_foreground
            * (mean_background - mean_foreground) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def _rgb_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _color_mask(rgb: np.ndarray, color: np.ndarray, tolerance: int) -> np.ndarray:
    delta = rgb.astype(np.int16) - color.astype(np.int16)
    distance_sq = np.sum(delta * delta, axis=2)
    return distance_sq <= tolerance * tolerance


def make_mask_candidates(
    image: Image.Image,
    mode: str,
    colors: list[list[int]],
    color_tolerance: int,
    luma_threshold: int | None,
    max_auto_colors: int,
) -> list[tuple[str, np.ndarray]]:
    rgb = _rgb_array(image)
    luma = (
        0.2126 * rgb[..., 0]
        + 0.7152 * rgb[..., 1]
        + 0.0722 * rgb[..., 2]
    ).astype(np.uint8)

    candidates: list[tuple[str, np.ndarray]] = []

    if mode in {"auto", "luma"}:
        threshold = otsu_threshold(luma) if luma_threshold is None else luma_threshold
        candidates.append((f"light>{threshold}", luma > threshold))
        candidates.append((f"dark<{threshold}", luma < threshold))

    if mode in {"auto", "color"}:
        configured = [np.asarray(c, dtype=np.uint8) for c in colors]
        for index, color in enumerate(configured):
            candidates.append(
                (f"configured-color-{index}", _color_mask(rgb, color, color_tolerance))
            )

        if mode == "auto" and not configured:
            # Quantization makes exact PNG colors and nearly equal colors share a bin.
            quantized = (rgb // 8) * 8
            packed = (
                quantized[..., 0].astype(np.uint32) << 16
                | quantized[..., 1].astype(np.uint32) << 8
                | quantized[..., 2].astype(np.uint32)
            )
            unique, counts = np.unique(packed, return_counts=True)
            order = np.argsort(counts)[::-1]
            area = rgb.shape[0] * rgb.shape[1]
            used = 0
            for idx in order:
                count = int(counts[idx])
                # Ignore a dominant background and colors too rare to form glyph blocks.
                if count > area * 0.60 or count < 2:
                    continue
                packed_color = int(unique[idx])
                color = np.array(
                    [
                        (packed_color >> 16) & 255,
                        (packed_color >> 8) & 255,
                        packed_color & 255,
                    ],
                    dtype=np.uint8,
                )
                candidates.append(
                    (
                        f"auto-color-{color.tolist()}",
                        _color_mask(rgb, color, max(color_tolerance, 10)),
                    )
                )
                used += 1
                if used >= max_auto_colors:
                    break

    # Reject unusable all-empty/all-filled masks and exact duplicates.
    filtered: list[tuple[str, np.ndarray]] = []
    seen: set[bytes] = set()
    area = image.width * image.height
    for name, mask in candidates:
        ink = int(mask.sum())
        if ink == 0 or ink >= area * 0.85:
            continue
        signature = np.packbits(mask).tobytes()
        if signature in seen:
            continue
        seen.add(signature)
        filtered.append((name, mask.astype(bool)))
    return filtered


def downsample_grid(
    mask: np.ndarray,
    scale: int,
    phase_x: int,
    phase_y: int,
    occupancy_threshold: float,
) -> np.ndarray:
    view = mask[phase_y:, phase_x:]
    height = (view.shape[0] // scale) * scale
    width = (view.shape[1] // scale) * scale
    if height <= 0 or width <= 0:
        return np.zeros((0, 0), dtype=bool)
    view = view[:height, :width]
    blocks = view.reshape(height // scale, scale, width // scale, scale)
    occupancy = blocks.mean(axis=(1, 3))
    return occupancy >= occupancy_threshold


def find_line_bands(mask: np.ndarray, max_gap: int = 1) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    active = np.flatnonzero(mask.any(axis=1))
    if active.size == 0:
        return []

    bands: list[tuple[int, int]] = []
    start = previous = int(active[0])
    for row in active[1:]:
        row = int(row)
        if row - previous > max_gap + 1:
            bands.append((start, previous + 1))
            start = row
        previous = row
    bands.append((start, previous + 1))
    return bands
