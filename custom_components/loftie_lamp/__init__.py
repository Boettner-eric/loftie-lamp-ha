"""Loftie Lamp integration for Home Assistant.

Shared state lives in hass.data[DOMAIN] so the light entity and scene switches
stay in sync without polling the lamp.
"""

import logging
from dataclasses import dataclass, field

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import LoftieClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light", "switch"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required("firebase_api_key"): cv.string,
                vol.Required("device_id"): cv.string,
                vol.Required("gateway_url"): cv.string,
                vol.Required("refresh_token"): cv.string,
                vol.Optional("name", default="Loftie Lamp"): cv.string,
                vol.Optional("scenes", default=[]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class LoftieState:
    """Shared lamp state — single source of truth for all entities."""

    is_on: bool = False
    brightness: int = 255  # HA scale 0-255
    hs_color: tuple[float, float] = (0.0, 0.0)
    active_scene: str | None = None  # scene key like "bali", or None for custom color

    # Entities register themselves here to get notified on state changes
    _listeners: list = field(default_factory=list)

    def add_listener(self, cb) -> None:
        self._listeners.append(cb)

    def notify(self, source=None) -> None:
        """Tell all entities (except the source) to update their HA state."""
        for cb in self._listeners:
            if cb is not source:
                cb()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up via YAML — store config, shared state, and API client."""
    conf = config.get(DOMAIN, {})

    session = async_get_clientsession(hass)
    client = LoftieClient(
        session=session,
        firebase_api_key=conf["firebase_api_key"],
        device_id=conf["device_id"],
        gateway_url=conf["gateway_url"],
        refresh_token=conf["refresh_token"],
    )

    hass.data[DOMAIN] = {
        "config": conf,
        "state": LoftieState(),
        "client": client,
    }

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.helpers.discovery.async_load_platform(platform, DOMAIN, {}, config)
        )

    return True
