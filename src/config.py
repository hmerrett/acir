"""Hardware configuration.

GP23, GP24, GP25 and GP29 are wired to the wifi chip and power circuitry on the
Pico W / Pico 2 W -- do not use them.
"""

IR_TX_PIN = 15      # physical pin 20 -> 330R -> transistor base
IR_RX_PIN = 16      # physical pin 21 -> receiver OUT

CARRIER_HZ = 38000  # revisit only if capture shows the remote is 36 or 40 kHz

CAPTURE_FILE = "captures.json"
