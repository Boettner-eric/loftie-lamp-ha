"""Light platform for Loftie Lamp."""

import asyncio
import logging
import math

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
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
    """Set up the Loftie Lamp light platform from YAML."""
    data = hass.data.get(DOMAIN, {})
    conf = data.get("config", {})
    state = data["state"]
    client: LoftieClient = data["client"]
    name = conf.get("name", "Loftie Lamp")

    scenes = client.get_scene_names()

    async_add_entities([LoftieLampLight(name, client, scenes, state)], True)


class LoftieLampLight(LightEntity):
    """Representation of a Loftie Lamp."""

    def __init__(
        self,
        name: str,
        client: LoftieClient,
        scenes: list[str],
        state,
    ) -> None:
        self._attr_name = name
        self._attr_unique_id = "loftie_lamp_light"
        self._attr_should_poll = False
        self._client = client
        self._state = state

        # Build effects list: firmware modes + scenes
        self._effects = []
        for mode_key, label in MODE_LABELS.items():
            self._effects.append(label)
        for scene_name in sorted(scenes, key=lambda n: SCENE_LABELS.get(n, n)):
            label = SCENE_LABELS.get(scene_name, scene_name)
            self._effects.append(label)

        # Reverse lookup: label -> (command, name)
        self._effect_commands = {}
        for mode_key, label in MODE_LABELS.items():
            self._effect_commands[label] = ("mode", mode_key)
        for scene_name in scenes:
            label = SCENE_LABELS.get(scene_name, scene_name)
            self._effect_commands[label] = ("scene", scene_name)

        # Reverse lookup: scene key -> label
        self._scene_to_label = {}
        for mode_key, label in MODE_LABELS.items():
            self._scene_to_label[mode_key] = label
        for scene_name in scenes:
            self._scene_to_label[scene_name] = SCENE_LABELS.get(scene_name, scene_name)

        # Debounce for color updates
        self._color_pending = False
        self._color_task: asyncio.Task | None = None

        # Register for state change notifications from other entities
        state.add_listener(self._on_state_changed)

    @callback
    def _on_state_changed(self) -> None:
        """Called when shared state is updated by another entity (e.g. scene switch)."""
        self.async_write_ha_state()

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        return {ColorMode.HS}

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.HS

    @property
    def supported_features(self) -> LightEntityFeature:
        return LightEntityFeature.EFFECT

    @property
    def is_on(self) -> bool:
        return self._state.is_on

    @property
    def brightness(self) -> int:
        return self._state.brightness

    @property
    def hs_color(self) -> tuple[float, float]:
        return self._state.hs_color

    @property
    def effect(self) -> str | None:
        scene = self._state.active_scene
        if scene is None:
            return None
        return self._scene_to_label.get(scene)

    @property
    def effect_list(self) -> list[str]:
        return self._effects

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the lamp on, optionally setting brightness, color, or effect."""
        try:
            if ATTR_EFFECT in kwargs:
                effect = kwargs[ATTR_EFFECT]
                cmd_info = self._effect_commands.get(effect)
                if cmd_info:
                    command, name = cmd_info
                    if command == "mode":
                        await self._client.set_mode(name)
                    else:
                        await self._client.set_scene(name)
                    self._state.is_on = True
                    self._state.active_scene = name
                    self._state.notify(source=self._on_state_changed)
                    self.async_write_ha_state()
                    return

            if ATTR_BRIGHTNESS in kwargs:
                self._state.brightness = kwargs[ATTR_BRIGHTNESS]
                level = max(1, min(5, math.ceil(self._state.brightness / 51)))
                await self._client.set_brightness(level)

            if ATTR_HS_COLOR in kwargs:
                self._state.hs_color = kwargs[ATTR_HS_COLOR]
                self._state.active_scene = None
                self._color_pending = True
                if self._color_task is None or self._color_task.done():
                    self._color_task = asyncio.create_task(self._debounced_color())

            if ATTR_BRIGHTNESS not in kwargs and ATTR_HS_COLOR not in kwargs and ATTR_EFFECT not in kwargs:
                await self._client.turn_on()

            self._state.is_on = True
            self._state.notify(source=self._on_state_changed)
            self.async_write_ha_state()
        except Exception:
            _LOGGER.exception("Failed to turn on lamp")

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

    async def _debounced_color(self) -> None:
        """Wait briefly then send the color update."""
        await asyncio.sleep(0.3)
        if not self._color_pending:
            return
        self._color_pending = False

        h, s = self._state.hs_color
        r, g, b = _hsv_to_rgb100(h, s, 100)
        await self._client.set_color(r, g, b)
        # Notify after color is sent (scene cleared)
        self._state.notify(source=self._on_state_changed)


def _hsv_to_rgb100(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Convert HSV (h: 0-360, s: 0-100, v: 0-100) to RGB (0-100 each)."""
    h_norm = h / 360.0
    s_norm = s / 100.0
    v_norm = v / 100.0

    if s_norm == 0:
        val = round(v_norm * 100)
        return val, val, val

    i = int(h_norm * 6)
    f = h_norm * 6 - i
    p = v_norm * (1 - s_norm)
    q = v_norm * (1 - s_norm * f)
    t = v_norm * (1 - s_norm * (1 - f))

    i %= 6
    if i == 0:
        r, g, b = v_norm, t, p
    elif i == 1:
        r, g, b = q, v_norm, p
    elif i == 2:
        r, g, b = p, v_norm, t
    elif i == 3:
        r, g, b = p, q, v_norm
    elif i == 4:
        r, g, b = t, p, v_norm
    else:
        r, g, b = v_norm, p, q

    return round(r * 100), round(g * 100), round(b * 100)
