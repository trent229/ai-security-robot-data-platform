"""Tests for AI detection annotation, event logging, and safety actions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from app.person_detection import PersonDetectionService


class PersonDetectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.runtime_path = Path(self.temporary_directory.name)
        self.stop_calls = 0

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_service(self, *, automatic_stop: bool = False) -> PersonDetectionService:
        def stop_rover() -> None:
            self.stop_calls += 1

        return PersonDetectionService(
            enabled=True,
            camera_url="http://camera.test/capture",
            event_log_path=str(self.runtime_path / "events.jsonl"),
            snapshot_path=str(self.runtime_path / "latest_detection.jpg"),
            automatic_stop=automatic_stop,
            stop_callback=stop_rover,
        )

    @staticmethod
    def detection(score: float = 0.82) -> np.ndarray:
        return np.array(
            [
                [
                    80,
                    40,
                    220,
                    280,
                    150,
                    180,
                    150,
                    285,
                    150,
                    110,
                    150,
                    185,
                    score,
                ]
            ],
            dtype=np.float32,
        )

    def test_annotation_produces_a_changed_image(self) -> None:
        frame = np.zeros((320, 300, 3), dtype=np.uint8)

        annotated = self.make_service()._annotate(frame, self.detection())

        self.assertEqual(annotated.shape, frame.shape)
        self.assertFalse(np.array_equal(annotated, frame))
        grayscale = cv2.cvtColor(annotated, cv2.COLOR_BGR2GRAY)
        self.assertGreater(int(cv2.countNonZero(grayscale)), 0)

    def test_detection_is_written_to_shared_event_log(self) -> None:
        service = self.make_service()

        event = service._record_detection(
            timestamp="2026-07-25T06:30:44+00:00",
            results=self.detection(0.682),
            inference_ms=56.51,
        )

        records = [
            json.loads(line)
            for line in service.event_log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(event["type"], "ai_person_detection")
        self.assertEqual(event["action"], "logged")
        self.assertEqual(event["person_count"], 1)
        self.assertAlmostEqual(event["confidence"], 0.682, places=3)
        self.assertEqual(records, [event])
        self.assertEqual(service.recent_events(), [event])

    def test_automatic_stop_is_explicit_and_recorded(self) -> None:
        service = self.make_service(automatic_stop=True)

        event = service._record_detection(
            timestamp="2026-07-25T06:30:44+00:00",
            results=self.detection(),
            inference_ms=50.0,
        )

        self.assertEqual(self.stop_calls, 1)
        self.assertEqual(event["action"], "rover_stopped")


if __name__ == "__main__":
    unittest.main()
