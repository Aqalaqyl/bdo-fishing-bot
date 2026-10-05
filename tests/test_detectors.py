import cv2
import numpy as np
import pytest

from bdo_fishing_bot.config import Config, Region
from bdo_fishing_bot.detectors import BiteDetector, GaugeTracker, WasdReader, analyze_gauge
from bdo_fishing_bot import vision


# ----------------------------------------------------------------- helpers
def make_gauge(width=600, height=60, zone=(300, 380), marker_x=None):
    """Dark bar with a blue success zone and an optional white marker."""
    frame = np.full((height, width, 3), (40, 40, 40), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (width - 20, 40), (70, 70, 70), -1)
    cv2.rectangle(frame, (zone[0], 20), (zone[1], 40), (230, 140, 30), -1)  # BGR blue-ish
    if marker_x is not None:
        cv2.rectangle(frame, (marker_x - 2, 15), (marker_x + 2, 45), (255, 255, 255), -1)
    return frame


def glyph(letter: str, size=40, flip=False):
    """Render a key-cap style icon for ``letter``."""
    img = np.full((size, size, 3), (30, 30, 30), dtype=np.uint8)
    cv2.rectangle(img, (1, 1), (size - 2, size - 2), (120, 120, 120), 1)
    cv2.putText(img, letter, (8, size - 10), cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 255, 255), 2)
    if flip:
        img = cv2.flip(img, 0)  # upside down, like the reversed keys in game
    return img


def make_wasd_row(sequence, size=40, gap=12, pad=30):
    """Compose a row of glyphs. ``sequence`` holds (letter, flipped) tuples."""
    width = pad * 2 + len(sequence) * (size + gap)
    frame = np.full((size + pad * 2, width, 3), (15, 15, 15), dtype=np.uint8)
    noise = np.random.default_rng(0).integers(0, 10, frame.shape, dtype=np.uint8)
    frame = cv2.add(frame, noise)
    for i, (letter, flipped) in enumerate(sequence):
        x = pad + i * (size + gap)
        frame[pad : pad + size, x : x + size] = glyph(letter, size, flipped)
    return frame


@pytest.fixture
def wasd_templates():
    templates = {}
    for letter in "wasd":
        templates[letter] = vision.to_gray(glyph(letter.upper()))
        templates[f"{letter}_rev"] = vision.to_gray(glyph(letter.upper(), flip=True))
    return templates


# ------------------------------------------------------------------ config
def test_config_overrides_and_roundtrip(tmp_path):
    cfg = Config()
    cfg.apply({"bite_region": [1, 2, 3, 4], "gauge_zone_hsv_lower": [1, 2, 3], "bite_timeout_s": 9})
    assert cfg.bite_region == Region(1, 2, 3, 4)
    assert cfg.gauge_zone_hsv_lower == (1, 2, 3)
    assert cfg.bite_timeout_s == 9
    path = tmp_path / "c.json"
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded.bite_region == Region(1, 2, 3, 4)
    with pytest.raises(KeyError):
        cfg.apply({"nope": 1})


def test_default_regions_fit_1080p():
    cfg = Config()
    for region in cfg.regions().values():
        assert 0 <= region.left and region.right <= 1920
        assert 0 <= region.top and region.bottom <= 1080


# ------------------------------------------------------------------- gauge
def test_gauge_detects_zone_and_marker():
    cfg = Config()
    reading = analyze_gauge(make_gauge(marker_x=340), cfg)
    assert reading is not None
    assert abs(reading.zone_left - 300) <= 2
    assert abs(reading.zone_right - 380) <= 2
    assert abs(reading.marker_x - 340) <= 2


def test_gauge_absent_on_blank_frame():
    cfg = Config()
    blank = np.full((60, 600, 3), (40, 40, 40), dtype=np.uint8)
    assert analyze_gauge(blank, cfg) is None


def test_gauge_tracker_presses_inside_zone_only():
    cfg = Config()
    tracker = GaugeTracker(cfg)
    pressed_at = None
    # Marker sweeps left to right at 10 px/frame.
    for x in range(100, 500, 10):
        reading = analyze_gauge(make_gauge(marker_x=x), cfg)
        if tracker.should_press(reading):
            pressed_at = x
            break
    assert pressed_at is not None
    # With lead compensation the press should land at or just before the zone.
    predicted = pressed_at + tracker.velocity * cfg.gauge_lead_frames
    assert 300 <= predicted <= 380
    assert pressed_at >= 280


def test_gauge_tracker_does_not_press_when_leaving_zone():
    cfg = Config()
    cfg.gauge_lead_frames = 3
    tracker = GaugeTracker(cfg)
    # Marker is at the right edge of the zone, moving right fast: predicted
    # position is outside, so do not press.
    tracker.should_press(analyze_gauge(make_gauge(marker_x=350), cfg))
    tracker.should_press(analyze_gauge(make_gauge(marker_x=365), cfg))
    assert tracker.should_press(analyze_gauge(make_gauge(marker_x=378), cfg)) is False


# -------------------------------------------------------------------- wasd
def test_wasd_reads_sequence_and_maps_reversed_keys(wasd_templates):
    cfg = Config()
    reader = WasdReader(cfg, wasd_templates)
    sequence = [("W", False), ("A", True), ("S", False), ("D", True), ("W", True), ("D", False)]
    reading = reader.read(make_wasd_row(sequence))
    assert [m.name for m in reading.matches] == ["w", "a_rev", "s", "d_rev", "w_rev", "d"]
    assert reading.keys == ["w", "d", "s", "a", "s", "d"]


def test_wasd_empty_frame_gives_no_keys(wasd_templates):
    cfg = Config()
    reader = WasdReader(cfg, wasd_templates)
    frame = np.full((100, 600, 3), (15, 15, 15), dtype=np.uint8)
    assert reader.read(frame).keys == []


def test_wasd_reader_without_templates_is_unavailable():
    reader = WasdReader(Config(), {})
    assert reader.available is False


def test_nms_keeps_strongest_overlapping_match():
    a = vision.Match("w", 10, 10, 40, 40, 0.9)
    b = vision.Match("w_rev", 12, 11, 40, 40, 0.95)
    c = vision.Match("a", 100, 10, 40, 40, 0.85)
    kept = vision.non_max_suppression([a, b, c])
    assert sorted(m.name for m in kept) == ["a", "w_rev"]


# -------------------------------------------------------------------- bite
def test_bite_bright_mode_requires_consecutive_frames():
    cfg = Config()
    cfg.bite_detection = "bright"
    cfg.bite_confirm_frames = 2
    detector = BiteDetector(cfg, {})
    dark = np.full((100, 100, 3), (30, 60, 90), dtype=np.uint8)
    bright = dark.copy()
    bright[20:60, 20:60] = 255  # 1600 bright pixels
    assert detector.update(dark) is False
    assert detector.update(bright) is False
    assert detector.update(bright) is True
    assert detector.update(dark) is False


def test_bite_template_mode():
    cfg = Config()
    cfg.bite_detection = "template"
    cfg.bite_confirm_frames = 1
    prompt = glyph("!", size=48)
    detector = BiteDetector(cfg, {"bite": vision.to_gray(prompt)})
    assert detector.mode == "template"
    scene = np.full((200, 300, 3), (50, 90, 120), dtype=np.uint8)
    assert detector.update(scene) is False
    scene[80:128, 120:168] = prompt
    assert detector.update(scene) is True


def test_bite_change_mode_uses_baseline():
    cfg = Config()
    cfg.bite_detection = "change"
    cfg.bite_confirm_frames = 1
    detector = BiteDetector(cfg, {})
    base = np.full((50, 50, 3), 100, dtype=np.uint8)
    detector.reset(base)
    assert detector.update(base.copy()) is False
    changed = base.copy()
    changed[:, :25] = 200
    assert detector.update(changed) is True


def test_auto_mode_falls_back_to_bright_without_template():
    cfg = Config()
    assert BiteDetector(cfg, {}).mode == "bright"
    with pytest.raises(ValueError):
        cfg.bite_detection = "template"
        BiteDetector(cfg, {})
