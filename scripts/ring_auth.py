"""Interactive one-time Ring authentication for the Jetson."""

from __future__ import annotations

import asyncio
import getpass
import json
from pathlib import Path

from ring_doorbell import Auth, Requires2FAError, Ring

TOKEN_PATH = Path("runtime/ring_token.json")


def save_token(token: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)


async def main() -> None:
    username = input("Ring account email: ").strip()
    password = getpass.getpass("Ring account password: ")
    auth = Auth("SureSightDataPlatform/1.0", None, save_token)
    try:
        try:
            await auth.async_fetch_token(username, password)
        except Requires2FAError:
            code = input("Ring two-factor code: ").strip()
            await auth.async_fetch_token(username, password, code)

        ring = Ring(auth)
        await ring.async_update_data()
        devices = ring.devices()
        cameras = list(devices["doorbots"]) + list(devices["stickup_cams"])
        print("Ring authentication saved. Available cameras:")
        for camera in cameras:
            print(f"  - {camera.name}")
    finally:
        await auth.async_close()


if __name__ == "__main__":
    asyncio.run(main())
