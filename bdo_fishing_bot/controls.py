"""Keyboard output.

Black Desert reads keyboard state through DirectInput and ignores the plain
``SendInput`` unicode events that ``pyautogui`` emits, so ``pydirectinput``
(which sends hardware scan codes) is used whenever it is available.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

log = logging.getLogger(__name__)


def _load_backend():
    try:
        import pydirectinput  # type: ignore

        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        return "pydirectinput", pydirectinput
    except Exception:  # pragma: no cover - platform dependent
        pass
    try:
        import pyautogui  # type: ignore

        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = False
        log.warning("pydirectinput not available; falling back to pyautogui (BDO may ignore it)")
        return "pyautogui", pyautogui
    except Exception:  # pragma: no cover - platform dependent
        return "none", None


class Keyboard:
    def __init__(self, hold_s: float = 0.05, jitter_s: float = 0.0, dry_run: bool = False) -> None:
        self.hold_s = hold_s
        self.jitter_s = jitter_s
        self.dry_run = dry_run
        self.backend_name, self._backend = ("dry-run", None) if dry_run else _load_backend()
        if self._backend is None and not dry_run:
            raise RuntimeError(
                "No keyboard backend found. Install pydirectinput (Windows) or pyautogui."
            )
        log.info("Keyboard backend: %s", self.backend_name)

    def press(self, key: str, hold_s: Optional[float] = None) -> None:
        hold = self.hold_s if hold_s is None else hold_s
        hold += random.uniform(0, self.jitter_s * 0.25)
        if self.dry_run:
            log.info("[dry-run] press %s (%.0f ms)", key, hold * 1000)
            time.sleep(hold)
            return
        self._backend.keyDown(key)
        time.sleep(hold)
        self._backend.keyUp(key)

    def press_sequence(self, keys, delay_s: float) -> None:
        for i, key in enumerate(keys):
            self.press(key)
            if i < len(keys) - 1:
                time.sleep(delay_s + random.uniform(0, self.jitter_s * 0.3))

    def sleep(self, seconds: float, jitter: bool = True) -> None:
        if jitter and self.jitter_s:
            seconds += random.uniform(0, self.jitter_s)
        time.sleep(max(0.0, seconds))
