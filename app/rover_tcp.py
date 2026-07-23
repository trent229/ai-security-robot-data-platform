"""Persistent TCP transport through the ELEGOO ESP32-to-Uno bridge."""

from __future__ import annotations

from collections import deque
import json
import re
import socket
import threading
import time
from typing import Any

from app.rover import RoverError


class RoverTCP:
    def __init__(
        self,
        host: str,
        port: int = 100,
        connect_timeout: float = 3.0,
        response_timeout: float = 3.0,
    ) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout

        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._response_condition = threading.Condition()
        self._responses: deque[bytes] = deque()
        self._last_error: str | None = None

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return self._socket is not None and not self._stop.is_set()

    def connect(self) -> None:
        with self._state_lock:
            if self.connected:
                return

            self._stop.clear()
            self._last_error = None
            try:
                sock = socket.create_connection(
                    (self.host, self.port), timeout=self.connect_timeout
                )
                sock.settimeout(0.5)
            except OSError as exc:
                raise RoverError(
                    f"Unable to connect to rover at {self.host}:{self.port}: {exc}"
                ) from exc

            self._socket = sock
            self._reader = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader.start()

    def close(self) -> None:
        with self._state_lock:
            self._stop.set()
            sock = self._socket
            self._socket = None
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        with self._response_condition:
            self._response_condition.notify_all()

    def _connection_failed(self, exc: BaseException) -> None:
        with self._state_lock:
            self._last_error = str(exc)
            self._stop.set()
            sock = self._socket
            self._socket = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        with self._response_condition:
            self._response_condition.notify_all()

    def _send(self, data: bytes) -> None:
        with self._send_lock:
            with self._state_lock:
                sock = self._socket
            if sock is None:
                raise RoverError("Rover TCP connection is closed")
            try:
                sock.sendall(data)
            except OSError as exc:
                self._connection_failed(exc)
                raise RoverError(f"Rover TCP send failed: {exc}") from exc

    def _reader_loop(self) -> None:
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                with self._state_lock:
                    sock = self._socket
                if sock is None:
                    return

                try:
                    data = sock.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    raise ConnectionError("Rover closed the TCP connection")
                buffer.extend(data)

                while True:
                    start = buffer.find(b"{")
                    if start < 0:
                        buffer.clear()
                        break
                    end = buffer.find(b"}", start)
                    if end < 0:
                        if start:
                            del buffer[:start]
                        break

                    frame = bytes(buffer[start : end + 1])
                    del buffer[: end + 1]

                    if frame == b"{Heartbeat}":
                        self._send(b"{Heartbeat}")
                    else:
                        with self._response_condition:
                            self._responses.append(frame)
                            self._response_condition.notify_all()
        except BaseException as exc:
            if not self._stop.is_set():
                self._connection_failed(exc)

    def _request(
        self,
        payload: dict[str, Any],
        *,
        tag: str,
        accept_ok: bool = False,
    ) -> str:
        with self._command_lock:
            self.connect()
            command = dict(payload)
            command["H"] = tag
            encoded = json.dumps(command, separators=(",", ":")).encode("ascii")

            with self._response_condition:
                self._responses.clear()
            self._send(encoded)

            tagged = re.compile(rb"^\{" + re.escape(tag.encode("ascii")) + rb"_([^}]*)\}$")
            deadline = time.monotonic() + self.response_timeout

            with self._response_condition:
                while True:
                    while self._responses:
                        frame = self._responses.popleft()
                        match = tagged.match(frame)
                        if match:
                            return match.group(1).decode("ascii", errors="replace")
                        if accept_ok and frame == b"{ok}":
                            return "ok"

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RoverError("Rover TCP command timed out")
                    if not self.connected:
                        detail = self._last_error or "connection closed"
                        raise RoverError(f"Rover TCP connection failed: {detail}")
                    self._response_condition.wait(timeout=remaining)

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
