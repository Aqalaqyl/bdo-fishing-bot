"""Keyboard output.

Backends, chosen with ``input_backend`` in the config (``auto`` picks the
first that works in this order):

* ``pydirectinput`` (Windows) - DirectInput scan codes, which BDO reads.
* ``uinput`` (Linux) - a virtual keyboard created through ``/dev/uinput``
  with ``evdev``; Wine/Proton sees it as real hardware, so it works even when
  the game ignores XTEST events. Needs write access to ``/dev/uinput`` (see
  ``install.sh --uinput``).
* ``pyautogui`` - XTEST on X11 / SendInput unicode on Windows. Last resort;
  BDO on Windows ignores it, under Proton it usually works.
"""

from __future__ import annotations

import logging
import os
import random
import sys
import time
from typing import Iterable, Optional

log = logging.getLogger(__name__)


class _PyDirectInputBackend:
    name = "pydirectinput"

    def __init__(self) -> None:
        import pydirectinput  # type: ignore

        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        self._lib = pydirectinput

    def key_down(self, key: str) -> None:
        self._lib.keyDown(key)

    def key_up(self, key: str) -> None:
        self._lib.keyUp(key)

    def close(self) -> None:
        pass


class _PyAutoGuiBackend:
    name = "pyautogui"

    def __init__(self) -> None:
        import pyautogui  # type: ignore

        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = False
        self._lib = pyautogui

    def key_down(self, key: str) -> None:
        self._lib.keyDown(key)

    def key_up(self, key: str) -> None:
        self._lib.keyUp(key)

    def close(self) -> None:
        pass


class _UinputBackend:
    name = "uinput"

    def __init__(self) -> None:
        from evdev import UInput, ecodes  # type: ignore

        if not os.access("/dev/uinput", os.W_OK):
            raise PermissionError(
                "/dev/uinput is not writable; run ./install.sh --uinput (or add a udev rule) "
                "and log in again"
            )
        self._ecodes = ecodes
        # With no explicit capabilities UInput registers every KEY_*/BTN_* code.
        self._ui = UInput(name="bdo-fishing-bot")
        # Give the compositor / Wine a moment to pick up the new device.
        time.sleep(0.5)

    def _code(self, key: str) -> int:
        aliases = {"space": "SPACE", "enter": "ENTER", "esc": "ESC", "escape": "ESC",
                   "shift": "LEFTSHIFT", "ctrl": "LEFTCTRL", "alt": "LEFTALT", "tab": "TAB"}
        name = aliases.get(key.lower(), key.upper())
        code = getattr(self._ecodes, f"KEY_{name}", None)
        if code is None:
            raise ValueError(f"Unknown key for uinput backend: {key!r}")
        return code

    def key_down(self, key: str) -> None:
        self._ui.write(self._ecodes.EV_KEY, self._code(key), 1)
        self._ui.syn()

    def key_up(self, key: str) -> None:
        self._ui.write(self._ecodes.EV_KEY, self._code(key), 0)
        self._ui.syn()

    def close(self) -> None:
        self._ui.close()


class _DryRunBackend:
    name = "dry-run"

    def key_down(self, key: str) -> None:
        pass

    def key_up(self, key: str) -> None:
        pass

    def close(self) -> None:
        pass


_BACKENDS = {
    "pydirectinput": _PyDirectInputBackend,
    "uinput": _UinputBackend,
    "pyautogui": _PyAutoGuiBackend,
}


def _auto_order() -> Iterable[str]:
    if sys.platform == "win32":
        return ("pydirectinput", "pyautogui")
    if sys.platform.startswith("linux"):
        return ("uinput", "pyautogui")
    return ("pyautogui",)


def load_backend(preference: str = "auto"):
    names = _auto_order() if preference == "auto" else (preference,)
    errors = []
    for name in names:
        if name not in _BACKENDS:
            raise ValueError(f"Unknown input_backend {name!r}; choose auto, {', '.join(_BACKENDS)}")
        try:
            return _BACKENDS[name]()
        except Exception as exc:  # pragma: no cover - platform dependent
            errors.append(f"{name}: {exc}")
            log.debug("Input backend %s unavailable: %s", name, exc)
    raise RuntimeError(
        "No keyboard backend could be initialised:\n  " + "\n  ".join(errors)
        + "\nInstall pydirectinput (Windows), evdev + uinput access (Linux) or pyautogui."
    )


class Keyboard:
    def __init__(
        self,
        hold_s: float = 0.05,
        jitter_s: float = 0.0,
        dry_run: bool = False,
        backend: str = "auto",
    ) -> None:
        self.hold_s = hold_s
        self.jitter_s = jitter_s
        self.dry_run = dry_run
        self._backend = _DryRunBackend() if dry_run else load_backend(backend)
        self.backend_name = self._backend.name
        if self.backend_name == "pyautogui" and sys.platform == "win32":
            log.warning("pyautogui backend selected; BDO on Windows usually ignores it - install pydirectinput")
        log.info("Keyboard backend: %s", self.backend_name)

    def press(self, key: str, hold_s: Optional[float] = None) -> None:
        hold = self.hold_s if hold_s is None else hold_s
        hold += random.uniform(0, self.jitter_s * 0.25)
        if self.dry_run:
            log.info("[dry-run] press %s (%.0f ms)", key, hold * 1000)
            time.sleep(hold)
            return
        self._backend.key_down(key)
        try:
            time.sleep(hold)
        finally:
            self._backend.key_up(key)

    def press_sequence(self, keys, delay_s: float) -> None:
        for i, key in enumerate(keys):
            self.press(key)
            if i < len(keys) - 1:
                time.sleep(delay_s + random.uniform(0, self.jitter_s * 0.3))

    def sleep(self, seconds: float, jitter: bool = True) -> None:
        if jitter and self.jitter_s:
            seconds += random.uniform(0, self.jitter_s)
        time.sleep(max(0.0, seconds))

    def close(self) -> None:
        self._backend.close()
