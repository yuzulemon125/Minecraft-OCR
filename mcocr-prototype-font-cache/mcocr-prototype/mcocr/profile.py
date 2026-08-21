from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Glyph:
    char: str
    bitmap: np.ndarray
    advance: int
    ink_pixels: int


@dataclass(frozen=True)
class FontProfile:
    name: str
    cell_width: int
    cell_height: int
    space_advance: int
    glyphs: tuple[Glyph, ...]


def _resolve(base_file: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (base_file.parent / path).resolve()
    return path


def _atlas_mask(image: Image.Image, mode: str, threshold: int) -> np.ndarray:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3]
    rgb = rgba[..., :3]

    if mode == "alpha":
        return alpha >= threshold
    if mode == "luma":
        luma = (
            0.2126 * rgb[..., 0]
            + 0.7152 * rgb[..., 1]
            + 0.0722 * rgb[..., 2]
        )
        return luma >= threshold
    if mode == "auto":
        if alpha.min() < 255:
            return alpha >= threshold
        luma = (
            0.2126 * rgb[..., 0]
            + 0.7152 * rgb[..., 1]
            + 0.0722 * rgb[..., 2]
        )
        return luma >= threshold
    raise ValueError(f"Unsupported atlas mask mode: {mode}")


def load_source_profile(profile_path: str | Path) -> FontProfile:
    """Build a FontProfile directly from a source atlas and JSON definition."""
    profile_path = Path(profile_path).resolve()
    with profile_path.open("r", encoding="utf-8") as f:
        cfg: dict[str, Any] = json.load(f)

    atlas_cfg = cfg["atlas"]
    atlas_path = _resolve(profile_path, atlas_cfg["path"])
    if not atlas_path.is_file():
        raise FileNotFoundError(
            f"Font atlas not found: {atlas_path}\n"
            "Put the font image at the path specified by profiles/*.json."
        )

    image = Image.open(atlas_path)
    mask = _atlas_mask(
        image,
        atlas_cfg.get("mask_mode", "auto"),
        int(atlas_cfg.get("threshold", 128)),
    )

    columns = int(atlas_cfg["columns"])
    rows = int(atlas_cfg["rows"])
    cell_width = int(atlas_cfg.get("cell_width", image.width // columns))
    cell_height = int(atlas_cfg.get("cell_height", image.height // rows))
    origin_x = int(atlas_cfg.get("origin_x", 0))
    origin_y = int(atlas_cfg.get("origin_y", 0))

    mapping = cfg["mapping"]
    first_codepoint = int(mapping.get("first_codepoint", 0))
    include = mapping.get("include", [32, 126])
    include_min, include_max = int(include[0]), int(include[1])
    exclude = {int(x) for x in mapping.get("exclude", [])}

    advances = cfg.get("advances", {})
    advance_mode = advances.get("mode", "ink_right_plus_one")
    default_advance = int(advances.get("default", cell_width))
    overrides = {int(k): int(v) for k, v in advances.get("overrides", {}).items()}
    space_advance = int(advances.get("space", 4))

    glyphs: list[Glyph] = []
    for cell_index in range(columns * rows):
        codepoint = first_codepoint + cell_index
        if codepoint < include_min or codepoint > include_max or codepoint in exclude:
            continue
        if codepoint == 32:
            continue

        row, col = divmod(cell_index, columns)
        x0 = origin_x + col * cell_width
        y0 = origin_y + row * cell_height
        bitmap = mask[y0:y0 + cell_height, x0:x0 + cell_width].copy()
        if bitmap.shape != (cell_height, cell_width):
            raise ValueError(f"Atlas cell {cell_index} extends beyond the image")
        if not bitmap.any():
            continue

        if codepoint in overrides:
            advance = overrides[codepoint]
        elif advance_mode == "ink_right_plus_one":
            occupied_columns = np.flatnonzero(bitmap.any(axis=0))
            advance = int(occupied_columns[-1]) + 2
        elif advance_mode == "fixed":
            advance = default_advance
        else:
            raise ValueError(f"Unsupported advance mode: {advance_mode}")

        advance = max(1, min(advance, cell_width + 1))
        glyphs.append(Glyph(chr(codepoint), bitmap, advance, int(bitmap.sum())))

    if not glyphs:
        raise ValueError("No glyphs were loaded from the configured atlas")

    return FontProfile(
        name=str(cfg.get("name", profile_path.stem)),
        cell_width=cell_width,
        cell_height=cell_height,
        space_advance=space_advance,
        glyphs=tuple(glyphs),
    )


def save_compiled_profile(profile: FontProfile, output_path: str | Path) -> Path:
    """Save glyph bitmaps and metrics in a runtime-ready NPZ file."""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    codepoints = np.asarray([ord(g.char) for g in profile.glyphs], dtype=np.int32)
    bitmaps = np.stack([g.bitmap for g in profile.glyphs]).astype(np.uint8)
    advances = np.asarray([g.advance for g in profile.glyphs], dtype=np.int16)
    ink_pixels = np.asarray([g.ink_pixels for g in profile.glyphs], dtype=np.int16)

    # Uncompressed NPZ: this data is tiny and avoids decompression overhead.
    np.savez(
        output_path,
        format_version=np.asarray([1], dtype=np.int16),
        name=np.asarray(profile.name),
        cell_width=np.asarray([profile.cell_width], dtype=np.int16),
        cell_height=np.asarray([profile.cell_height], dtype=np.int16),
        space_advance=np.asarray([profile.space_advance], dtype=np.int16),
        codepoints=codepoints,
        bitmaps=bitmaps,
        advances=advances,
        ink_pixels=ink_pixels,
    )
    return output_path


def load_compiled_profile(data_path: str | Path) -> FontProfile:
    """Load a runtime-ready font profile without reading the source atlas."""
    data_path = Path(data_path).resolve()
    if not data_path.is_file():
        raise FileNotFoundError(
            f"Compiled font data not found: {data_path}\n"
            "Run: python tools/build_font_data.py"
        )

    with np.load(data_path, allow_pickle=False) as data:
        version = int(data["format_version"][0])
        if version != 1:
            raise ValueError(f"Unsupported compiled font format: {version}")
        name = str(data["name"].item())
        cell_width = int(data["cell_width"][0])
        cell_height = int(data["cell_height"][0])
        space_advance = int(data["space_advance"][0])
        codepoints = data["codepoints"].astype(np.int32)
        bitmaps = data["bitmaps"].astype(bool)
        advances = data["advances"].astype(np.int16)
        ink_pixels = data["ink_pixels"].astype(np.int16)

    if not (
        len(codepoints) == len(bitmaps) == len(advances) == len(ink_pixels)
    ):
        raise ValueError("Compiled font arrays have inconsistent lengths")

    glyphs = tuple(
        Glyph(
            chr(int(codepoints[i])),
            bitmaps[i],
            int(advances[i]),
            int(ink_pixels[i]),
        )
        for i in range(len(codepoints))
    )
    return FontProfile(name, cell_width, cell_height, space_advance, glyphs)


# Backward-compatible alias for code that explicitly wants source loading.
load_profile = load_source_profile
