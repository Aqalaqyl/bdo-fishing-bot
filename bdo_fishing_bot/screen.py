"""Fast screen capture built on ``mss``."""

from __future__ import annotations

from typing import Optional

import numpy as np

from .config import Region


class Screen:
    """Grabs BGR frames of arbitrary screen regions.

    A single ``mss`` instance is kept per thread; grabbing a ~800x150 region
    takes roughly 1-3 ms on Windows, which is fast enough to track the gauge
    marker frame by frame.
    """

    def __init__(self) -> None:
        import mss  # imported lazily so the vision code can be unit tested headless

        self._sct = mss.mss()

    def grab(self, region: Region) -> np.ndarray:
        shot = self._sct.grab(region.as_mss())
        frame = np.asarray(shot, dtype=np.uint8)
        # mss returns BGRA; drop alpha and make the array contiguous for OpenCV.
        return np.ascontiguousarray(frame[:, :, :3])

    def grab_full(self, width: Optional[int] = None, height: Optional[int] = None) -> np.ndarray:
        monitor = self._sct.monitors[1]
        region = Region(
            monitor["left"],
            monitor["top"],
            width or monitor["width"],
            height or monitor["height"],
        )
        return self.grab(region)

    def close(self) -> None:
        self._sct.close()
