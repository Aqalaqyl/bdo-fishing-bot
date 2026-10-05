"""Detectors for the three visual stages of BDO fishing.

1. :class:`BiteDetector`  - "a fish is on the line, press Space".
2. :class:`GaugeTracker`  - the bouncing marker that must stop in the blue zone.
3. :class:`WasdReader`    - the row of W/A/S/D keys (some reversed) to type.

Everything here is pure image math over frames that the caller captures, so it
can be exercised offline against saved screenshots or synthetic images.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from . import vision
from .config import Config
from .vision import Match

log = logging.getLogger(__name__)

KEY_FOR_TEMPLATE = {"w": "w", "a": "a", "s": "s", "d": "d"}


# --------------------------------------------------------------------------
# Bite detection
# --------------------------------------------------------------------------
class BiteDetector:
    """Decides whether the bite prompt is on screen.

    Modes:

    * ``template`` - match ``templates/bite.png`` (most reliable once captured).
    * ``bright``   - count near-white pixels; the prompt is a bright icon on
      top of darker water/ground.
    * ``change``   - compare against a baseline frame captured right after
      casting and trigger on a large difference.
    * ``auto``     - ``template`` if the template exists, else ``bright``.
    """

    def __init__(self, cfg: Config, templates: Dict[str, np.ndarray]) -> None:
        self.cfg = cfg
        self.template = templates.get(vision.BITE_TEMPLATE_NAME)
        mode = cfg.bite_detection
        if mode == "auto":
            mode = "template" if self.template is not None else "bright"
        if mode == "template" and self.template is None:
            raise ValueError("bite_detection='template' but templates/bite.png is missing")
        self.mode = mode
        self.baseline: Optional[np.ndarray] = None
        self._streak = 0
        self.last_score: float = 0.0

    def reset(self, baseline: Optional[np.ndarray] = None) -> None:
        self.baseline = baseline
        self._streak = 0

    def frame_is_positive(self, frame: np.ndarray) -> bool:
        if self.mode == "template":
            best = vision.match_best(frame, self.template, vision.BITE_TEMPLATE_NAME)
            self.last_score = best.score if best else 0.0
            return best is not None and best.score >= self.cfg.template_threshold
        if self.mode == "bright":
            count = vision.bright_pixel_count(frame, self.cfg.bite_bright_value)
            self.last_score = float(count)
            return count >= self.cfg.bite_bright_min_pixels
        if self.mode == "change":
            if self.baseline is None:
                self.baseline = frame.copy()
                return False
            diff = vision.mean_abs_diff(frame, self.baseline)
            self.last_score = diff
            return diff >= self.cfg.bite_change_threshold
        raise ValueError(f"Unknown bite_detection mode {self.mode!r}")

    def update(self, frame: np.ndarray) -> bool:
        """Feed one frame; returns True once enough consecutive frames are positive."""
        if self.frame_is_positive(frame):
            self._streak += 1
        else:
            self._streak = 0
        return self._streak >= self.cfg.bite_confirm_frames


# --------------------------------------------------------------------------
# Gauge minigame
# --------------------------------------------------------------------------
@dataclass
class GaugeReading:
    zone_left: int
    zone_right: int
    marker_x: Optional[float]

    @property
    def zone_width(self) -> int:
        return self.zone_right - self.zone_left


def analyze_gauge(frame: np.ndarray, cfg: Config) -> Optional[GaugeReading]:
    """Locate the blue success zone and the white marker inside ``frame``.

    Returns ``None`` when no gauge is visible.
    """
    zone_mask = vision.hsv_mask(frame, cfg.gauge_zone_hsv_lower, cfg.gauge_zone_hsv_upper)
    extent = vision.column_extent(zone_mask, cfg.gauge_min_column_pixels)
    if extent is None or extent[1] - extent[0] < cfg.gauge_min_zone_width:
        return None
    zone_left, zone_right = extent

    marker_mask = vision.hsv_mask(frame, cfg.gauge_marker_hsv_lower, cfg.gauge_marker_hsv_upper)
    # Only look for the marker on the rows the zone occupies; this ignores
    # white text drawn above/below the bar.
    rows = np.flatnonzero(np.count_nonzero(zone_mask, axis=1))
    if rows.size:
        marker_mask = marker_mask[rows[0] : rows[-1] + 1]
    marker_x = vision.column_centroid(marker_mask, cfg.gauge_min_column_pixels)
    return GaugeReading(zone_left, zone_right, marker_x)


class GaugeTracker:
    """Tracks marker motion across frames and says when to press."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.prev_x: Optional[float] = None
        self.velocity: float = 0.0
        self.frames_seen = 0

    def reset(self) -> None:
        self.prev_x = None
        self.velocity = 0.0
        self.frames_seen = 0

    def should_press(self, reading: GaugeReading) -> bool:
        if reading.marker_x is None:
            return False
        self.frames_seen += 1
        x = reading.marker_x
        if self.prev_x is not None:
            # Exponential smoothing keeps a single noisy frame from flipping the sign.
            self.velocity = 0.6 * (x - self.prev_x) + 0.4 * self.velocity
        self.prev_x = x

        predicted = x + self.velocity * self.cfg.gauge_lead_frames
        margin = min(self.cfg.gauge_zone_margin_px, max(0, reading.zone_width // 2 - 1))
        left = reading.zone_left + margin
        right = reading.zone_right - margin
        inside_now = left <= x <= right
        inside_soon = left <= predicted <= right
        # The predicted position accounts for input latency. Without velocity
        # information (first frame) only trust the current position.
        if self.frames_seen < 2:
            return inside_now and inside_soon
        return inside_soon


# --------------------------------------------------------------------------
# WASD minigame
# --------------------------------------------------------------------------
@dataclass
class WasdReading:
    matches: List[Match]
    keys: List[str]


class WasdReader:
    def __init__(self, cfg: Config, templates: Dict[str, np.ndarray]) -> None:
        self.cfg = cfg
        self.templates = {n: t for n, t in templates.items() if n in vision.WASD_TEMPLATE_NAMES}
        if not self.templates:
            log.warning(
                "No WASD templates found in %s; the key minigame cannot be solved "
                "until you capture them (see README).",
                cfg.templates_dir,
            )

    @property
    def available(self) -> bool:
        return bool(self.templates)

    def key_for(self, template_name: str) -> str:
        if template_name in self.cfg.wasd_reversed_map:
            return self.cfg.wasd_reversed_map[template_name]
        return KEY_FOR_TEMPLATE[template_name]

    def read(self, frame: np.ndarray) -> WasdReading:
        candidates: List[Match] = []
        for name, template in self.templates.items():
            candidates.extend(vision.match_all(frame, template, self.cfg.template_threshold, name))
        matches = sorted(vision.non_max_suppression(candidates), key=lambda m: m.center_x)
        return WasdReading(matches, [self.key_for(m.name) for m in matches])
