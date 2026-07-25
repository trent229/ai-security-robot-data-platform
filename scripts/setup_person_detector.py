#!/usr/bin/env python3
"""Download the OpenCV Zoo person detector into the ignored runtime folder."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
from urllib.request import Request, urlopen


BASE_URL = (
    "https://raw.githubusercontent.com/opencv/opencv_zoo/main/"
    "models/person_detection_mediapipe"
)
FILES = {
    "mp_persondet.py": f"{BASE_URL}/mp_persondet.py",
    "LICENSE": f"{BASE_URL}/LICENSE",
    "person_detector.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/"
        "models/person_detection_mediapipe/"
        "person_detection_mediapipe_2023mar_int8bq.onnx"
    ),
}
MINIMUM_SIZES = {
    "mp_persondet.py": 20_000,
    "LICENSE": 100,
    "person_detector.onnx": 1_000_000,
}


def download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "AI-Security-Setup/1.0"})
    temporary = destination.with_suffix(destination.suffix + ".download")
    with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    if temporary.stat().st_size < MINIMUM_SIZES[destination.name]:
        size = temporary.stat().st_size
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded {destination.name} is unexpectedly small ({size} bytes)"
        )
    temporary.replace(destination)


def main() -> int:
    destination_dir = Path("runtime/ai")
    destination_dir.mkdir(parents=True, exist_ok=True)

    for name, url in FILES.items():
        destination = destination_dir / name
        if destination.is_file() and destination.stat().st_size >= MINIMUM_SIZES[name]:
            print(f"Ready: {destination} ({destination.stat().st_size} bytes)")
            continue
        print(f"Downloading {name} from OpenCV Zoo...")
        download(url, destination)
        print(f"Saved: {destination} ({destination.stat().st_size} bytes)")

    print("OpenCV person detector setup complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Setup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
