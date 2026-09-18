"""High level control of the CostWay air conditioner.

The unit speaks TCL112. That was established by capture rather than guesswork:
frames are 112 bits prefixed 23 CB 26, the checksums verify against the
documented algorithm, and byte 12 carries the isTcl flag.

    >>> import ac
    >>> ac.on(temp=20, fan='high')
    >>> ac.off()

Air conditioner remotes are stateful -- every frame carries the whole machine
configuration -- so this module keeps a copy of what it last sent and modifies
that, rather than pretending there are discrete "warmer"/"cooler" commands.
"""

import config
import protocols as p
from ir_tx import IRTransmitter

# What we believe the unit is currently set to. Seeded from the state captured
# from the real remote. It can drift if someone uses the physical remote, which
# is inherent to one-way IR control.
_state = {
    "power": False,
    "mode": "cool",
    "temp": 25,
    "fan": "low",
    "swing": False,
    "turbo": False,
    "econo": False,
}


def state():
    return dict(_state)


def _transmit(**changes):
    _state.update(changes)
    frame = p.tcl112_state(mode=_state["mode"], temp=_state["temp"],
                           fan=_state["fan"], power=_state["power"],
                           swing=_state["swing"], turbo=_state["turbo"],
                           econo=_state["econo"])
    tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)
    try:
        p.tcl112_send(tx, frame)
    finally:
        tx.deinit()
    flags = "".join(k[0].upper() for k in ("swing", "turbo", "econo") if _state[k])
    print("sent: power={} mode={} temp={}C fan={}{}  [{}]".format(
        "on" if _state["power"] else "off", _state["mode"], _state["temp"],
        _state["fan"], " " + flags if flags else "",
        " ".join("%02X" % b for b in frame)))
    return frame


FAN_SPEEDS = ("auto", "min", "low", "med", "high")
MODES = ("cool", "heat", "dry", "fan", "auto")


def on(temp=None, mode=None, fan=None, swing=None, turbo=None, econo=None):
    """Turn on, optionally changing settings at the same time."""
    return _apply({"power": True}, temp, mode, fan, swing, turbo, econo)


def _apply(changes, temp, mode, fan, swing, turbo, econo):
    for key, value in (("temp", temp), ("mode", mode), ("fan", fan),
                       ("swing", swing), ("turbo", turbo), ("econo", econo)):
        if value is not None:
            changes[key] = value
    return _transmit(**changes)


def off():
    return _transmit(power=False)


def set(temp=None, mode=None, fan=None, swing=None, turbo=None, econo=None):
    """Change settings without touching the power state."""
    if all(v is None for v in (temp, mode, fan, swing, turbo, econo)):
        raise ValueError("nothing to change")
    return _apply({}, temp, mode, fan, swing, turbo, econo)


def resend():
    """Retransmit the current state, for when a command was missed."""
    return _transmit()


def blast(seconds=30, interval_s=2):
    """Retransmit the current state repeatedly, for aiming at the unit.

    Toggles power each time so a working link is unmistakable: the AC should
    click on and off roughly every two seconds.
    """
    import time
    print("transmitting for {}s -- aim at the AC's IR window".format(seconds))
    for i in range(int(seconds / interval_s)):
        _transmit(power=(i % 2 == 0))
        time.sleep(interval_s)
    print("done")
