from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import sys
from typing import Any

import numpy as np
from PIL import Image

from .preprocess import downsample_grid, find_line_bands, make_mask_candidates
from .profile import FontProfile, Glyph, load_profile


@dataclass(frozen=True)
class OCRResult:
    text: str
    score: float
    profile: str
    mask_name: str
    grid_phase: tuple[int, int]
    lines: int


@dataclass
class _State:
    cost: float
    text: str
    glyph_count: int
    matched_ink: int


class MinecraftOCR:
    def __init__(self, config_path: str | Path = "config.json") -> None:
        self.config_path = Path(config_path).resolve()
        with self.config_path.open("r", encoding="utf-8") as f:
            self.config: dict[str, Any] = json.load(f)

        profile_value = Path(self.config["profile"])
        if not profile_value.is_absolute():
            profile_value = (self.config_path.parent / profile_value).resolve()
        self.profile: FontProfile = load_profile(profile_value)

    def recognize_file(
        self,
        image_path: str | Path,
        gui_scale: int | None = None,
    ) -> OCRResult:
        image_path = Path(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Input image not found: {image_path}")
        image = Image.open(image_path).convert("RGB")
        return self.recognize_image(image, gui_scale=gui_scale)

    def recognize_image(
        self,
        image: Image.Image,
        gui_scale: int | None = None,
    ) -> OCRResult:
        scale = int(gui_scale or self.config.get("gui_scale", 3))
        if scale < 1:
            raise ValueError("gui_scale must be 1 or greater")

        bin_cfg = self.config.get("binarization", {})
        masks = make_mask_candidates(
            image=image,
            mode=str(bin_cfg.get("mode", "auto")),
            colors=list(bin_cfg.get("colors", [])),
            color_tolerance=int(bin_cfg.get("color_tolerance", 12)),
            luma_threshold=bin_cfg.get("luma_threshold"),
            max_auto_colors=int(bin_cfg.get("max_auto_colors", 8)),
        )
        if not masks:
            return OCRResult("", 0.0, self.profile.name, "none", (0, 0), 0)

        rec_cfg = self.config.get("recognition", {})
        occupancy = float(rec_cfg.get("block_occupancy_threshold", 0.45))
        best: OCRResult | None = None

        for mask_name, mask in masks:
            for phase_y in range(scale):
                for phase_x in range(scale):
                    grid = downsample_grid(
                        mask, scale, phase_x, phase_y, occupancy
                    )
                    result = self._recognize_grid(
                        grid, mask_name, (phase_x, phase_y)
                    )
                    if self._better(result, best):
                        best = result

        if best is None:
            return OCRResult("", 0.0, self.profile.name, "none", (0, 0), 0)
        return best

    @staticmethod
    def _better(candidate: OCRResult, current: OCRResult | None) -> bool:
        if current is None:
            return True
        if bool(candidate.text) != bool(current.text):
            return bool(candidate.text)
        # Prefer confidence, then more recognized non-space characters.
        key_candidate = (candidate.score, len(candidate.text.replace(" ", "")))
        key_current = (current.score, len(current.text.replace(" ", "")))
        return key_candidate > key_current

    def _recognize_grid(
        self,
        grid: np.ndarray,
        mask_name: str,
        phase: tuple[int, int],
    ) -> OCRResult:
        rec_cfg = self.config.get("recognition", {})
        line_gap = int(rec_cfg.get("line_row_gap", 1))
        bands = find_line_bands(grid, max_gap=line_gap)
        if not bands:
            return OCRResult("", 0.0, self.profile.name, mask_name, phase, 0)

        texts: list[str] = []
        scores: list[float] = []
        for top, bottom in bands:
            # Ignore components too tall to plausibly be one font line.
            if bottom - top > self.profile.cell_height * 2:
                continue
            text, score = self._recognize_line(grid, top, bottom)
            text = " ".join(text.strip().split())
            if text:
                texts.append(text)
                scores.append(score)

        if not texts:
            return OCRResult("", 0.0, self.profile.name, mask_name, phase, 0)

        score = float(sum(scores) / len(scores)) if scores else 0.0
        return OCRResult(
            "\n".join(texts),
            max(0.0, min(100.0, score)),
            self.profile.name,
            mask_name,
            phase,
            len(texts),
        )

    def _recognize_line(
        self,
        full_mask: np.ndarray,
        band_top: int,
        band_bottom: int,
    ) -> tuple[str, float]:
        font_h = self.profile.cell_height
        rec_cfg = self.config.get("recognition", {})
        vertical_search = int(rec_cfg.get("vertical_search", font_h))

        # Keep horizontal padding so glyphs with a left bearing can still match.
        active_cols = np.flatnonzero(full_mask[band_top:band_bottom].any(axis=0))
        if active_cols.size == 0:
            return "", 0.0
        left = max(0, int(active_cols[0]) - self.profile.cell_width)
        right = min(full_mask.shape[1], int(active_cols[-1]) + 1 + self.profile.cell_width)

        candidate_tops = range(
            max(0, band_bottom - font_h - vertical_search),
            min(band_top + 1, full_mask.shape[0] - font_h + 1),
        )
        best_text = ""
        best_score = 0.0

        for cell_top in candidate_tops:
            line = full_mask[cell_top:cell_top + font_h, left:right]
            text, score = self._decode_line(line)
            if (score, len(text.replace(" ", ""))) > (
                best_score,
                len(best_text.replace(" ", "")),
            ):
                best_text, best_score = text, score
        return best_text, best_score

    def _decode_line(self, line: np.ndarray) -> tuple[str, float]:
        cfg = self.config.get("recognition", {})
        miss_weight = float(cfg.get("missing_pixel_weight", 1.25))
        extra_weight = float(cfg.get("extra_pixel_weight", 1.0))
        blank_skip_cost = float(cfg.get("blank_skip_cost", 0.08))
        ink_skip_cost = float(cfg.get("ink_skip_cost", 1.8))
        max_cost_per_glyph = float(cfg.get("max_cost_per_glyph", 1.10))
        beam_width = int(cfg.get("beam_width", 20))
        min_chars = int(cfg.get("minimum_characters", 1))

        width = line.shape[1]
        # Add a blank margin; the actual cursor can start before the first ink pixel.
        margin = self.profile.cell_width
        canvas = np.pad(line, ((0, 0), (margin, margin)), constant_values=False)
        width = canvas.shape[1]

        states: list[list[_State]] = [[] for _ in range(width + 1)]
        states[0].append(_State(0.0, "", 0, 0))

        for x in range(width):
            if not states[x]:
                continue
            states[x].sort(key=lambda s: (s.cost / max(1, s.glyph_count), s.cost))
            states[x] = states[x][:beam_width]

            column_has_ink = bool(canvas[:, x].any())
            for state in states[x]:
                # Moving across unused columns handles crop padding and small noise.
                skip = blank_skip_cost if not column_has_ink else ink_skip_cost
                self._push_state(
                    states[x + 1],
                    _State(state.cost + skip, state.text, state.glyph_count, state.matched_ink),
                    beam_width,
                )

                # A space is only allowed over an actually blank run.
                sa = self.profile.space_advance
                if x + sa <= width and not canvas[:, x:x + sa].any():
                    if state.text and not state.text.endswith(" "):
                        self._push_state(
                            states[x + sa],
                            _State(
                                state.cost + 0.05,
                                state.text + " ",
                                state.glyph_count,
                                state.matched_ink,
                            ),
                            beam_width,
                        )

                for glyph in self.profile.glyphs:
                    advance = glyph.advance
                    if x + advance > width:
                        continue
                    template = glyph.bitmap[:, :min(glyph.bitmap.shape[1], advance)]
                    observed = canvas[:, x:x + template.shape[1]]
                    missing = np.logical_and(template, ~observed).sum()
                    extra = np.logical_and(~template, observed).sum()
                    raw_cost = miss_weight * missing + extra_weight * extra
                    normalizer = max(1.0, glyph.ink_pixels)
                    glyph_cost = float(raw_cost / normalizer)
                    if glyph_cost > max_cost_per_glyph:
                        continue

                    self._push_state(
                        states[min(width, x + advance)],
                        _State(
                            state.cost + glyph_cost,
                            state.text + glyph.char,
                            state.glyph_count + 1,
                            state.matched_ink + glyph.ink_pixels,
                        ),
                        beam_width,
                    )

        endings: list[_State] = []
        # Permit remaining blank right margin without requiring exact end alignment.
        for x in range(max(0, width - margin * 2), width + 1):
            endings.extend(states[x])
        endings = [
            s for s in endings
            if s.glyph_count >= min_chars and s.text.strip()
        ]
        if not endings:
            return "", 0.0

        endings.sort(
            key=lambda s: (
                s.cost / max(1, s.glyph_count),
                -s.glyph_count,
            )
        )
        best = endings[0]
        average_cost = best.cost / max(1, best.glyph_count)
        score = 100.0 * math.exp(-1.8 * average_cost)
        return best.text.strip(), score

    @staticmethod
    def _push_state(bucket: list[_State], state: _State, beam_width: int) -> None:
        bucket.append(state)
        if len(bucket) > beam_width * 3:
            bucket.sort(key=lambda s: (s.cost / max(1, s.glyph_count), s.cost))
            del bucket[beam_width:]

    def check(self) -> list[str]:
        messages = [
            f"config: {self.config_path}",
            f"profile: {self.profile.name}",
            f"glyphs: {len(self.profile.glyphs)}",
            f"cell: {self.profile.cell_width}x{self.profile.cell_height}",
            f"space advance: {self.profile.space_advance}",
        ]
        return messages
