"""Global pause/stop hotkeys so the bot can be controlled while BDO has focus."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class HotkeyController:
    def __init__(self, pause_key: str, stop_key: str) -> None:
        self.pause_key = pause_key.lower()
        self.stop_key = stop_key.lower()
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self._listener = None

    def start(self) -> None:
        try:
            from pynput import keyboard  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            log.warning("pynput not installed; hotkeys disabled (use Ctrl+C in the console)")
            return

        def key_name(key) -> str:
            if hasattr(key, "char") and key.char:
                return key.char.lower()
            return str(getattr(key, "name", key)).lower()

        def on_press(key) -> None:
            name = key_name(key)
            if name == self.stop_key:
                log.info("Stop hotkey pressed")
                self.stopped.set()
                self.paused.clear()
            elif name == self.pause_key:
                if self.paused.is_set():
                    self.paused.clear()
                    log.info("Resumed")
                else:
                    self.paused.set()
                    log.info("Paused (press %s again to resume)", self.pause_key.upper())

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.daemon = True
        self._listener.start()
        log.info("Hotkeys: %s = pause/resume, %s = stop", self.pause_key.upper(), self.stop_key.upper())

    def stop(self) -> None:
        self.stopped.set()
        if self._listener is not None:
            self._listener.stop()

    def wait_if_paused(self) -> None:
        while self.paused.is_set() and not self.stopped.is_set():
            self.paused.wait(0.2)
