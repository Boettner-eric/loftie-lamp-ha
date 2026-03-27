"""Scene switches for Loftie Lamp.

Each scene is a stateful switch in Apple Home:
  - Turn ON  -> activates that scene on the lamp, turns off other scene switches
  - Turn OFF -> turns the lamp off

State is synced via the shared LoftieState — when the light entity changes color
or turns off, scene switches update automatically, and vice versa.
"""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .api import LoftieClient
from .const import DOMAIN, MODE_LABELS, SCENE_LABELS

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up scene switches from YAML config."""
    data = hass.data.get(DOMAIN, {})
    conf = data.get("config", {})
    state = data["state"]
    client: LoftieClient = data["client"]
    scene_names = conf.get("scenes", [])

    entities = []
    for name in scene_names:
        if name in MODE_LABELS:
            label = MODE_LABELS[name]
            command = "mode"
        elif name in SCENE_LABELS:
            label = SCENE_LABELS[name]
            command = "scene"
        else:
            label = name
            command = "scene"

        entities.append(
            LoftieLampSceneSwitch(label, name, command, client, state)
        )

    if entities:
        async_add_entities(entities, True)


class LoftieLampSceneSwitch(SwitchEntity):
    """A stateful switch that represents an active lamp scene."""

    def __init__(
        self,
        label: str,
        scene_name: str,
        command: str,
        client: LoftieClient,
        state,
    ) -> None:
        self._attr_name = f"Loftie {label}"
        self._attr_unique_id = f"loftie_lamp_scene_{scene_name}"
        self._attr_icon = "mdi:lamp"
        self._attr_should_poll = False
        self._scene_name = scene_name
        self._command = command
        self._client = client
        self._state = state

        # Register for state change notifications
        state.add_listener(self._on_state_changed)

    @callback
    def _on_state_changed(self) -> None:
        """Called when shared state is updated by another entity."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """On when the lamp is on AND this scene is the active one."""
        return self._state.is_on and self._state.active_scene == self._scene_name

    async def async_turn_on(self, **kwargs) -> None:
        """Activate this scene on the lamp."""
        try:
            if self._command == "mode":
                await self._client.set_mode(self._scene_name)
            else:
                await self._client.set_scene(self._scene_name)
        except Exception:
            _LOGGER.exception("Failed to activate scene %s", self._scene_name)
            return

        self._state.is_on = True
        self._state.active_scene = self._scene_name
        self._state.notify(source=self._on_state_changed)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the lamp off."""
        try:
            await self._client.turn_off()
        except Exception:
            _LOGGER.exception("Failed to turn off lamp")
            return
        self._state.is_on = False
        self._state.active_scene = None
        self._state.notify(source=self._on_state_changed)
        self.async_write_ha_state()
