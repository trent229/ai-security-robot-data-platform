# Verification Evidence — July 23, 2026

## Ring collector

```json
{
  "connected": true,
  "device_name": "Front Door",
  "enabled": true,
  "snapshot_available": true,
  "wifi_signal_category": "good"
}
```

Observed Ring event types included:

- `motion`
- `on_demand`

## Sure Sight collector

Sure Sight status:

```json
{
  "connected": true,
  "event_id": 2,
  "projector_enabled": false,
  "status_url": "http://127.0.0.1:5000/api/status"
}
```

Live alert test:

```json
{
  "alert_active": true,
  "event_id": 3,
  "message": "Activity detected at the entrance",
  "projector_enabled": true,
  "remaining_seconds": 11.0,
  "source": "sure_sight",
  "type": "sure_sight_alert"
}
```

## Persistent event timeline

The platform recovered 61 persisted events after restart. The stored timeline
contained Ring, Sure Sight, and rover records. Older proximity events were
normalized to the rover source.

## Compilation

The following modules compiled without errors:

- `app/main.py`
- `app/analytics.py`
- `app/ring_camera.py`
- `app/sure_sight.py`
- `scripts/ring_auth.py`

## Data protection

The following local material is excluded from Git:

- Ring authentication token
- Runtime event log
- Latest Ring snapshot
- Local backup copies
