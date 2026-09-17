"""Find out which IR dialect the air conditioner speaks.

With no IR receiver, the air conditioner itself is the instrument: it beeps and
its display changes when it accepts a frame. So we send known-good commands from
documented protocols and watch for a reaction.

    >>> import probe
    >>> probe.sweep()

Point the LED at the unit from a metre or two, roughly where you would hold the
remote. Each command is announced before it is sent, with a pause afterwards, so
a reaction can be attributed to a specific protocol.
"""

import time

import config
import protocols as p
from ir_tx import IRTransmitter


def _plan():
    """One highly visible command per protocol, then variations.

    A large temperature swing is the most visible single command: any state
    command other than an explicit "off" implicitly means "on", so an idle unit
    should wake up and jump to its minimum setpoint.
    """
    return [
        ("tcl112", "cool 17C fan high",
         lambda tx: p.tcl112_send(tx, p.tcl112_state("cool", 17, "high"))),
        ("tcl112", "cool 30C fan high",
         lambda tx: p.tcl112_send(tx, p.tcl112_state("cool", 30, "high"))),
        ("tcl112", "power off",
         lambda tx: p.tcl112_send(tx, p.tcl112_state("cool", 25, "auto", power=False))),

        ("coolix", "cool 17C fan max",
         lambda tx: p.coolix_send(tx, p.coolix_state("cool", 17, "max"))),
        ("coolix", "cool 30C fan max",
         lambda tx: p.coolix_send(tx, p.coolix_state("cool", 30, "max"))),
        ("coolix", "power off",
         lambda tx: p.coolix_send(tx, p.COOLIX_OFF)),

        ("gree", "cool 17C fan max",
         lambda tx: p.gree_send(tx, p.gree_state("cool", 17, "max"))),
        ("gree", "cool 30C fan max",
         lambda tx: p.gree_send(tx, p.gree_state("cool", 30, "max"))),
        ("gree", "power off",
         lambda tx: p.gree_send(tx, p.gree_state("auto", 25, "auto", power=False))),

        ("midea", "cool 17C fan max",
         lambda tx: p.midea_send(tx, p.midea_state("cool", 17, "max"))),
        ("midea", "cool 30C fan max",
         lambda tx: p.midea_send(tx, p.midea_state("cool", 30, "max"))),
        ("midea", "power off",
         lambda tx: p.midea_send(tx, p.midea_state("auto", 25, "auto", power=False))),
    ]


def sweep(pause_s=4, repeat=2):
    """Fire every candidate in turn, announcing each one.

    Watch the unit. If it beeps or the display changes, note which line was on
    screen at the time -- that is your protocol.
    """
    tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)
    plan = _plan()

    print("Sweeping {} commands across 3 protocols.".format(len(plan)))
    print("Point the LED at the unit. Watch for a beep or a display change.")
    print("Note the line number if anything happens.\n")

    try:
        for i, (proto, label, send) in enumerate(plan, 1):
            print("[{:>2}] {:<8} {}".format(i, proto, label))
            for _ in range(repeat):
                send(tx)
                time.sleep_ms(300)
            time.sleep(pause_s)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        tx.deinit()

    print("\n" + "=" * 54)
    print("Nothing? See the troubleshooting notes in the README.")
    print("Something? Note the line number and re-run just that protocol,")
    print("e.g. probe.coolix() / probe.gree() / probe.midea()")


def _one(sender, label, repeat=2):
    tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)
    try:
        print("sending:", label)
        for _ in range(repeat):
            sender(tx)
            time.sleep_ms(300)
    finally:
        tx.deinit()


def coolix(mode="cool", temp=17, fan="max", repeat=2):
    state = p.coolix_state(mode, temp, fan)
    _one(lambda tx: p.coolix_send(tx, state),
         "coolix {} {}C {} (0x{:06X})".format(mode, temp, fan, state), repeat)


def gree(mode="cool", temp=17, fan="max", power=True, repeat=2):
    state = p.gree_state(mode, temp, fan, power=power)
    _one(lambda tx: p.gree_send(tx, state),
         "gree {} {}C {} [{}]".format(mode, temp, fan,
                                      " ".join("%02X" % b for b in state)), repeat)


def midea(mode="cool", temp=17, fan="max", power=True, repeat=2):
    state = p.midea_state(mode, temp, fan, power=power)
    _one(lambda tx: p.midea_send(tx, state),
         "midea {} {}C {} (0x{:012X})".format(mode, temp, fan, state), repeat)


def off(protocol="coolix"):
    if protocol == "coolix":
        _one(lambda tx: p.coolix_send(tx, p.COOLIX_OFF), "coolix off")
    elif protocol == "gree":
        gree("auto", 25, "auto", power=False)
    elif protocol == "midea":
        midea("auto", 25, "auto", power=False)
    else:
        raise ValueError("unknown protocol: " + protocol)


def tcl112(mode="cool", temp=17, fan="high", power=True, repeat=1):
    state = p.tcl112_state(mode, temp, fan, power=power)
    _one(lambda tx: p.tcl112_send(tx, state),
         "tcl112 {} {}C {} [{}]".format(mode, temp, fan,
                                        " ".join("%02X" % b for b in state)), repeat)
