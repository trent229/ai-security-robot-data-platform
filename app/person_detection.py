"""Background person detection for rover and security camera frames."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from http.client import IncompleteRead
import importlib.util
import json
from pathlib import Path
import socket
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np


class PersonDetectionError(RuntimeError):
    """Raised when the AI detector cannot load or process a frame."""


class PersonDetectionService:
    """Run OpenCV DNN person detection without blocking Flask request threads."""

    def __init__(
        self,
        *,
        enabled: bool,
        camera_url: str,
        model_path: str = "runtime/ai/person_detector.onnx",
        wrapper_path: str = "runtime/ai/mp_persondet.py",
        event_log_path: str = "runtime/events.jsonl",
        snapshot_path: str = "runtime/ai/latest_detection.jpg",
        poll_seconds: float = 5.0,
        score_threshold: float = 0.45,
        event_cooldown_seconds: float = 15.0,
        capture_timeout_seconds: float = 20.0,
        automatic_stop: bool = False,
        stop_callback: Callable[[], None] | None = None,
    ) -> None:
        self.enabled = enabled
        self.camera_url = camera_url
        self.model_path = Path(model_path)
        self.wrapper_path = Path(wrapper_path)
        self.event_log_path = Path(event_log_path)
        self.snapshot_path = Path(snapshot_path)
        self.poll_seconds = max(1.0, poll_seconds)
        self.score_threshold = min(max(score_threshold, 0.05), 0.99)
        self.event_cooldown_seconds = max(0.0, event_cooldown_seconds)
        self.capture_timeout_seconds = max(2.0, capture_timeout_seconds)
        self.automatic_stop = automatic_stop
        self.stop_callback = stop_callback

        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        self._detector: Any = None
        self._events: deque[dict[str, Any]] = deque(maxlen=50)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._last_detected = False
        self._last_event_monotonic = float("-inf")
        self._detection_events = 0
        self._status: dict[str, Any] = {
            "enabled": enabled,
            "running": False,
            "connected": False,
            "model_loaded": False,
            "model_path": str(self.model_path),
            "camera_url": self.camera_url,
            "score_threshold": self.score_threshold,
            "person_detected": False,
            "person_count": 0,
            "confidence": None,
            "last_poll": None,
            "last_detection": None,
            "inference_ms": None,
            "detection_events": 0,
            "snapshot_available": self.snapshot_path.is_file(),
            "automatic_stop_enabled": automatic_stop,
            "last_action": None,
            "error": None if enabled else "AI person detection is disabled",
        }

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(
            target=self._run,
            name="person-detection-service",
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

    def _load_detector(self) -> None:
        if not self.wrapper_path.is_file():
            raise PersonDetectionError(
                f"Detector wrapper not found at {self.wrapper_path}; "
                "run scripts/setup_person_detector.py"
            )
        if not self.model_path.is_file():
            raise PersonDetectionError(
                f"Detector model not found at {self.model_path}; "
                "run scripts/setup_person_detector.py"
            )

        spec = importlib.util.spec_from_file_location(
            "opencv_zoo_mp_persondet",
            self.wrapper_path,
        )
        if spec is None or spec.loader is None:
            raise PersonDetectionError(
                f"Unable to import detector wrapper from {self.wrapper_path}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._detector = module.MPPersonDet(
            modelPath=str(self.model_path),
            nmsThreshold=0.3,
            scoreThreshold=self.score_threshold,
            backendId=cv2.dnn.DNN_BACKEND_OPENCV,
            targetId=cv2.dnn.DNN_TARGET_CPU,
        )

    def _fetch_frame(self) -> np.ndarray:
        request = Request(
            self.camera_url,
            headers={
                "Accept": "image/jpeg,image/*;q=0.9,*/*;q=0.1",
                "User-Agent": "AI-Security-Robot-Data-Platform/1.0",
            },
        )
        payload = bytearray()
        try:
            with urlopen(request, timeout=self.capture_timeout_seconds) as response:
                while len(payload) < 5_000_000:
                    try:
                        chunk = response.read(8192)
                    except (TimeoutError, socket.timeout):
                        break
                    if not chunk:
                        break
                    payload.extend(chunk)
        except IncompleteRead as exc:
            payload.extend(exc.partial)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if not payload:
                raise PersonDetectionError(f"Camera request failed: {exc}") from exc

        if not payload:
            raise PersonDetectionError("Camera returned no image data")

        encoded = np.frombuffer(payload, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise PersonDetectionError(
                f"Camera returned {len(payload)} bytes that were not a usable JPEG"
            )
        return frame

    @staticmethod
    def _annotate(frame: np.ndarray, results: np.ndarray) -> np.ndarray:
        output = frame.copy()
        height, width = output.shape[:2]

        for result in results:
            score = float(result[-1])
            landmarks = result[4:-1].reshape(4, 2).astype(np.int32)
            hip_center, full_body, shoulder_center, upper_body = landmarks

            full_radius = max(1, int(np.linalg.norm(hip_center - full_body)))
            upper_radius = max(1, int(np.linalg.norm(shoulder_center - upper_body)))
            cv2.circle(output, tuple(hip_center), full_radius, (255, 0, 0), 3)
            cv2.circle(output, tuple(shoulder_center), upper_radius, (0, 255, 255), 3)

            for point in landmarks:
                x = max(0, min(int(point[0]), width - 1))
                y = max(0, min(int(point[1]), height - 1))
                cv2.circle(output, (x, y), 4, (0, 0, 255), -1)

            cv2.putText(
                output,
                f"PERSON {score:.2f}",
                (12, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.85,
                (0, 255, 0),
                2,
            )

        return output

    def _record_detection(
        self,
        *,
        timestamp: str,
        results: np.ndarray,
        inference_ms: float,
    ) -> dict[str, Any]:
        confidence = max(float(result[-1]) for result in results)
        action = "logged"

        if self.automatic_stop and self.stop_callback is not None:
            try:
                self.stop_callback()
                action = "rover_stopped"
            except Exception as exc:
                action = f"rover_stop_failed: {exc}"

        event = {
            "type": "ai_person_detection",
            "source": "ai_person_detector",
            "camera": "rover",
            "person_count": len(results),
            "confidence": round(confidence, 4),
            "score_threshold": self.score_threshold,
            "inference_ms": round(inference_ms, 2),
            "action": action,
            "timestamp": timestamp,
        }
        with self.event_log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(event) + "\n")
        with self._lock:
            self._events.append(event)
        self._detection_events += 1
        return event

    def _run(self) -> None:
        self._set_status(running=True, error=None)
        try:
            self._load_detector()
            self._set_status(model_loaded=True)
        except Exception as exc:
            self._set_status(
                running=False,
                model_loaded=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        while not self._stop.is_set():
            loop_started = time.monotonic()
            timestamp = datetime.now(timezone.utc).isoformat()

            try:
                frame = self._fetch_frame()
                inference_started = time.perf_counter()
                results = self._detector.infer(frame)
                inference_ms = (time.perf_counter() - inference_started) * 1000.0
                detected = len(results) > 0
                confidence = (
                    max(float(result[-1]) for result in results) if detected else None
                )
                action = None

                if detected:
                    annotated = self._annotate(frame, results)
                    cv2.imwrite(str(self.snapshot_path), annotated)

                    cooldown_elapsed = (
                        time.monotonic() - self._last_event_monotonic
                        >= self.event_cooldown_seconds
                    )
                    if not self._last_detected and cooldown_elapsed:
                        event = self._record_detection(
                            timestamp=timestamp,
                            results=results,
                            inference_ms=inference_ms,
                        )
                        self._last_event_monotonic = time.monotonic()
                        action = event["action"]

                self._set_status(
                    running=True,
                    connected=True,
                    model_loaded=True,
                    person_detected=detected,
                    person_count=len(results),
                    confidence=round(confidence, 4) if confidence is not None else None,
                    last_poll=timestamp,
                    last_detection=timestamp
                    if detected
                    else self.status()["last_detection"],
                    inference_ms=round(inference_ms, 2),
                    detection_events=self._detection_events,
                    snapshot_available=self.snapshot_path.is_file(),
                    last_action=action or self.status()["last_action"],
                    error=None,
                )
                self._last_detected = detected
            except Exception as exc:
                self._set_status(
                    running=True,
                    connected=False,
                    person_detected=False,
                    person_count=0,
                    last_poll=timestamp,
                    error=f"{type(exc).__name__}: {exc}",
                )
                self._last_detected = False

            elapsed = time.monotonic() - loop_started
            self._stop.wait(max(0.1, self.poll_seconds - elapsed))

        self._set_status(running=False)
