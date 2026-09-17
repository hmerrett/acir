"""MQTT bridge: presents the air conditioner to Home Assistant and HomeBridge.

Publishes a Home Assistant MQTT Discovery config so the climate entity appears
by itself, then listens for commands and mirrors state back. HomeBridge can use
the same topics via homebridge-mqttthing.

    >>> import mqtt_bridge
    >>> mqtt_bridge.run()

IR is one-way, so the state published here is what we last *sent*, not what the
unit is necessarily doing. If someone uses the physical remote it will drift --
unavoidable without a receiver watching the remote.
"""

import json
import time

import machine
import network

import ac
import secrets
import wifi
from umqtt.simple import MQTTClient

BASE = "acir/costway"
TOPIC_AVAILABILITY = BASE + "/availability"
TOPIC_STATE = BASE + "/state"
TOPIC_CMD = BASE + "/set/"
TOPIC_CMD_WILD = TOPIC_CMD + "#"

# Home Assistant's climate modes are fixed; ours differ slightly.
HA_TO_MODE = {"cool": "cool", "heat": "heat", "dry": "dry",
              "fan_only": "fan", "auto": "auto"}
MODE_TO_HA = {v: k for k, v in HA_TO_MODE.items()}

FAN_MODES = ["auto", "min", "low", "med", "high"]
SWING_MODES = ["off", "vertical"]
# "none" is reserved: Home Assistant adds it implicitly and rejects a discovery
# payload that lists it explicitly -- silently, with nothing logged. It is still
# a valid *state* value, meaning no preset is active.
PRESET_MODES = ["eco", "boost"]

_client = None
_uid = None


def _unique_id():
    global _uid
    if _uid is None:
        mac = network.WLAN(network.STA_IF).config("mac")
        _uid = "costway_ac_" + "".join("%02x" % b for b in mac[3:])
    return _uid


def _discovery_payload():
    uid = _unique_id()
    return {
        "name": None,                       # use the device name
        "unique_id": uid,
        "object_id": "costway_ac",
        "device": {
            "identifiers": [uid],
            "name": "CostWay Air Conditioner",
            "manufacturer": "CostWay",
            "model": "TCL112 IR",
            "sw_version": "acir",
        },
        "availability_topic": TOPIC_AVAILABILITY,
        "payload_available": "online",
        "payload_not_available": "offline",

        "modes": ["off"] + sorted(HA_TO_MODE),
        "mode_command_topic": TOPIC_CMD + "mode",
        "mode_state_topic": TOPIC_STATE,
        "mode_state_template": "{{ value_json.mode }}",

        "min_temp": 16,
        "max_temp": 31,
        "temp_step": 1,
        "temperature_unit": "C",
        "temperature_command_topic": TOPIC_CMD + "temperature",
        "temperature_state_topic": TOPIC_STATE,
        "temperature_state_template": "{{ value_json.temperature }}",

        "fan_modes": FAN_MODES,
        "fan_mode_command_topic": TOPIC_CMD + "fan_mode",
        "fan_mode_state_topic": TOPIC_STATE,
        "fan_mode_state_template": "{{ value_json.fan_mode }}",

        "swing_modes": SWING_MODES,
        "swing_mode_command_topic": TOPIC_CMD + "swing_mode",
        "swing_mode_state_topic": TOPIC_STATE,
        "swing_mode_state_template": "{{ value_json.swing_mode }}",

        "preset_modes": PRESET_MODES,
        "preset_mode_command_topic": TOPIC_CMD + "preset_mode",
        "preset_mode_state_topic": TOPIC_STATE,
        "preset_mode_value_template": "{{ value_json.preset_mode }}",

        "optimistic": False,
        "retain": False,
    }


def _state_payload():
    s = ac.state()
    preset = "none"
    if s["econo"]:
        preset = "eco"
    elif s["turbo"]:
        preset = "boost"
    return {
        "mode": MODE_TO_HA.get(s["mode"], "cool") if s["power"] else "off",
        "temperature": s["temp"],
        "fan_mode": s["fan"],
        "swing_mode": "vertical" if s["swing"] else "off",
        "preset_mode": preset,
    }


def publish_state():
    if _client is None:
        return
    payload = json.dumps(_state_payload())
    _client.publish(TOPIC_STATE, payload.encode(), retain=True)
    print("  state ->", payload)


def _handle(topic, value):
    """Apply one command. Returns True if anything was transmitted."""
    key = topic.split("/")[-1]

    if key == "mode":
        if value == "off":
            ac.off()
        else:
            mode = HA_TO_MODE.get(value)
            if mode is None:
                print("  unknown mode:", value)
                return False
            ac.on(mode=mode)
        return True

    if key == "temperature":
        try:
            temp = int(float(value))
        except ValueError:
            print("  bad temperature:", value)
            return False
        ac.set(temp=temp)
        return True

    if key == "fan_mode":
        if value not in FAN_MODES:
            print("  unknown fan mode:", value)
            return False
        ac.set(fan=value)
        return True

    if key == "swing_mode":
        ac.set(swing=(value == "vertical"))
        return True

    if key == "preset_mode":
        ac.set(econo=(value == "eco"), turbo=(value == "boost"))
        return True

    print("  unhandled topic:", topic)
    return False


def _on_message(topic_b, payload_b):
    topic = topic_b.decode()
    value = payload_b.decode()
    print("cmd:", topic, "=", value)
    try:
        if _handle(topic, value):
            publish_state()
    except Exception as e:
        print("  command failed:", e)


def connect():
    global _client
    if not secrets.MQTT_HOST:
        raise SystemExit("set MQTT_HOST in secrets.py first")

    client = MQTTClient(
        client_id=_unique_id(),
        server=secrets.MQTT_HOST,
        port=secrets.MQTT_PORT or 1883,
        user=secrets.MQTT_USER,
        password=secrets.MQTT_PASSWORD,
        keepalive=60,
    )
    client.set_callback(_on_message)
    # Announce ourselves offline if we drop, so HA greys the entity out rather
    # than showing stale values.
    client.set_last_will(TOPIC_AVAILABILITY, b"offline", retain=True)
    client.connect()
    _client = client

    uid = _unique_id()
    prefix = getattr(secrets, "MQTT_DISCOVERY_PREFIX", "homeassistant")
    client.publish("{}/climate/{}/config".format(prefix, uid),
                   json.dumps(_discovery_payload()).encode(), retain=True)
    client.publish(TOPIC_AVAILABILITY, b"online", retain=True)
    client.subscribe(TOPIC_CMD_WILD.encode())
    print("MQTT connected to {} as {}".format(secrets.MQTT_HOST, uid))
    print("  discovery -> {}/climate/{}/config".format(prefix, uid))
    print("  commands  <- {}".format(TOPIC_CMD_WILD))
    publish_state()
    return client


def run(reconnect_delay_s=5):
    """Connect and service messages forever."""
    if not wifi.connect():
        raise SystemExit("no wifi")

    while True:
        try:
            connect()
            last_ping = time.ticks_ms()
            while True:
                _client.check_msg()
                if time.ticks_diff(time.ticks_ms(), last_ping) > 30000:
                    _client.ping()
                    last_ping = time.ticks_ms()
                time.sleep_ms(100)
        except Exception as e:
            print("MQTT error:", e)
            try:
                _client.disconnect()
            except Exception:
                pass
            print("  reconnecting in {}s".format(reconnect_delay_s))
            time.sleep(reconnect_delay_s)
