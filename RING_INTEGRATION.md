# Ring Camera Data Integration

This integration adds Ring camera data to the AI Security Robot Data Platform
without changing the Sure Sight door projection workflow.

## Data collected

- Motion and doorbell-button event type
- Ring event ID and timestamp
- Whether the event was answered
- Camera name
- Battery level
- Wi-Fi signal strength and category
- Latest still snapshot after a new Ring event

Ring events are appended to `runtime/events.jsonl`. The authentication token and
latest snapshot also remain under `runtime/`, which is excluded by `.gitignore`.

## Install on the Jetson

Copy these files into the existing repository:

- `app/main.py`
- `app/ring_camera.py`
- `scripts/ring_auth.py`
- `requirements.txt`

Then run:

```bash
cd ~/ai-security-robot-data-platform
source .venv/bin/activate
pip install -r requirements.txt
python scripts/ring_auth.py
```

Enter the Ring account email, password, and two-factor code only in the Jetson
terminal. Do not place them in source code, GitHub, or chat.

The authentication script prints the available camera names. Start the platform
using the exact name shown:

```bash
RING_ENABLED=true \
RING_DEVICE_NAME="Front Door" \
python -m app.main
```

Open `http://JETSON_IP:5050/` and check:

```bash
curl -s http://127.0.0.1:5050/api/ring/status | python -m json.tool
curl -s http://127.0.0.1:5050/api/ring/events | python -m json.tool
```

Trigger one motion event or press the Ring doorbell. Within the configured
30-second polling interval, the dashboard should show the event, updated health
data, and a new still snapshot.

## Optional systemd environment

After the interactive test succeeds, add these environment values to the
platform service:

```ini
Environment=RING_ENABLED=true
Environment=RING_DEVICE_NAME=Front Door
Environment=RING_TOKEN_PATH=runtime/ring_token.json
Environment=RING_POLL_SECONDS=30
```

The service must use the repository as its working directory so the relative
`runtime/` paths resolve correctly.

## Important limitation

The integration gathers Ring event, health, and snapshot data. Ring Live View
continues to run in the Ring browser session used by the projector. The
prototype does not copy or rebroadcast the Ring live stream.
