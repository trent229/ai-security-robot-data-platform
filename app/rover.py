"""Thread-safe serial interface for the ELEGOO Smart Robot Car V4.0."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import serial


class RoverError(RuntimeError):
    """Raised when the rover cannot complete a command."""


class RoverSerial:
    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 9600,
        startup_delay: float = 7.0,
        response_timeout: float = 3.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.startup_delay = startup_delay
        self.response_timeout = response_timeout
        self._serial: serial.Serial | None = None
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def connect(self) -> None:
        with self._lock:
            if self.connected:
                return

            try:
                self._serial = serial.Serial(
                    self.port,
                    self.baudrate,
                    timeout=0.20,
                    write_timeout=1.0,
                )
                # Opening the USB serial port resets the Uno. Allow its MPU6050
                # initialization and calibration to finish before sending data.
                time.sleep(self.startup_delay)
                self._serial.reset_input_buffer()
            except (OSError, serial.SerialException) as exc:
                self.close()
                raise RoverError(f"Unable to open rover serial port {self.port}: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                finally:
                    self._serial = None

    def _request(
        self,
        payload: dict[str, Any],
        *,
        tag: str,
        accept_ok: bool = False,
    ) -> str:
        with self._lock:
            self.connect()
            assert self._serial is not None

            command = dict(payload)
            command["H"] = tag
            encoded = json.dumps(command, separators=(",", ":")).encode("ascii")

            self._serial.reset_input_buffer()
            self._serial.write(encoded)
            self._serial.flush()

            deadline = time.monotonic() + self.response_timeout
            received = bytearray()
            tagged = re.compile(rb"\{" + re.escape(tag.encode("ascii")) + rb"_([^}]*)\}")

            while time.monotonic() < deadline:
                waiting = self._serial.in_waiting
                received.extend(self._serial.read(waiting or 1))

                match = tagged.search(received)
                if match:
                    return match.group(1).decode("ascii", errors="replace")
                if accept_ok and b"{ok}" in received:
                    return "ok"

            raw = received.decode("ascii", errors="replace") or "no response"
            raise RoverError(f"Rover command timed out ({raw})")

    def distance_cm(self) -> int:
        value = self._request({"N": 21, "D1": 2}, tag="JETSON")
        try:
            return int(value)
        except ValueError as exc:
            raise RoverError(f"Invalid ultrasonic response: {value!r}") from exc

    def stop(self) -> None:
        self._request({"N": 100}, tag="JETSONSTOP", accept_ok=True)

    def start_autonomous(self) -> None:
        self._request({"N": 101, "D1": 2}, tag="JETSONAUTO", accept_ok=True)
