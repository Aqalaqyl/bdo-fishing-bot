"""Command line interface: ``python -m bdo_fishing_bot --help``."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bdo_fishing_bot",
        description="Black Desert fishing bot (1920x1080, UI scale 100).",
    )
    parser.add_argument("-c", "--config", help="JSON config overrides (default: ./config.json if present)")
    parser.add_argument("--dry-run", action="store_true", help="detect everything but never press keys")
    parser.add_argument("--debug-dir", help="save a screenshot of every detection stage here")
    parser.add_argument("--bite-mode", choices=["auto", "template", "bright", "change"])
    parser.add_argument("--max-casts", type=int)
    parser.add_argument(
        "--cast-hold",
        type=float,
        metavar="SECONDS",
        help="hold the cast key this long to spend energy on the cast (default: tap)",
    )
    parser.add_argument("--start-delay", type=float, default=3.0, help="seconds before the first cast")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--print-config", action="store_true", help="dump the effective config and exit")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = Config.load(args.config)
    if args.dry_run:
        cfg.dry_run = True
    if args.debug_dir:
        cfg.debug_dir = args.debug_dir
    if args.bite_mode:
        cfg.bite_detection = args.bite_mode
    if args.max_casts is not None:
        cfg.max_casts = args.max_casts
    if args.cast_hold is not None:
        cfg.cast_hold_s = args.cast_hold
    if args.print_config:
        import json

        print(json.dumps(cfg.to_dict(), indent=2))
        return 0

    from .bot import FishingBot

    FishingBot(cfg).run(start_delay_s=args.start_delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
