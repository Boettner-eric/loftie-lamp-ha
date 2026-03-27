"""Async API client for Loftie Lamp.

Communicates with the Loftie device via the Firebase-backed gateway API.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Load app presets (gradient LED patterns extracted from decompiled Loftie app)
_PRESETS_PATH = os.path.join(os.path.dirname(__file__), "presets.json")
APP_PRESETS: dict[str, list[dict]] = {}
if os.path.exists(_PRESETS_PATH):
    with open(_PRESETS_PATH) as _f:
        APP_PRESETS = json.load(_f)
    # Halve all preset values for lower brightness
    for _name, _leds in APP_PRESETS.items():
        for _led in _leds:
            for _key in ("r", "g", "b", "w"):
                _led[_key] = max(0, _led[_key] // 2)
APP_PRESETS_LOWER: dict[str, str] = {k.lower(): k for k in APP_PRESETS}

PRESET_DOC_IDS = {
    "no": "G1uGrdnMWapF7v1vnMxX",
    "night": "AxMu54dO5XuTTK6fmHv2",
    "bali": "oYU1HsEe9lWjmkUPdGc3",
    "joshuaTree": "NhFNg7N3HqcVEz9NKdj9",
    "santorini": "eGSTTgCPiYNv4ZVMlf4g",
    "tulum": "Y1Fl1rXcewDDwBltDz6H",
    "santaFe": "wRSaNEEA7Y0X4vwmlVzy",
    "dubai": "AWHcsS4t8JKK83jIuJgI",
    "frenchRiviera": "8kdtErfWQOU6UOUBcWjC",
    "tuscany": "1yz9TCFez6bwaLldI0jB",
    "fiji": "YORGHdDxyw9ifQEf99x2",
    "budapest": "EdsIsCRgNuSO8hdhLeLO",
    "siemReap": "EUDXDThOnO93luo1Xc6w",
    "maui": "CHDOfJ87u0H8NkZtmomf",
    "cappadocia": "iPJv4jgPWoeGl73nBaw6",
    "red": "KhTpObkxVbNrL8Z9rIbo",
    "candle": "jU8fYdXpNxGwdBjbD6DG",
    "blush": "hmxHIN3MroT3SDXjCzy9",
    "fog": "EWF2xQRvQtepFHFnk7yT",
    "canyon": "MNRGRNcWxmKCF9XSsuNf",
    "ember": "bbq5Snn8ptF039w5829u",
    "goldenHour": "iQNMIRbURddSdkPQXpZy",
    "warmth": "ZHFKNN5YZL9ILUF2VFwl",
    "desert": "VNSwkAGWLw8IC9grKr9j",
    "overCast": "3XX0w912Z7lSFkufaSQc",
    "mist": "XTY0E1E6ZYfT7DRN1gdt",
    "woodLand": "qhfestNpi8TKFWh5tQkx",
    "vine": "imJ4uvpXu4zXL4ryAJbY",
    "air": "ZYtAQVMymhuyUyCIhj1C",
    "highNoon": "u3gujHk1r9zkOAZom2BQ",
    "coast": "p0SuqZ93RaIGoN3AhMfP",
    "cloud": "ZRF0zBmTbZ4JnfbWpFKx",
    "pride": "o4iZoJojxZeI8TbdtpOB",
    "american": "Qnr6tgzKbweVVfwIUvW8",
    "speakNow": "3J5MXfVZiD0SgK4y8DGM",
}


def _make_solid_leds(r: int, g: int, b: int, w: int = 0) -> list[dict]:
    """Create array of 20 identical RGBW LEDs."""
    return [{"r": r, "g": g, "b": b, "w": w} for _ in range(20)]


def _parse_firestore_state(doc: dict) -> dict:
    """Parse a Firestore device document into a plain config dict."""
    state = doc["fields"].get("state", {}).get("mapValue", {}).get("fields", {})

    selected = int(state.get("selectedLampMode", {}).get("integerValue", "3"))
    lamp_on = state.get("lampOn", {}).get("booleanValue", True)
    night_light = int(state.get("nightLight", {}).get("integerValue", "2"))
    night_light_on = state.get("nightLightOn", {}).get("booleanValue", False)

    modes_array = state.get("lampModes", {}).get("arrayValue", {}).get("values", [])
    lamp_modes = []
    for mode in modes_array:
        m = mode.get("mapValue", {}).get("fields", {})
        idx = int(m.get("index", {}).get("integerValue", "0"))
        ena = int(m.get("enable", {}).get("integerValue", "1"))
        leds_arr = m.get("leds", {}).get("arrayValue", {}).get("values", [])
        leds = []
        for led in leds_arr:
            lf = led.get("mapValue", {}).get("fields", {})
            leds.append({
                "r": int(lf.get("r", {}).get("integerValue", "0")),
                "g": int(lf.get("g", {}).get("integerValue", "0")),
                "b": int(lf.get("b", {}).get("integerValue", "0")),
                "w": int(lf.get("w", {}).get("integerValue", "0")),
            })
        lamp_modes.append({"index": idx, "leds": leds, "enable": ena})

    return {
        "lampOn": lamp_on,
        "selectedLampMode": selected,
        "nightLight": night_light,
        "nightLightOn": night_light_on,
        "lampModes": lamp_modes,
    }


class LoftieClient:
    """Async client for the Loftie device gateway API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        firebase_api_key: str,
        device_id: str,
        gateway_url: str,
        refresh_token: str,
    ) -> None:
        self._session = session
        self._firebase_api_key = firebase_api_key
        self._device_id = device_id
        self._gateway_url = gateway_url
        self._refresh_token = refresh_token
        self._cached_token: str | None = None
        self._token_expires_at: float = 0

    async def _get_token(self) -> str:
        """Get a Firebase ID token, using cached version if still valid."""
        # Firebase ID tokens last 3600s; refresh 5 min early to be safe
        if self._cached_token and time.monotonic() < self._token_expires_at:
            return self._cached_token

        url = f"https://securetoken.googleapis.com/v1/token?key={self._firebase_api_key}"
        async with self._session.post(url, json={
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }) as resp:
            resp.raise_for_status()
            result = await resp.json()

        self._cached_token = result["id_token"]
        expires_in = int(result.get("expires_in", 3600))
        self._token_expires_at = time.monotonic() + expires_in - 300
        return self._cached_token

    def _invalidate_token(self) -> None:
        """Clear cached token so the next call fetches a fresh one."""
        self._cached_token = None
        self._token_expires_at = 0

    async def _authed_request(self, method: str, url: str, **kwargs) -> dict | None:
        """Make an authenticated request, retrying once on 401."""
        for attempt in range(2):
            token = await self._get_token()
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {token}"
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 401 and attempt == 0:
                    _LOGGER.debug("Got 401, refreshing token and retrying")
                    self._invalidate_token()
                    continue
                resp.raise_for_status()
                return await resp.json()
        return None

    async def _send_config(self, config_data: dict) -> dict | None:
        """Send config to the Loftie device gateway API."""
        return await self._authed_request("POST", self._gateway_url, json={
            "device_id": self._device_id,
            "config_data": config_data,
        })

    async def _read_device_state(self) -> dict:
        """Read current device state from Firestore."""
        url = (
            f"https://firestore.googleapis.com/v1/projects/loftie-4f472"
            f"/databases/(default)/documents/devices/{self._device_id}"
        )
        return await self._authed_request("GET", url)

    async def _update_firestore_fields(self, fields: dict) -> None:
        """Update specific fields on the device document in Firestore."""
        url = (
            f"https://firestore.googleapis.com/v1/projects/loftie-4f472"
            f"/databases/(default)/documents/devices/{self._device_id}"
        )
        mask_params = "&".join(f"updateMask.fieldPaths={k}" for k in fields)
        url = f"{url}?{mask_params}"
        await self._authed_request("PATCH", url, json={"fields": fields})

    async def _get_current_config(self) -> dict:
        """Read current device state and return a config dict."""
        doc = await self._read_device_state()
        return _parse_firestore_state(doc)

    async def _update_timestamp(self) -> None:
        """Update the updated_at field so the app sees our changes."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        await self._update_firestore_fields({
            "updated_at": {"timestampValue": now},
        })

    # -- Public command methods --

    async def turn_on(self) -> None:
        """Turn lamp on."""
        config = await self._get_current_config()
        config["lampOn"] = True
        await self._send_config(config)
        await self._update_timestamp()

    async def turn_off(self) -> None:
        """Turn lamp off."""
        config = await self._get_current_config()
        config["lampOn"] = False
        await self._send_config(config)
        await self._update_timestamp()

    async def set_brightness(self, level: int) -> None:
        """Set lamp brightness (1-5)."""
        level = max(1, min(5, level))
        config = await self._get_current_config()
        config["nightLight"] = level
        config["nightLightOn"] = True
        await self._send_config(config)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        await self._update_firestore_fields({
            "nightlight": {"integerValue": str(level)},
            "updated_at": {"timestampValue": now},
        })

    async def set_color(self, r: int, g: int, b: int, w: int = 0) -> None:
        """Set lamp to a solid color (r, g, b, w as 0-100)."""
        leds = _make_solid_leds(r, g, b, w)
        config = await self._get_current_config()
        config["lampOn"] = True
        config["selectedLampMode"] = 3
        config["lampModes"] = [{"index": 0, "leds": leds, "enable": 1}]
        await self._send_config(config)
        await self._update_timestamp()

    async def set_mode(self, mode_name: str) -> None:
        """Select lamp mode (day/reading/night/1/2)."""
        mode_map = {"day": 0, "reading": 1, "night": 2, "1": 3, "2": 4}
        mode = mode_map.get(mode_name.lower())
        if mode is None:
            _LOGGER.error("Unknown mode: %s", mode_name)
            return
        config = await self._get_current_config()
        config["lampOn"] = True
        config["selectedLampMode"] = mode
        await self._send_config(config)
        await self._update_timestamp()

    async def set_scene(self, scene_name: str) -> None:
        """Apply a named scene (app preset)."""
        canonical = APP_PRESETS_LOWER.get(scene_name.lower())
        if canonical is None:
            _LOGGER.error("Unknown scene: %s", scene_name)
            return
        leds = APP_PRESETS[canonical]

        config = await self._get_current_config()
        config["lampOn"] = True
        config["selectedLampMode"] = 3
        config["lampModes"] = [{"index": 0, "leds": leds, "enable": 1}]
        await self._send_config(config)

        if canonical in PRESET_DOC_IDS:
            ref_field = "lampMode1Ref"
            ref_value = (
                f"projects/loftie-4f472/databases/(default)"
                f"/documents/lamp-modes/{PRESET_DOC_IDS[canonical]}"
            )
            await self._update_firestore_fields({
                ref_field: {"referenceValue": ref_value},
            })
        await self._update_timestamp()

    def get_scene_names(self) -> list[str]:
        """Return available scene names (excluding 'no')."""
        return [n for n in APP_PRESETS if n != "no"]
