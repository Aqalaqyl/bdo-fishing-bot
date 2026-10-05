"""The fishing loop: cast -> wait for bite -> hook -> gauge -> WASD -> recast."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import vision
from .config import Config
from .controls import Keyboard
from .detectors import BiteDetector, GaugeTracker, WasdReader, analyze_gauge
from .hotkeys import HotkeyController
from .screen import Screen

log = logging.getLogger(__name__)


@dataclass
class Stats:
    casts: int = 0
    bites: int = 0
    bite_timeouts: int = 0
    gauges_played: int = 0
    wasd_solved: int = 0
    wasd_missed: int = 0
    catches: int = 0
    started_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        minutes = (time.time() - self.started_at) / 60
        return (
            f"{minutes:.1f} min | casts={self.casts} bites={self.bites} "
            f"timeouts={self.bite_timeouts} gauges={self.gauges_played} "
            f"wasd ok/missed={self.wasd_solved}/{self.wasd_missed} catches={self.catches}"
        )


class FishingBot:
    def __init__(
        self,
        cfg: Config,
        screen: Optional[Screen] = None,
        keyboard: Optional[Keyboard] = None,
    ) -> None:
        self.cfg = cfg
        self.screen = screen or Screen()
        self.keyboard = keyboard or Keyboard(cfg.key_hold_s, cfg.jitter_s, cfg.dry_run)
        templates = vision.load_templates(
            cfg.templates_dir, vision.WASD_TEMPLATE_NAMES + (vision.BITE_TEMPLATE_NAME,)
        )
        log.info("Loaded templates: %s", ", ".join(sorted(templates)) or "none")
        self.bite = BiteDetector(cfg, templates)
        self.gauge = GaugeTracker(cfg)
        self.wasd = WasdReader(cfg, templates)
        self.hotkeys = HotkeyController(cfg.pause_hotkey, cfg.stop_hotkey)
        self.stats = Stats()
        self._failures = 0
        if cfg.debug_dir:
            Path(cfg.debug_dir).mkdir(parents=True, exist_ok=True)
        log.info("Bite detection mode: %s", self.bite.mode)

    # ------------------------------------------------------------------ loop
    def run(self, start_delay_s: float = 3.0) -> None:
        self.hotkeys.start()
        log.info("Switch to the game window... starting in %.0f s", start_delay_s)
        time.sleep(start_delay_s)
        try:
            while not self.hotkeys.stopped.is_set():
                if self.cfg.max_casts and self.stats.casts >= self.cfg.max_casts:
                    log.info("Reached max_casts=%d", self.cfg.max_casts)
                    break
                self.hotkeys.wait_if_paused()
                if self.hotkeys.stopped.is_set():
                    break
                ok = self.cycle()
                self._failures = 0 if ok else self._failures + 1
                if self._failures >= self.cfg.max_consecutive_failures:
                    log.error(
                        "%d cycles in a row without a bite - stopping (rod broken, "
                        "inventory full, or regions miscalibrated?)",
                        self._failures,
                    )
                    break
                log.info("Stats: %s", self.stats.summary())
                self.keyboard.sleep(self.cfg.loop_delay_s)
        except KeyboardInterrupt:
            log.info("Interrupted")
        finally:
            self.hotkeys.stop()
            log.info("Final stats: %s", self.stats.summary())

    def cycle(self) -> bool:
        """One full cast. Returns False when nothing bit before the timeout."""
        self.cast()
        if not self.wait_for_bite():
            self.stats.bite_timeouts += 1
            log.info("No bite within %.0f s, recasting", self.cfg.bite_timeout_s)
            return False
        self.hook()
        self.play_gauge()
        self.play_wasd()
        self.finish_catch()
        return True

    # ---------------------------------------------------------------- stages
    def cast(self) -> None:
        self.stats.casts += 1
        log.info("Cast #%d", self.stats.casts)
        self.keyboard.press(self.cfg.cast_key)
        self.keyboard.sleep(self.cfg.cast_settle_s)
        baseline = self.screen.grab(self.cfg.bite_region) if self.bite.mode == "change" else None
        self.bite.reset(baseline)

    def wait_for_bite(self) -> bool:
        deadline = time.time() + self.cfg.bite_timeout_s
        next_log = time.time() + 15
        while time.time() < deadline:
            if self.hotkeys.stopped.is_set():
                return False
            self.hotkeys.wait_if_paused()
            frame = self.screen.grab(self.cfg.bite_region)
            if self.bite.update(frame):
                self.stats.bites += 1
                log.info("Bite detected (score=%.2f)", self.bite.last_score)
                self._debug_save("bite", frame)
                return True
            if time.time() >= next_log:
                log.debug("Waiting for bite... last score %.2f", self.bite.last_score)
                next_log = time.time() + 15
            time.sleep(self.cfg.bite_poll_s)
        return False

    def hook(self) -> None:
        self.keyboard.press(self.cfg.hook_key)
        log.info("Hooked, waiting for minigame")

    def play_gauge(self) -> bool:
        reading = None
        deadline = time.time() + self.cfg.hook_to_gauge_timeout_s
        while time.time() < deadline:
            frame = self.screen.grab(self.cfg.gauge_region)
            reading = analyze_gauge(frame, self.cfg)
            if reading is not None:
                break
            time.sleep(0.01)
        if reading is None:
            log.info("Gauge not detected (skipped at your skill level, or region needs calibration)")
            return False

        self.stats.gauges_played += 1
        self.gauge.reset()
        self._debug_save("gauge", frame)
        deadline = time.time() + self.cfg.gauge_timeout_s
        while time.time() < deadline:
            frame = self.screen.grab(self.cfg.gauge_region)
            reading = analyze_gauge(frame, self.cfg)
            if reading is None:
                log.info("Gauge disappeared before we pressed")
                return True
            if self.gauge.should_press(reading):
                self.keyboard.press(self.cfg.gauge_key)
                log.info(
                    "Gauge: pressed at x=%.0f (zone %d-%d, v=%.1f px/frame)",
                    reading.marker_x or -1,
                    reading.zone_left,
                    reading.zone_right,
                    self.gauge.velocity,
                )
                return True
            time.sleep(self.cfg.gauge_poll_s)
        log.warning("Gauge timeout - pressing anyway")
        self.keyboard.press(self.cfg.gauge_key)
        return True

    def play_wasd(self) -> bool:
        if not self.wasd.available:
            log.warning("Skipping WASD minigame: no key templates captured yet")
            self.stats.wasd_missed += 1
            return False
        deadline = time.time() + self.cfg.gauge_to_wasd_timeout_s
        last_count, stable, reading, frame = 0, 0, None, None
        while time.time() < deadline:
            frame = self.screen.grab(self.cfg.wasd_region)
            reading = self.wasd.read(frame)
            count = len(reading.keys)
            stable = stable + 1 if count and count == last_count else 0
            last_count = count
            if count and stable >= self.cfg.wasd_stable_frames - 1:
                break
            time.sleep(0.02)
        else:
            log.info("WASD prompt not detected")
            self.stats.wasd_missed += 1
            return False

        assert reading is not None
        detail = " ".join(f"{m.name}@{m.x}" for m in reading.matches)
        log.info("WASD sequence: %s  (%s)", "".join(reading.keys).upper(), detail)
        self._debug_save("wasd", frame)
        self.keyboard.press_sequence(reading.keys, self.cfg.wasd_key_delay_s)
        self.stats.wasd_solved += 1
        return True

    def finish_catch(self) -> None:
        self.stats.catches += 1
        self.keyboard.sleep(self.cfg.post_catch_delay_s)
        if self.cfg.press_loot_key_after_catch:
            self.keyboard.press(self.cfg.loot_key)
            self.keyboard.sleep(0.6)

    # --------------------------------------------------------------- helpers
    def _debug_save(self, stage: str, frame: Optional[np.ndarray]) -> None:
        if not self.cfg.debug_dir or frame is None:
            return
        name = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{stage}.png"
        cv2.imwrite(str(Path(self.cfg.debug_dir) / name), frame)
