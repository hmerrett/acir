"""Wifi association for the Pico W.

Kept separate from everything else so the IR side stays testable with no network
at all -- which matters, because the IR work is the part that needs iterating.
"""

import network
import time

import secrets

# Status codes the CYW43 driver reports, mapped to something readable.
_STATUS = {
    network.STAT_IDLE: "idle",
    network.STAT_CONNECTING: "connecting",
    network.STAT_WRONG_PASSWORD: "wrong password",
    network.STAT_NO_AP_FOUND: "no such network",
    network.STAT_CONNECT_FAIL: "connect failed",
    network.STAT_GOT_IP: "connected",
}


def connect(timeout_s=20, verbose=True):
    """Join the configured network. Returns the IP address, or None."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        if verbose:
            print("already connected:", ip)
        return ip

    if verbose:
        print("connecting to '{}'...".format(secrets.WIFI_SSID))
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)

    deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        status = wlan.status()
        if status == network.STAT_GOT_IP:
            ip = wlan.ifconfig()[0]
            if verbose:
                print("connected: {}  rssi {} dBm".format(ip, wlan.status("rssi")))
            return ip
        if status < 0:                      # negative codes are terminal failures
            if verbose:
                print("failed:", _STATUS.get(status, status))
            return None
        time.sleep_ms(250)

    if verbose:
        print("timed out after {}s (last status: {})".format(
            timeout_s, _STATUS.get(wlan.status(), wlan.status())))
    return None


def disconnect():
    wlan = network.WLAN(network.STA_IF)
    wlan.disconnect()
    wlan.active(False)
