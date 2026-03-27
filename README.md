# Loftie Lamp – Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Custom Home Assistant integration for the [Loftie Lamp](https://byloftie.com). Controls the lamp via its Firebase-backed cloud API — no external scripts or extra dependencies needed. Exposes a light entity (on/off, brightness, color picker, scenes) and optional scene switches for Apple Home.

## How it works

The integration communicates directly with the Loftie device gateway API using reverse-engineered endpoints from the Loftie app. It uses Firebase auth tokens to authenticate and sends lamp configuration (colors, modes, scenes) via the gateway. Scene presets (gradient LED patterns) were extracted from the decompiled Loftie app.

## Installation via HACS

1. In HACS, go to **Integrations** → three-dot menu → **Custom repositories**.
2. Paste this repo's URL, select category **Integration**, and click **Add**.
3. Find **Loftie Lamp** in the HACS store and click **Install**.
4. Restart Home Assistant.

## Configuration

You'll need your Firebase credentials and device ID. These can be obtained by intercepting the Loftie app's network traffic.

Add to `configuration.yaml`:

```yaml
loftie_lamp:
  firebase_api_key: "your-firebase-api-key"
  device_id: "your-loftie-device-id"
  gateway_url: "https://your-gateway-url"
  refresh_token: "your-firebase-refresh-token"
  name: "Loftie Lamp"      # optional
  scenes:                   # optional — each becomes a switch tile in Apple Home
    - bali
    - santaFe
    - budapest
    - night
    - day

light:
  - platform: loftie_lamp

switch:
  - platform: loftie_lamp
```

Restart Home Assistant after saving.

### Scene presets

To use named scenes (gradient presets from the Loftie app), place a `presets.json` file in the `custom_components/loftie_lamp/` directory. This file contains the LED color data for each scene.

## Entities

| Entity | Type | What it does |
|--------|------|--------------|
| `light.loftie_lamp` | Light | On/off, brightness (1-5), HS color picker, scene/mode effects |
| `switch.loftie_bali` | Switch | Activates the Bali scene |
| `switch.loftie_santa_fe` | Switch | Activates the Santa Fe scene |
| ... | | One switch per scene in your `scenes` list |

Scene switches are **stateful** — turning one on activates that scene and turns off the others. Turning a scene switch off turns the lamp off.

## Apple Home via HomeKit Bridge

1. In HA, go to **Settings → Devices & Services → Add Integration → HomeKit Bridge**.
2. Include `light.loftie_lamp` and your scene switches in the bridge.
3. The lamp appears in Apple Home with full color/brightness controls.
4. Scene switches appear as separate tiles you can tap or add to HomeKit scenes/automations.

## Available scene names

Firmware modes: `day`, `reading`, `night`

Scenes: `bali`, `joshuaTree`, `santorini`, `tulum`, `santaFe`, `dubai`, `frenchRiviera`, `tuscany`, `fiji`, `budapest`, `siemReap`, `maui`, `cappadocia`, `red`, `candle`, `blush`, `fog`, `canyon`, `ember`, `goldenHour`, `warmth`, `desert`, `overCast`, `mist`, `woodLand`, `vine`, `air`, `highNoon`, `coast`, `cloud`, `pride`, `american`, `speakNow`
