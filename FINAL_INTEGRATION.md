# Final Platform Integration

The AI Security Robot Data Platform combines three operational data sources:

- Ring camera motion and on-demand events, device health, and snapshots
- Sure Sight alert and projector state from the local runtime
- Indoor Security Rover ultrasonic telemetry and proximity-state changes

All event types are persisted to `runtime/events.jsonl` and returned by
`GET /api/events`.

## Install

From the repository root:

```bash
unzip -o ~/final-platform-integration.zip
source .venv/bin/activate
pip install -r requirements.txt
```

Start the platform for final testing:

```bash
nohup env \
RING_ENABLED=true \
RING_DEVICE_NAME="Front Door" \
.venv/bin/python -m app.main \
> runtime/platform.log 2>&1 &
```

## Verification

```bash
curl -sS http://127.0.0.1:5050/api/ring/status | python3 -m json.tool
curl -sS http://127.0.0.1:5050/api/sure-sight/status | python3 -m json.tool
curl -sS http://127.0.0.1:5050/api/events | python3 -m json.tool
```

Trigger a Sure Sight alert:

```bash
curl -sS -X POST http://127.0.0.1:5000/api/alert
```

Within approximately one second, the combined event response should contain a
record with:

```json
{
  "type": "sure_sight_alert",
  "source": "sure_sight"
}
```

Ring remains the current demonstration and data source. It is not presented as
the final production camera architecture for Sure Sight.
