"""Image-analysis primitives shared by the detectors."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

WASD_TEMPLATE_NAMES = ("w", "a", "s", "d", "w_rev", "a_rev", "s_rev", "d_rev")
BITE_TEMPLATE_NAME = "bite"


@dataclass(frozen=True)
class Match:
    name: str
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def load_templates(directory: str | Path, names: Iterable[str]) -> Dict[str, np.ndarray]:
    """Load ``<name>.png`` files that exist in ``directory`` as grayscale arrays."""
    directory = Path(directory)
    templates: Dict[str, np.ndarray] = {}
    for name in names:
        path = directory / f"{name}.png"
        if not path.exists():
            continue
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            log.warning("Could not read template %s", path)
            continue
        templates[name] = to_gray(image)
    return templates


def iou(a: Match, b: Match) -> float:
    ix = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    iy = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    inter = ix * iy
    if inter == 0:
        return 0.0
    union = a.width * a.height + b.width * b.height - inter
    return inter / union


def non_max_suppression(matches: Sequence[Match], max_overlap: float = 0.3) -> List[Match]:
    """Keep the strongest match among overlapping candidates (across all names)."""
    kept: List[Match] = []
    for candidate in sorted(matches, key=lambda m: m.score, reverse=True):
        if all(iou(candidate, k) <= max_overlap for k in kept):
            kept.append(candidate)
    return kept


def match_all(
    image: np.ndarray, template: np.ndarray, threshold: float, name: str = ""
) -> List[Match]:
    """Return every non-overlapping location where ``template`` scores >= threshold."""
    gray = to_gray(image)
    tmpl = to_gray(template)
    th, tw = tmpl.shape[:2]
    if th > gray.shape[0] or tw > gray.shape[1]:
        return []
    result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    candidates = [Match(name, int(x), int(y), tw, th, float(result[y, x])) for y, x in zip(ys, xs)]
    return non_max_suppression(candidates)


def match_best(image: np.ndarray, template: np.ndarray, name: str = "") -> Optional[Match]:
    gray = to_gray(image)
    tmpl = to_gray(template)
    th, tw = tmpl.shape[:2]
    if th > gray.shape[0] or tw > gray.shape[1]:
        return None
    result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return Match(name, int(max_loc[0]), int(max_loc[1]), tw, th, float(max_val))


def hsv_mask(image_bgr: np.ndarray, lower: Tuple[int, int, int], upper: Tuple[int, int, int]) -> np.ndarray:
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))


def column_extent(mask: np.ndarray, min_column_pixels: int) -> Optional[Tuple[int, int]]:
    """Leftmost/rightmost column that contains at least ``min_column_pixels`` mask pixels."""
    counts = np.count_nonzero(mask, axis=0)
    cols = np.flatnonzero(counts >= min_column_pixels)
    if cols.size == 0:
        return None
    return int(cols[0]), int(cols[-1])


def column_centroid(mask: np.ndarray, min_column_pixels: int) -> Optional[float]:
    counts = np.count_nonzero(mask, axis=0)
    cols = np.flatnonzero(counts >= min_column_pixels)
    if cols.size == 0:
        return None
    weights = counts[cols].astype(np.float64)
    return float(np.sum(cols * weights) / np.sum(weights))


def bright_pixel_count(image_bgr: np.ndarray, min_value: int) -> int:
    """Number of pixels whose three channels all exceed ``min_value`` (white-ish UI)."""
    return int(np.count_nonzero(np.all(image_bgr[:, :, :3] >= min_value, axis=2)))


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(cv2.absdiff(a, b)))
