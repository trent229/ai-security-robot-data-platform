"""Real-time rover telemetry filtering and event logging."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import statistics
import threading
from typing import Any


class TelemetryAnalyzer:
    def __init__(
        self,
        log_path: str = "runtime/events.jsonl",
        window_size: int = 5,
        stop_distance_cm: int = 25,
        caution_distance_cm: int = 50,
    ) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.stop_distance_cm = stop_distance_cm
        self.caution_distance_cm = caution_distance_cm

        self._samples: deque[int] = deque(maxlen=window_size)
        self._events: deque[dict[str, Any]] = deque(maxlen=50)
        self._last_filtered: int | None = None
        self._last_state: str | None = None
        self._lock = threading.RLock()

    def record(self, distance_cm: int, timestamp: str) -> dict[str, Any]:
        with self._lock:
            self._samples.append(distance_cm)
            filtered = round(statistics.median(self._samples))

            if filtered <= self.stop_distance_cm:
                state = "OBSTACLE"
            elif filtered <= self.caution_distance_cm:
                state = "CAUTION"
            else:
                state = "CLEAR"

            change_rate = (
                0
                if self._last_filtered is None
                else filtered - self._last_filtered
            )

            result = {
                "distance_cm": distance_cm,
                "filtered_distance_cm": filtered,
                "change_cm": change_rate,
                "proximity_state": state,
                "sample_count": len(self._samples),
                "timestamp": timestamp,
            }

            if state != self._last_state:
                event = {
                    "type": "proximity_state_change",
                    "state": state,
                    "filtered_distance_cm": filtered,
                    "timestamp": timestamp,
                }
                self._events.append(event)
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(event) + "\n")

            self._last_filtered = filtered
            self._last_state = state
            return result

    def recent_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._events))

    @property
    def sample_count(self) -> int:
        with self._lock:
            return len(self._samples)
