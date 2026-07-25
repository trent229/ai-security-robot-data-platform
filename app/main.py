"""Web dashboard joining camera feeds, Ring events, and rover telemetry."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, send_file

from app.analytics import TelemetryAnalyzer
from app.person_detection import PersonDetectionService
from app.ring_camera import RingCameraCollector
from app.rover import RoverError, RoverSerial
from app.rover_tcp import RoverTCP
from app.sure_sight import SureSightCollector


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}

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

RING_ENABLED = os.getenv("RING_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
RING_DEVICE_NAME = os.getenv("RING_DEVICE_NAME", "")
RING_TOKEN_PATH = os.getenv("RING_TOKEN_PATH", "runtime/ring_token.json")
RING_POLL_SECONDS = int(os.getenv("RING_POLL_SECONDS", "30"))
RING_SNAPSHOT_PATH = os.getenv("RING_SNAPSHOT_PATH", "runtime/ring_latest.jpg")
EVENT_LOG_PATH = os.getenv("EVENT_LOG_PATH", "runtime/events.jsonl")
SURE_SIGHT_STATUS_URL = os.getenv(
    "SURE_SIGHT_STATUS_URL", "http://127.0.0.1:5000/api/status"
)
SURE_SIGHT_POLL_SECONDS = float(os.getenv("SURE_SIGHT_POLL_SECONDS", "1"))
AI_ENABLED = env_flag("AI_ENABLED", False)
AI_CAMERA_URL = os.getenv("AI_CAMERA_URL", ROVER_CAMERA_STREAM_URL)
AI_MODEL_PATH = os.getenv(
    "AI_MODEL_PATH",
    "runtime/ai/person_detector.onnx",
)
AI_WRAPPER_PATH = os.getenv(
    "AI_WRAPPER_PATH",
    "runtime/ai/mp_persondet.py",
)
AI_SNAPSHOT_PATH = os.getenv(
    "AI_SNAPSHOT_PATH",
    "runtime/ai/latest_detection.jpg",
)
AI_POLL_SECONDS = float(os.getenv("AI_POLL_SECONDS", "5"))
AI_SCORE_THRESHOLD = float(os.getenv("AI_SCORE_THRESHOLD", "0.45"))
AI_EVENT_COOLDOWN_SECONDS = float(
    os.getenv("AI_EVENT_COOLDOWN_SECONDS", "15")
)
AI_CAPTURE_TIMEOUT_SECONDS = float(
    os.getenv("AI_CAPTURE_TIMEOUT_SECONDS", "20")
)
AI_AUTOMATIC_STOP = env_flag("AI_AUTOMATIC_STOP", False)

app = Flask(__name__)
if ROVER_TRANSPORT == "serial":
    rover = RoverSerial(port=ROVER_PORT)
else:
    rover = RoverTCP(host=ROVER_HOST, port=ROVER_TCP_PORT)

analyzer = TelemetryAnalyzer(log_path=EVENT_LOG_PATH)
ring_collector = RingCameraCollector(
    enabled=RING_ENABLED,
    token_path=RING_TOKEN_PATH,
    device_name=RING_DEVICE_NAME,
    poll_seconds=RING_POLL_SECONDS,
    snapshot_path=RING_SNAPSHOT_PATH,
    event_log_path=EVENT_LOG_PATH,
)
sure_sight_collector = SureSightCollector(
    status_url=SURE_SIGHT_STATUS_URL,
    poll_seconds=SURE_SIGHT_POLL_SECONDS,
    event_log_path=EVENT_LOG_PATH,
)
person_detector = PersonDetectionService(
    enabled=AI_ENABLED,
    camera_url=AI_CAMERA_URL,
    model_path=AI_MODEL_PATH,
    wrapper_path=AI_WRAPPER_PATH,
    event_log_path=EVENT_LOG_PATH,
    snapshot_path=AI_SNAPSHOT_PATH,
    poll_seconds=AI_POLL_SECONDS,
    score_threshold=AI_SCORE_THRESHOLD,
    event_cooldown_seconds=AI_EVENT_COOLDOWN_SECONDS,
    capture_timeout_seconds=AI_CAPTURE_TIMEOUT_SECONDS,
    automatic_stop=AI_AUTOMATIC_STOP,
    stop_callback=rover.stop,
)

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
    header { display: flex; align-items: center; gap: 14px; padding: 12px 20px;
             background: #0c1d2a; border-bottom: 1px solid #21455e; }
    .brand-logo { width: clamp(46px, 7vw, 72px); height: clamp(46px, 7vw, 72px);
                  object-fit: contain; flex: 0 0 auto; border-radius: 8px; }
    h1 { margin: 0; font-size: clamp(20px, 3vw, 32px); }
    main { display: grid; gap: 16px; padding: 16px; grid-template-columns: 1fr 1fr; }
    .card { background: #102330; border: 1px solid #21455e; border-radius: 12px; padding: 14px; }
    .camera { width: 100%; max-height: 55vh; object-fit: contain; background: #000; }
    .reading { font-size: 48px; font-weight: 700; color: #5eead4; }
    .status { color: #9fc2d8; white-space: pre-line; }
    .wide { grid-column: 1 / -1; }
    button { width: 100%; min-height: 48px; margin-top: 10px; padding: 10px 12px;
             border: 0; border-radius: 8px; font-size: clamp(12px, 1.4vw, 15px);
             line-height: 1.2; font-weight: 700; white-space: normal;
             overflow-wrap: anywhere; cursor: pointer; }
    .stop { background: #ef4444; color: white; }
    .auto { background: #22c55e; color: #04130a; }
    @media (max-width: 800px) { main { grid-template-columns: 1fr; } .wide { grid-column: auto; } }
  </style>
</head>
<body>
  <header>
    <img class="brand-logo" src="/static/suresight_logo.png" alt="Sure Sight logo">
    <h1>AI Security Robot Data Platform</h1>
  </header>
  <main>
    <section class="card">
      <h2>Fixed Security Camera</h2>
      <img id="fixed-camera" class="camera" alt="Fixed security camera">
    </section>
    <section class="card">
      <h2>Rover Camera</h2>
      <img id="rover-camera" class="camera" alt="Rover camera">
    </section>
    <section class="card">
      <h2>Ring Camera Data</h2>
      <img id="ring-snapshot" class="camera" alt="Latest Ring snapshot">
      <p id="ring-status" class="status">Loading Ring status…</p>
    </section>
    <section class="card">
      <h2>Rover Telemetry</h2>
      <div id="distance" class="reading">-- cm</div>
      <p id="status" class="status">Connecting to rover…</p>
      <button class="stop" onclick="commandRover('stop')">Emergency Stop</button>
      <button class="auto" onclick="startAutonomous()">Start Autonomous Mode</button>
    </section>
    <section class="card wide">
      <h2>Sure Sight Runtime</h2>
      <p id="sure-sight-status" class="status">Loading Sure Sight status…</p>
    </section>
    <section class="card wide">
      <h2>AI Person Detection</h2>
      <img id="ai-snapshot" class="camera" alt="Latest AI person detection"
           style="display:none">
      <p id="ai-status" class="status">Loading AI detector status…</p>
    </section>
    <section class="card wide">
      <h2>Combined Event Timeline</h2>
      <p id="event-timeline" class="status">Loading recorded events…</p>
    </section>
  </main>
  <script>
    document.getElementById('fixed-camera').src =
      `${location.protocol}//${location.hostname}:5000/stream.mjpg`;
    document.getElementById('rover-camera').src = {{ rover_camera_url|tojson }};

    async function refreshDistance() {
      const status = document.getElementById('status');
      try {
        const response = await fetch('/api/rover/distance', {cache: 'no-store'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Rover unavailable');
        const distance = document.getElementById('distance');
        distance.textContent = `${data.filtered_distance_cm} cm`;
        const colors = {CLEAR:'#5eead4', CAUTION:'#facc15', OBSTACLE:'#ef4444'};
        distance.style.color = colors[data.proximity_state] || '#5eead4';
        status.textContent = `${data.proximity_state} • Raw: ${data.distance_cm} cm • ` +
          `Filtered: ${data.filtered_distance_cm} cm • ${new Date(data.timestamp).toLocaleTimeString()}`;
      } catch (error) {
        status.textContent = error.message;
      }
    }

    async function refreshRing() {
      const response = await fetch('/api/ring/status', {cache: 'no-store'});
      const data = await response.json();
      const lines = [
        `State: ${data.connected ? 'CONNECTED' : (data.enabled ? 'WAITING' : 'DISABLED')}`,
        `Device: ${data.device_name || '--'}`,
        `Battery: ${data.battery_life ?? '--'}`,
        `Wi-Fi RSSI: ${data.wifi_signal_strength ?? '--'}`,
        `Last poll: ${data.last_poll ? new Date(data.last_poll).toLocaleTimeString() : '--'}`,
        data.last_event ? `Last event: ${data.last_event.kind} at ${new Date(data.last_event.timestamp).toLocaleTimeString()}` : '',
        data.error || ''
      ].filter(Boolean);
      document.getElementById('ring-status').textContent = lines.join('\\n');
      if (data.snapshot_available) {
        document.getElementById('ring-snapshot').src = '/api/ring/snapshot?t=' + Date.now();
      }
    }

    async function refreshSureSight() {
      const response = await fetch('/api/sure-sight/status', {cache: 'no-store'});
      const data = await response.json();
      const lines = [
        `State: ${data.connected ? 'CONNECTED' : 'WAITING'}`,
        `Alert: ${data.alert_active ? 'ACTIVE' : 'IDLE'}`,
        `Event ID: ${data.event_id ?? '--'}`,
        `Projector: ${data.projector_enabled ? 'ENABLED' : 'STANDBY'}`,
        `Message: ${data.message || '--'}`,
        data.error || ''
      ].filter(Boolean);
      document.getElementById('sure-sight-status').textContent = lines.join('\\n');
    }

    async function refreshAI() {
      const response = await fetch('/api/ai/status', {cache: 'no-store'});
      const data = await response.json();
      const confidence = data.confidence == null
        ? '--'
        : `${(data.confidence * 100).toFixed(1)}%`;
      const lines = [
        `State: ${data.enabled ? (data.running ? 'RUNNING' : 'STOPPED') : 'DISABLED'}`,
        `Camera: ${data.connected ? 'CONNECTED' : 'WAITING'}`,
        `Person: ${data.person_detected ? 'DETECTED' : 'NOT DETECTED'}`,
        `Confidence: ${confidence}`,
        `Inference: ${data.inference_ms ?? '--'} ms`,
        `Detection events: ${data.detection_events ?? 0}`,
        `Automatic stop: ${data.automatic_stop_enabled ? 'ENABLED' : 'DISABLED'}`,
        `Last action: ${data.last_action || '--'}`,
        data.error || ''
      ].filter(Boolean);
      document.getElementById('ai-status').textContent = lines.join('\\n');

      const snapshot = document.getElementById('ai-snapshot');
      if (data.snapshot_available) {
        snapshot.src = '/api/ai/snapshot?t=' + Date.now();
        snapshot.style.display = 'block';
      }
    }

    async function refreshEvents() {
      const response = await fetch('/api/events?limit=12', {cache: 'no-store'});
      const data = await response.json();
      const lines = data.events.map(event => {
        const time = event.timestamp ? new Date(event.timestamp).toLocaleString() : '--';
        const detail = event.kind || event.state || event.message || event.type;
        return `${time} • ${event.source || 'platform'} • ${detail}`;
      });
      document.getElementById('event-timeline').textContent =
        lines.length ? lines.join('\\n') : 'No recorded events yet.';
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
    refreshRing();
    refreshSureSight();
    refreshAI();
    refreshEvents();
    setInterval(refreshDistance, 3000);
    setInterval(refreshRing, 10000);
    setInterval(refreshSureSight, 1000);
    setInterval(refreshAI, 2000);
    setInterval(refreshEvents, 3000);
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
        ring=ring_collector.status(),
        sure_sight=sure_sight_collector.status(),
        ai_person_detection=person_detector.status(),
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
    from flask import request

    try:
        limit = min(max(int(request.args.get("limit", "100")), 1), 500)
    except ValueError:
        return jsonify(error="limit must be an integer", timestamp=now_iso()), 400

    events: list[dict] = []
    log_path = Path(EVENT_LOG_PATH)
    if log_path.is_file():
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    event = json.loads(line)
                    if (
                        not event.get("source")
                        and event.get("type") == "proximity_state_change"
                    ):
                        event["source"] = "rover"
                    events.append(event)
                except (json.JSONDecodeError, TypeError):
                    app.logger.warning("Skipped malformed event-log line")
        except OSError as exc:
            return jsonify(error=f"Unable to read event log: {exc}", timestamp=now_iso()), 500

    events.sort(key=lambda event: str(event.get("timestamp", "")), reverse=True)
    return jsonify(
        events=events,
        rover_sample_count=analyzer.sample_count,
        persisted_event_count=len(events),
        timestamp=now_iso(),
    )


@app.get("/api/ring/status")
def ring_status():
    return jsonify(**ring_collector.status())


@app.get("/api/ring/events")
def ring_events():
    return jsonify(events=ring_collector.recent_events(), timestamp=now_iso())


@app.get("/api/sure-sight/status")
def sure_sight_status():
    return jsonify(**sure_sight_collector.status())


@app.get("/api/sure-sight/events")
def sure_sight_events():
    return jsonify(events=sure_sight_collector.recent_events(), timestamp=now_iso())


@app.get("/api/ai/status")
def ai_status():
    return jsonify(**person_detector.status())


@app.get("/api/ai/events")
def ai_events():
    return jsonify(events=person_detector.recent_events(), timestamp=now_iso())


@app.get("/api/ai/snapshot")
def ai_snapshot():
    status = person_detector.status()
    if not status["snapshot_available"]:
        return jsonify(error="No AI detection snapshot is available", timestamp=now_iso()), 404
    response = send_file(person_detector.snapshot_path.resolve(), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/ring/snapshot")
def ring_snapshot():
    status = ring_collector.status()
    if not status["snapshot_available"]:
        return jsonify(error="No Ring snapshot is available", timestamp=now_iso()), 404
    response = send_file(ring_collector.snapshot_path.resolve(), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store"
    return response


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


def warm_connections() -> None:
    ring_collector.start()
    sure_sight_collector.start()
    person_detector.start()
    try:
        rover.connect()
    except RoverError as exc:
        app.logger.warning("Rover startup connection failed: %s", exc)


if __name__ == "__main__":
    threading.Thread(target=warm_connections, daemon=True).start()
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
