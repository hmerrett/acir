# Home Assistant and HomeBridge

The Pico publishes MQTT. Home Assistant picks it up by discovery; HomeBridge
reads the same topics via `homebridge-mqttthing`. Neither depends on the other.

```
  Pico W ──IR──> AC
     │
     └──MQTT──> broker ──┬──> Home Assistant   climate entity
                         └──> HomeBridge       heaterCooler
```

## Broker

Any MQTT broker. On Home Assistant OS: Settings → Add-ons → Mosquitto broker →
Install → Start, then accept the MQTT integration when it offers itself.

## Pico

Put the broker details in `src/secrets.py`:

```python
MQTT_HOST = "192.168.1.10"
MQTT_PORT = 1883
MQTT_USER = None
MQTT_PASSWORD = None
MQTT_DISCOVERY_PREFIX = "homeassistant"
```

```
mpremote connect auto fs cp src/*.py :
mpremote connect auto reset
```

The climate entity appears by itself. Discovery is published retained, so HA
recreates it after a restart without the Pico being awake.

## Topics

| Topic | Direction | Payload |
|---|---|---|
| `acir/costway/availability` | Pico → | `online` / `offline` (last will) |
| `acir/costway/state` | Pico → | JSON: mode, temperature, fan_mode, swing_mode, preset_mode |
| `acir/costway/set/mode` | → Pico | `off` `cool` `heat` `dry` `fan_only` `auto` |
| `acir/costway/set/temperature` | → Pico | 16–31 |
| `acir/costway/set/fan_mode` | → Pico | `auto` `min` `low` `med` `high` |
| `acir/costway/set/swing_mode` | → Pico | `off` `vertical` |
| `acir/costway/set/preset_mode` | → Pico | `none` `eco` `boost` |

```
mosquitto_sub -h <broker> -t 'acir/#' -v
```

## Two things that fail silently

Both produce no entity and no log entry:

- **Wrong discovery prefix.** Usually `homeassistant`, but it is configurable
  (Settings → Devices & Services → MQTT → Configure). A mismatch is ignored.
- **`"none"` in `preset_modes`.** Reserved — Home Assistant adds it implicitly
  and rejects any payload that lists it explicitly, invalidating the whole
  discovery message rather than just that field.

## HomeBridge

```
npm install -g homebridge-mqttthing
```

Add `homebridge-mqttthing.json` to `config.json` under `accessories`, setting
`url` to your broker.

HomeKit's `HeaterCooler` requires a current temperature and there is no sensor,
so the config reports the target temperature as current. If that matters, point
`getCurrentTemperature` at a real sensor's topic instead.

New accessories do not reach an already-paired bridge until it reloads.

## One-way control

Nothing reports back from the AC. State published is what was last sent; the
physical remote will desync it until the next command. Fixable with an IR
receiver watching for the remote's frames — `ir_rx.py` and `capture.py` already
do the decoding.
