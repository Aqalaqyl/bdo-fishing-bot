"""Calibration helpers: ``python -m bdo_fishing_bot.tools.calibrate --help``.

Sub-commands
------------
preview     Screenshot the whole screen with the configured regions drawn on it.
burst       Save frames of a region for N seconds while you fish manually, so
            you can grab screenshots of the bite prompt / gauge / WASD row.
split-keys  Cut the individual key icons out of a WASD screenshot to use as
            templates (rename the output files to w.png, a_rev.png, ...).
analyze     Run a detector offline against a saved screenshot.
hsv         Print the HSV value of a pixel in an image (for tuning colour ranges).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

from .. import vision
from ..config import Config, Region
from ..detectors import BiteDetector, GaugeTracker, WasdReader, analyze_gauge

log = logging.getLogger("calibrate")

COLORS = {"bite": (0, 255, 255), "gauge": (255, 128, 0), "wasd": (0, 0, 255)}


def _region(cfg: Config, name: str) -> Region:
    if name == "full":
        return Region(0, 0, cfg.screen_width, cfg.screen_height)
    return cfg.regions()[name]


def cmd_preview(cfg: Config, args) -> int:
    from ..screen import Screen

    time.sleep(args.delay)
    frame = Screen().grab_full(cfg.screen_width, cfg.screen_height)
    for name, region in cfg.regions().items():
        color = COLORS[name]
        cv2.rectangle(frame, (region.left, region.top), (region.right, region.bottom), color, 2)
        cv2.putText(
            frame, name, (region.left + 4, region.top + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
        )
    cv2.imwrite(args.out, frame)
    print(f"Saved {args.out}")
    return 0


def cmd_burst(cfg: Config, args) -> int:
    from ..screen import Screen

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    region = _region(cfg, args.region)
    screen = Screen()
    print(f"Capturing '{args.region}' {region.as_mss()} for {args.seconds}s at {args.fps} fps -> {out}/")
    print("Go fish manually; trigger the bite / gauge / WASD prompt while this runs.")
    time.sleep(args.delay)
    interval = 1.0 / args.fps
    end = time.time() + args.seconds
    count = 0
    while time.time() < end:
        t0 = time.time()
        frame = screen.grab(region)
        name = out / f"{args.region}_{datetime.now():%H%M%S_%f}.png"
        cv2.imwrite(str(name), frame)
        count += 1
        time.sleep(max(0.0, interval - (time.time() - t0)))
    print(f"Saved {count} frames")
    return 0


def find_key_boxes(image: np.ndarray, min_size: int = 18, max_size: int = 140) -> List[Tuple[int, int, int, int]]:
    """Find roughly square icon boxes in a WASD screenshot (x, y, w, h), left to right."""
    gray = vision.to_gray(image)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    boxes: List[Tuple[int, int, int, int]] = []
    for mode in (thresh, cv2.bitwise_not(thresh)):
        contours, _ = cv2.findContours(mode, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if min_size <= w <= max_size and min_size <= h <= max_size and 0.6 <= w / h <= 1.6:
                found.append((x, y, w, h))
        if len(found) > len(boxes):
            boxes = found
    # Merge boxes that overlap heavily (outer frame + inner glyph of the same key).
    merged: List[Tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda b: b[2] * b[3], reverse=True):
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        if any(mx <= cx <= mx + mw and my <= cy <= my + mh for mx, my, mw, mh in merged):
            continue
        merged.append(box)
    return sorted(merged, key=lambda b: b[0])


def cmd_split_keys(cfg: Config, args) -> int:
    image = cv2.imread(args.image)
    if image is None:
        print(f"Cannot read {args.image}")
        return 1
    boxes = find_key_boxes(image)
    if not boxes:
        print("No key boxes found; crop the icons manually (any image editor) and save them as templates/<name>.png")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pad = args.pad
    for i, (x, y, w, h) in enumerate(boxes):
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(image.shape[1], x + w + pad), min(image.shape[0], y + h + pad)
        crop = image[y0:y1, x0:x1]
        path = out / f"key_{i}.png"
        cv2.imwrite(str(path), crop)
        print(f"{path}  box=({x},{y},{w},{h})")
    print(
        f"\nSaved {len(boxes)} crops to {out}/. Look at each one and rename it to one of: "
        f"{', '.join(n + '.png' for n in vision.WASD_TEMPLATE_NAMES)} inside '{cfg.templates_dir}/'."
    )
    return 0


def cmd_analyze(cfg: Config, args) -> int:
    image = cv2.imread(args.image)
    if image is None:
        print(f"Cannot read {args.image}")
        return 1
    templates = vision.load_templates(
        cfg.templates_dir, vision.WASD_TEMPLATE_NAMES + (vision.BITE_TEMPLATE_NAME,)
    )
    annotated = image.copy()
    if args.kind == "bite":
        detector = BiteDetector(cfg, templates)
        positive = detector.frame_is_positive(image)
        print(f"mode={detector.mode} score={detector.last_score:.2f} positive={positive}")
    elif args.kind == "gauge":
        reading = analyze_gauge(image, cfg)
        if reading is None:
            print("No gauge found (tune gauge_zone_hsv_* or the gauge_region)")
        else:
            tracker = GaugeTracker(cfg)
            print(
                f"zone={reading.zone_left}-{reading.zone_right} marker={reading.marker_x} "
                f"press_now={tracker.should_press(reading)}"
            )
            h = image.shape[0]
            cv2.line(annotated, (reading.zone_left, 0), (reading.zone_left, h), (255, 128, 0), 1)
            cv2.line(annotated, (reading.zone_right, 0), (reading.zone_right, h), (255, 128, 0), 1)
            if reading.marker_x is not None:
                mx = int(reading.marker_x)
                cv2.line(annotated, (mx, 0), (mx, h), (0, 0, 255), 1)
    elif args.kind == "wasd":
        reader = WasdReader(cfg, templates)
        if not reader.available:
            print("No WASD templates loaded")
            return 1
        reading = reader.read(image)
        print("keys:", "".join(reading.keys).upper() or "(none)")
        for m in reading.matches:
            print(f"  {m.name:6s} x={m.x:4d} y={m.y:4d} score={m.score:.2f} -> press {reader.key_for(m.name)}")
            cv2.rectangle(annotated, (m.x, m.y), (m.x + m.width, m.y + m.height), (0, 0, 255), 1)
            cv2.putText(annotated, m.name, (m.x, m.y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    if args.out:
        cv2.imwrite(args.out, annotated)
        print(f"Annotated image saved to {args.out}")
    return 0


def cmd_hsv(cfg: Config, args) -> int:
    image = cv2.imread(args.image)
    if image is None:
        print(f"Cannot read {args.image}")
        return 1
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    b, g, r = image[args.y, args.x]
    h, s, v = hsv[args.y, args.x]
    print(f"pixel ({args.x},{args.y}): BGR=({b},{g},{r}) HSV=({h},{s},{v})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bdo_fishing_bot.tools.calibrate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--config")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preview", help="screenshot with regions drawn")
    p.add_argument("--out", default="preview.png")
    p.add_argument("--delay", type=float, default=3.0, help="seconds to switch to the game first")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("burst", help="save frames of a region for a while")
    p.add_argument("--region", choices=["bite", "gauge", "wasd", "full"], default="full")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--fps", type=float, default=4)
    p.add_argument("--delay", type=float, default=3.0)
    p.add_argument("--out", default="captures")
    p.set_defaults(func=cmd_burst)

    p = sub.add_parser("split-keys", help="cut key icons out of a WASD screenshot")
    p.add_argument("image")
    p.add_argument("--out", default="captures/keys")
    p.add_argument("--pad", type=int, default=0)
    p.set_defaults(func=cmd_split_keys)

    p = sub.add_parser("analyze", help="run a detector on a saved image")
    p.add_argument("kind", choices=["bite", "gauge", "wasd"])
    p.add_argument("image")
    p.add_argument("--out", help="write an annotated copy here")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("hsv", help="print HSV of a pixel")
    p.add_argument("image")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=cmd_hsv)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    cfg = Config.load(args.config)
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
