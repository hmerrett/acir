"""Hardware checks for the IR front end.

Two modes, because the transmit and receive halves can be verified separately:

    beacon()    transmit only. Needs no receiver -- you confirm it with a phone
                camera. Most phone front cameras have no IR cut filter, so the
                LED shows up as a visible flashing purple-white dot.

    loopback()  transmit and receive. Needs a working IR receiver on IR_RX_PIN.

Run beacon() first. It isolates wiring faults from protocol work, which is much
harder to debug if you are not certain the LED is actually emitting.
"""

import time

import config
from ir_tx import IRTransmitter

# A recognisable NEC-shaped frame: long header, then alternating short and long
# spaces so a mangled capture is obvious at a glance.
TEST_FRAME = [9000, 4500]
for _bit in range(8):
    TEST_FRAME += [560, 1690, 560, 560]
TEST_FRAME += [560]

# Slow, high duty flashing -- nothing like a real protocol, but unmistakable
# through a phone camera.
BEACON_FRAME = [100000, 100000]


def beacon(seconds=15):
    """Flash the IR LED slowly so it can be seen through a phone camera.

    Point a phone's FRONT camera at the LED from a few centimetres. Rear cameras
    on most modern phones filter IR out; front ones generally do not.
    """
    tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)
    cycles = int(seconds / 0.2)

    print("Flashing IR LED at 5 Hz for {} s.".format(seconds))
    print("Point a phone FRONT camera at the LED -- look for a flashing")
    print("purple-white dot. Nothing visible to the naked eye is expected.")
    try:
        for i in range(cycles):
            tx.send(BEACON_FRAME)
            if i % 25 == 0:
                print("  ... {} s left".format(int((cycles - i) * 0.2)))
    finally:
        tx.deinit()
    print("\nDone.")
    print("  Saw it flashing   -> transmit side is working")
    print("  Saw nothing       -> LED backwards? (anode, the long leg, goes to")
    print("                       the resistor). Transistor pinout? No 5 V on")
    print("                       VBUS unless powered over USB.")


def carrier_check(seconds=5):
    """Hold the carrier on continuously -- for checking with a scope or meter.

    A DC meter across the LED should read roughly a third of the forward drop,
    since the carrier is 33% duty.
    """
    tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)
    print("Carrier on solid for {} s...".format(seconds))
    try:
        # One very long mark: the PIO counts carrier periods in a 32 bit
        # register, so a multi-second burst is not a problem.
        tx.send([seconds * 1000000, 1000])
    finally:
        tx.deinit()
    print("Done.")


def loopback():
    """Transmit a frame and confirm the receiver hears it.

    Needs a working receiver on IR_RX_PIN. Aim the LED at it from 10-20 cm; at
    point blank the receiver's automatic gain control saturates.
    """
    from ir_rx import IRReceiver

    rx = IRReceiver(config.IR_RX_PIN)
    tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)

    print("=== receiver idle state ===")
    time.sleep_ms(200)
    if rx.line_idle():
        print("  OK   line idles high")
    else:
        print("  FAIL line is stuck low")
        print("       -> check the pinout (middle pin is GND), or move away")
        print("          from sunlight, CFLs and some LED bulbs")
        return False

    print("\n=== loopback ===")
    for attempt in range(1, 4):
        rx.reset()
        tx.send(TEST_FRAME)
        echo = rx.wait(timeout_ms=500)
        if echo is None:
            print("  attempt {}: nothing received".format(attempt))
            continue
        print("  attempt {}: {} intervals (sent {}), header {} / {}".format(
            attempt, len(echo), len(TEST_FRAME), echo[0],
            echo[1] if len(echo) > 1 else 0))
        if abs(echo[0] - TEST_FRAME[0]) < TEST_FRAME[0] * 0.25:
            print("\n  PASS transmit and receive both working")
            return True

    print("\n  FAIL no clean loopback")
    return False


def main():
    beacon()


if __name__ == "__main__":
    main()
