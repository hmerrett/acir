"""Copy to secrets.py and fill in. secrets.py is gitignored."""

WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-password"

# Filled in later, once the Home Assistant side exists.
MQTT_HOST = None
MQTT_PORT = 1883
MQTT_USER = None
MQTT_PASSWORD = None

# Home Assistant's MQTT discovery prefix. Usually "homeassistant", but it is
# configurable and a mismatch fails silently -- nothing appears, nothing logs.
MQTT_DISCOVERY_PREFIX = "homeassistant"
