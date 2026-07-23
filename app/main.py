"""Web dashboard joining the Jetson camera runtime and rover telemetry."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string

from app.rover import RoverError, RoverSerial
from app.rover_tcp import RoverTCP
from app.analytics import TelemetryAnalyzer

CAMERA_STREAM_URL = os.getenv(
    "CAMERA_STREAM_URL", "http://127.0.0.1:5000/stream.mjpg"
)
ROVER_CAMERA_STREAM_URL = os.getenv(
    "ROVER_CAMERA_STREAM_URL", "http://192.168.1.251/capture"
)
ROVER_PORT = os.getenv("ROVER_PORT", "/dev/ttyUSB0")
ROVER_TRANSPORT = os.getenv("ROVER_TRANSPORT", "tcp").lower()
ROVER_HOST = os.getenv("ROVER_HOST", "192.168.1.251")
ROVER_TCP_PORT = int(os.getenv("ROVER_TCP_PORT", "100"))

app = Flask(__name__)
if ROVER_TRANSPORT == "serial":
    rover = RoverSerial(port=ROVER_PORT)
else:
    rover = RoverTCP(host=ROVER_HOST, port=ROVER_TCP_PORT)
    analyzer = TelemetryAnalyzer()

DASHBOARD = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Security Robot Data Platform</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #071018; color: #e8f4ff; }
    header { padding: 16px 20px; background: #0c1d2a; border-bottom: 1px solid #21455e; }
    h1 { margin: 0; font-size: clamp(20px, 3vw, 32px); }
    main { display: grid; gap: 16px; padding: 16px; grid-template-columns: 1fr 1fr; }
    .card { background: #102330; border: 1px solid #21455e; border-radius: 12px; padding: 14px; }
    .camera { width: 100%; max-height: 72vh; object-fit: contain; background: #000; }
    .reading { font-size: 48px; font-weight: 700; color: #5eead4; }
    .status { color: #9fc2d8; }
    .telemetry { grid-column: 1 / -1; }
    button { width: 100%; margin-top: 10px; padding: 14px; border: 0; border-radius: 8px;
             font-size: 17px; font-weight: 700; cursor: pointer; }
    .stop { background: #ef4444; color: white; }
    .auto { background: #22c55e; color: #04130a; }
    @media (max-width: 800px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header><h1>AI Security Robot Data Platform</h1></header>
  <main>
    <section class="card">
      <h2>Fixed Security Camera</h2>
      <img id="fixed-camera" class="camera" alt="Fixed security camera">
    </section>
    <section class="card">
      <h2>Rover Camera</h2>
      <img id="rover-camera" class="camera" alt="Rover camera">
    </section>
    <section class="card telemetry">
      <h2>Rover Telemetry</h2>
      <div id="distance" class="reading">-- cm</div>
      <p id="status" class="status">Connecting to rover…</p>
      <button class="stop" onclick="commandRover('stop')">Emergency Stop</button>
      <button class="auto" onclick="startAutonomous()">Start Autonomous Mode</button>
    </section>
  </main>
  <script>
    document.getElementById('fixed-camera').src =
      `${location.protocol}//${location.hostname}:5000/stream.mjpg`;
    document.getElementById('rover-camera').src = {{ rover_camera_url|tojson }};
    setInterval(() => { document.getElementById('rover-camera').src = {{ rover_camera_url|tojson }} + '?t=' + Date.now(); }, 10000);

    async function refreshDistance() {
      const status = document.getElementById('status');
      try {
        const response = await fetch('/api/rover/distance', {cache: 'no-store'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Rover unavailable');
        const distance = document.getElementById('distance');
        distance.textContent = `${data.filtered_distance_cm} cm`;

        const stateColors = {
          CLEAR: '#5eead4',
          CAUTION: '#facc15',
          OBSTACLE: '#ef4444'
        };
        distance.style.color = stateColors[data.proximity_state] || '#5eead4';

        status.textContent =
          `${data.proximity_state} • Raw: ${data.distance_cm} cm • ` +
          `Filtered: ${data.filtered_distance_cm} cm • ` +
          `${new Date(data.timestamp).toLocaleTimeString()}`;
      } catch (error) {
        status.textContent = error.message;
      }
    }

    async function commandRover(command) {
      const response = await fetch(`/api/rover/${command}`, {method: 'POST'});
      const data = await response.json();
      document.getElementById('status').textContent =
        response.ok ? data.status : (data.error || 'Command failed');
    }

    function startAutonomous() {
      if (confirm('Start autonomous movement? Confirm the rover is on the floor with a clear test area.')) {
        commandRover('autonomous');
      }
    }

    refreshDistance();
    setInterval(refreshDistance, 3000);
  </script>
</body>
</html>
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/")
def dashboard():
    return render_template_string(
        DASHBOARD,
        rover_camera_url=ROVER_CAMERA_STREAM_URL,
    )


@app.get("/api/health")
def health():
    return jsonify(
        status="ok",
        rover_connected=rover.connected,
        rover_transport=ROVER_TRANSPORT,
        rover_port=ROVER_PORT,
        rover_host=ROVER_HOST,
        rover_tcp_port=ROVER_TCP_PORT,
        fixed_camera_stream=CAMERA_STREAM_URL,
        rover_camera_stream=ROVER_CAMERA_STREAM_URL,
        timestamp=now_iso(),
    )


@app.get("/api/rover/distance")
def rover_distance():
    timestamp = now_iso()
    try:
        reading = analyzer.record(rover.distance_cm(), timestamp)
        return jsonify(**reading)
    except RoverError as exc:
        return jsonify(error=str(exc), timestamp=timestamp), 503

@app.get("/api/events")
def recent_events():
    return jsonify(
        events=analyzer.recent_events(),
        sample_count=analyzer.sample_count,
        timestamp=now_iso(),
    )

@app.post("/api/rover/stop")
def rover_stop():
    try:
        rover.stop()
        return jsonify(status="Rover stopped", timestamp=now_iso())
    except RoverError as exc:
        return jsonify(error=str(exc), timestamp=now_iso()), 503


@app.post("/api/rover/autonomous")
def rover_autonomous():
    try:
        rover.start_autonomous()
        return jsonify(status="Autonomous mode started", timestamp=now_iso())
    except RoverError as exc:
        return jsonify(error=str(exc), timestamp=now_iso()), 503


def warm_serial_connection() -> None:
    try:
        rover.connect()
    except RoverError as exc:
        app.logger.warning("Rover startup connection failed: %s", exc)


if __name__ == "__main__":
    threading.Thread(target=warm_serial_connection, daemon=True).start()
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
