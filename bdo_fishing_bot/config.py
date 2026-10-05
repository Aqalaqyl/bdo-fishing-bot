"""Bot configuration.

All defaults target a 1920x1080 client at 100% UI scale. Every value can be
overridden through a JSON file (see ``config.example.json``) so the bot can be
re-calibrated without touching code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

HSV = Tuple[int, int, int]


@dataclass
class Region:
    """A rectangular screen area in absolute pixel coordinates."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_mss(self) -> Dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def to_absolute(self, x: int, y: int) -> Tuple[int, int]:
        """Translate a point inside this region to screen coordinates."""
        return self.left + x, self.top + y


@dataclass
class Config:
    # --- Display -----------------------------------------------------------
    screen_width: int = 1920
    screen_height: int = 1080
    ui_scale: int = 100

    # --- Screen regions (1920x1080 @ 100%) ----------------------------------
    # Where the "press Space" bite prompt / exclamation shows up.
    bite_region: Region = field(default_factory=lambda: Region(710, 430, 500, 300))
    # Where the horizontal gauge (blue zone + moving marker) is drawn.
    gauge_region: Region = field(default_factory=lambda: Region(560, 590, 800, 170))
    # Where the row of W/A/S/D key icons is drawn.
    wasd_region: Region = field(default_factory=lambda: Region(560, 220, 800, 150))

    # --- Keys ---------------------------------------------------------------
    cast_key: str = "space"
    hook_key: str = "space"
    gauge_key: str = "space"
    loot_key: str = "r"
    press_loot_key_after_catch: bool = False

    # --- Timings (seconds) ---------------------------------------------------
    cast_settle_s: float = 3.0  # ignore the bite region right after casting
    bite_timeout_s: float = 150.0  # recast if nothing bites in this long
    bite_poll_s: float = 0.05
    bite_confirm_frames: int = 2  # consecutive positive frames required
    hook_to_gauge_timeout_s: float = 4.0
    gauge_poll_s: float = 0.004
    gauge_timeout_s: float = 8.0  # press anyway if we never find a good moment
    gauge_to_wasd_timeout_s: float = 4.0
    wasd_stable_frames: int = 2  # frames the key count must stay constant
    wasd_key_delay_s: float = 0.09
    wasd_timeout_s: float = 5.0
    post_catch_delay_s: float = 4.5
    key_hold_s: float = 0.05
    jitter_s: float = 0.12  # random extra delay added to most waits
    loop_delay_s: float = 1.0

    # --- Detection -----------------------------------------------------------
    templates_dir: str = "templates"
    template_threshold: float = 0.80
    # "auto" uses the bite template if present, otherwise "bright".
    bite_detection: str = "auto"  # auto | template | bright | change
    bite_bright_value: int = 225  # min channel value for a pixel to count as bright
    bite_bright_min_pixels: int = 350
    bite_change_threshold: float = 14.0  # mean abs diff vs baseline frame

    gauge_zone_hsv_lower: HSV = (92, 110, 110)
    gauge_zone_hsv_upper: HSV = (128, 255, 255)
    gauge_marker_hsv_lower: HSV = (0, 0, 205)
    gauge_marker_hsv_upper: HSV = (180, 70, 255)
    gauge_min_zone_width: int = 20
    gauge_min_column_pixels: int = 6  # mask pixels per column to count as zone/marker
    gauge_zone_margin_px: int = 4  # stay this far inside the zone edges
    gauge_lead_frames: float = 1.5  # predict marker position this many frames ahead

    wasd_reversed_map: Dict[str, str] = field(
        default_factory=lambda: {"w_rev": "s", "s_rev": "w", "a_rev": "d", "d_rev": "a"}
    )

    # --- Hotkeys / safety ----------------------------------------------------
    pause_hotkey: str = "f9"
    stop_hotkey: str = "f10"
    max_consecutive_failures: int = 6
    max_casts: int = 0  # 0 = unlimited
    debug_dir: Optional[str] = None
    dry_run: bool = False

    # ------------------------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "Config":
        cfg = cls()
        if path is None:
            default = Path("config.json")
            path = default if default.exists() else None
        if path is None:
            return cfg
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg.apply(data)
        return cfg

    def apply(self, data: Dict[str, Any]) -> None:
        known = {f.name: f for f in fields(self)}
        for key, value in data.items():
            if key not in known:
                raise KeyError(f"Unknown config key: {key!r}")
            current = getattr(self, key)
            if isinstance(current, Region):
                if isinstance(value, dict):
                    value = Region(**value)
                else:
                    value = Region(*value)
            elif isinstance(current, tuple) and isinstance(value, list):
                value = tuple(value)
            setattr(self, key, value)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = asdict(value) if is_dataclass(value) else value
        return out

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def regions(self) -> Dict[str, Region]:
        return {
            "bite": self.bite_region,
            "gauge": self.gauge_region,
            "wasd": self.wasd_region,
        }
