"""Runs on boot. Connects to wifi and serves MQTT until told otherwise."""

import time


def start():
    import mqtt_bridge
    mqtt_bridge.run()


if __name__ == "__main__":
    # A short pause makes it possible to interrupt with Ctrl-C and get a REPL
    # before the bridge takes over the board.
    print("acir starting in 3s -- Ctrl-C for a REPL")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        raise SystemExit("cancelled")
    start()
