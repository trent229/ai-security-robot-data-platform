"""Background Ring camera event, health, and snapshot collection."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class RingCameraCollector:
    """Poll one Ring doorbell/camera without blocking Flask request threads."""

    def __init__(
        self,
        *,
        enabled: bool,
        token_path: str = "runtime/ring_token.json",
        device_name: str = "",
        event_log_path: str = "runtime/events.jsonl",
        snapshot_path: str = "runtime/ring_latest.jpg",
        poll_seconds: int = 30,
    ) -> None:
        self.enabled = enabled
        self.token_path = Path(token_path)
        self.device_name = device_name.strip()
        self.event_log_path = Path(event_log_path)
        self.snapshot_path = Path(snapshot_path)
        self.poll_seconds = max(15, poll_seconds)

        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        self._events: deque[dict[str, Any]] = deque(maxlen=50)
        self._seen_ids = self._load_seen_ids()
        self._status: dict[str, Any] = {
            "enabled": enabled,
            "connected": False,
            "device_name": self.device_name or None,
            "last_poll": None,
            "last_event": None,
            "battery_life": None,
            "wifi_signal_strength": None,
            "wifi_signal_category": None,
            "snapshot_available": self.snapshot_path.is_file(),
            "error": None if enabled else "Ring collection is disabled",
        }
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _load_seen_ids(self) -> set[str]:
        seen: set[str] = set()
        if not self.event_log_path.is_file():
            return seen
        try:
            lines = self.event_log_path.read_text(encoding="utf-8").splitlines()[-500:]
            for line in lines:
                event = json.loads(line)
                if event.get("source") == "ring" and event.get("event_id"):
                    seen.add(str(event["event_id"]))
        except (OSError, ValueError, TypeError):
            pass
        return seen

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(
            target=self._thread_main,
            name="ring-camera-collector",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def recent_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._events))

    def _set_status(self, **values: Any) -> None:
        with self._lock:
            self._status.update(values)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self._set_status(connected=False, error=f"{type(exc).__name__}: {exc}")

    async def _run(self) -> None:
        from ring_doorbell import Auth, Ring

        if not self.token_path.is_file():
            self._set_status(
                connected=False,
                error=f"Run scripts/ring_auth.py to create {self.token_path}",
            )
            return

        def token_updated(token: dict[str, Any]) -> None:
            self.token_path.write_text(json.dumps(token), encoding="utf-8")
            self.token_path.chmod(0o600)

        token = json.loads(self.token_path.read_text(encoding="utf-8"))
        auth = Auth("SureSightDataPlatform/1.0", token, token_updated)
        ring = Ring(auth)
        try:
            await ring.async_create_session()
            await ring.async_update_data()
            device = self._select_device(ring)
            self._set_status(
                connected=True,
                device_name=device.name,
                error=None,
            )

            while not self._stop.is_set():
                try:
                    await self._poll(device)
                except Exception as exc:
                    self._set_status(
                        connected=False,
                        error=f"{type(exc).__name__}: {exc}",
                        last_poll=datetime.now(timezone.utc).isoformat(),
                    )
                await asyncio.to_thread(self._stop.wait, self.poll_seconds)
        finally:
            await auth.async_close()

    def _select_device(self, ring: Any) -> Any:
        devices = ring.devices()
        cameras = list(devices["doorbots"]) + list(devices["stickup_cams"])
        if not cameras:
            raise RuntimeError("No Ring doorbell or camera was found")
        if not self.device_name:
            return cameras[0]
        for device in cameras:
            if device.name.casefold() == self.device_name.casefold():
                return device
        names = ", ".join(device.name for device in cameras)
        raise RuntimeError(
            f"Ring device {self.device_name!r} not found; available: {names}"
        )

    async def _poll(self, device: Any) -> None:
        await device.async_update_health_data()
        history = await device.async_history(limit=20)
        new_events: list[dict[str, Any]] = []

        for raw in reversed(history):
            event_id = str(raw.get("id", ""))
            if not event_id or event_id in self._seen_ids:
                continue
            event = {
                "type": "ring_camera_event",
                "source": "ring",
                "event_id": event_id,
                "device_name": device.name,
                "kind": _json_value(raw.get("kind")),
                "answered": _json_value(raw.get("answered")),
                "timestamp": _json_value(raw.get("created_at")),
            }
            new_events.append(event)
            self._seen_ids.add(event_id)
            with self.event_log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(event) + "\n")

        if new_events:
            with self._lock:
                self._events.extend(new_events)
            try:
                snapshot = await device.async_get_snapshot()
                if snapshot:
                    self.snapshot_path.write_bytes(snapshot)
            except Exception as exc:
                self._set_status(error=f"Events collected; snapshot failed: {exc}")

        last_event = new_events[-1] if new_events else self.status()["last_event"]
        self._set_status(
            connected=True,
            device_name=device.name,
            last_poll=datetime.now(timezone.utc).isoformat(),
            last_event=last_event,
            battery_life=_json_value(device.battery_life),
            wifi_signal_strength=_json_value(device.wifi_signal_strength),
            wifi_signal_category=_json_value(device.wifi_signal_category),
            snapshot_available=self.snapshot_path.is_file(),
            error=None,
        )
