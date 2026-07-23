"""Background collection of Sure Sight alert and projector status."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SureSightCollector:
    """Poll the local Sure Sight runtime and persist new alert events."""

    def __init__(
        self,
        *,
        status_url: str = "http://127.0.0.1:5000/api/status",
        event_log_path: str = "runtime/events.jsonl",
        poll_seconds: float = 1.0,
    ) -> None:
        self.status_url = status_url
        self.event_log_path = Path(event_log_path)
        self.poll_seconds = max(0.5, poll_seconds)
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._events: deque[dict[str, Any]] = deque(maxlen=50)
        self._last_event_id = self._load_last_event_id()
        self._status: dict[str, Any] = {
            "connected": False,
            "status_url": self.status_url,
            "alert_active": None,
            "event_id": self._last_event_id,
            "message": None,
            "projector_enabled": None,
            "remaining_seconds": None,
            "last_poll": None,
            "error": None,
        }
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _load_last_event_id(self) -> Any:
        if not self.event_log_path.is_file():
            return None
        try:
            for line in reversed(
                self.event_log_path.read_text(encoding="utf-8").splitlines()[-500:]
            ):
                event = json.loads(line)
                if event.get("source") == "sure_sight" and event.get("event_id") is not None:
                    return event["event_id"]
        except (OSError, ValueError, TypeError):
            pass
        return None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="sure-sight-collector",
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

    def _run(self) -> None:
        while not self._stop.is_set():
            self._poll()
            self._stop.wait(self.poll_seconds)

    def _poll(self) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        request = Request(
            self.status_url,
            headers={"Accept": "application/json", "User-Agent": "AI-Security-Data-Platform/1.0"},
        )
        try:
            with urlopen(request, timeout=2.0) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            self._set_status(
                connected=False,
                last_poll=timestamp,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        event_id = payload.get("event_id")
        if event_id is not None and event_id != self._last_event_id:
            event = {
                "type": "sure_sight_alert",
                "source": "sure_sight",
                "event_id": event_id,
                "alert_active": bool(payload.get("alert_active")),
                "message": payload.get("message"),
                "projector_enabled": bool(payload.get("projector_enabled")),
                "remaining_seconds": payload.get("remaining_seconds"),
                "timestamp": timestamp,
            }
            with self._lock:
                self._events.append(event)
            with self.event_log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(event) + "\n")
            self._last_event_id = event_id

        self._set_status(
            connected=True,
            alert_active=bool(payload.get("alert_active")),
            event_id=event_id,
            message=payload.get("message"),
            projector_enabled=bool(payload.get("projector_enabled")),
            remaining_seconds=payload.get("remaining_seconds"),
            last_poll=timestamp,
            error=None,
        )
