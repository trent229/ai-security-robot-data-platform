# AI Security Robot Data Platform

This integration layer combines the existing Sure Sight live camera service with
ELEGOO Smart Robot Car V4.0 telemetry and control on an NVIDIA Jetson Orin Nano.

## Current integration

- Camera source: battery-powered ESP32-S3 over Wi-Fi
- Camera processing/restream: Sure Sight runtime on port 5000
- Rover connection: wireless TCP through the ESP32-to-Uno bridge on port 100
- Dashboard: Flask on port 5050
- Rover camera: dual-network ESP32-S3 stream on the main LAN
- Rover telemetry: ultrasonic distance in centimeters
- Safety controls: stop and confirmed autonomous-mode start
- Telemetry filtering: rolling five-sample median to reduce ultrasonic noise
- Proximity classification: `CLEAR` above 50 cm, `CAUTION` from 26–50 cm,
  and `OBSTACLE` at 25 cm or less
- Event persistence: proximity state changes recorded in
  `runtime/events.jsonl`

## Run

```bash
cd ~/ai-security-robot-data-platform
source .venv/bin/activate
python -m app.main
```

Open `http://JETSON_IP:5050/` from another device on the same network.

The rover camera defaults to `http://192.168.1.251/capture`.
changed DHCP address when launching with:

```bash
ROVER_CAMERA_STREAM_URL=http://NEW_IP:81/stream python -m app.main
```
## Data API

- `GET /api/rover/distance` returns the raw distance, median-filtered distance,
  change from the previous filtered reading, proximity classification, sample
  count, and timestamp.
- `GET /api/events` returns recent proximity-state changes.
- `GET /api/health` reports platform, camera, and rover connection settings.
- `POST /api/rover/stop` sends the emergency-stop command.
- `POST /api/rover/autonomous` starts autonomous mode after confirmation from
  the dashboard.

Runtime event logs are intentionally excluded from Git because they are
generated during operation.

## Hardware state required

For wireless control, reconnect the rover camera communication cable and set the
ELEGOO shield switch to **Cam**. The ESP32 must be connected to the `Recons` LAN.

USB serial remains available for bench testing by launching with
`ROVER_TRANSPORT=serial`. In that mode, disconnect the camera communication
cable, move the shield switch to **Upload**, and use `/dev/ttyUSB0`.

Before enabling autonomous mode, place the rover on the floor in a clear test
area and confirm that the emergency-stop endpoint is available.
