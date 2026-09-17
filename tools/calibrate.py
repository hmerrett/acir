"""Calibrate the Broadlink tick against the Pico's known-good transmitter.

There is genuine disagreement in the wild about Broadlink's time unit -- 2^-15 s
(30.518 us) and 269/8192 ms (32.837 us) are both widely cited, and they differ by
7.6%. That is more than enough to misidentify a protocol.

We do not have to guess. The Pico transmits timings we have measured on hardware
to within 0.4%, so pointing it at the RM and learning its output gives a direct
reading of the tick.

    .venv/bin/python tools/calibrate.py

Point the Pico's IR LED at the RM Pro from ~20 cm first.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import rm_learn

# A frame with a wide spread of durations, so the fit is not dominated by one
# value. These are the exact microsecond figures the Pico is asked to send.
REFERENCE = [4692, 4416, 552, 1656, 552, 552, 1656, 1656, 552, 1656,
             552, 552, 1656, 552, 552, 1656, 552]


def pico_send(frame, repeat=3):
    """Ask the Pico to transmit the reference frame."""
    code = (
        "import config\n"
        "from ir_tx import IRTransmitter\n"
        "tx = IRTransmitter(config.IR_TX_PIN, carrier_hz=config.CARRIER_HZ)\n"
        "f = {}\n"
        "for _ in range({}):\n"
        "    tx.send(f)\n"
        "tx.deinit()\n"
        "print('sent')\n"
    ).format(frame, repeat)
    r = subprocess.run(["mpremote", "connect", "auto", "exec", code],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise SystemExit("Pico transmit failed:\n" + (r.stderr or r.stdout))
    return True


def main():
    dev = rm_learn.connect()

    print("Point the Pico's IR LED at the RM Pro (~20 cm), then press enter.")
    input()

    for attempt in range(1, 4):
        print("[attempt {}] arming RM, then transmitting from the Pico...".format(attempt))
        dev.enter_learning()
        time.sleep(0.5)
        pico_send(REFERENCE)

        packet = None
        for _ in range(20):
            time.sleep(0.5)
            try:
                packet = dev.check_data()
            except Exception:
                packet = None
            if packet:
                break

        if not packet:
            print("  nothing learned -- aim the LED straight at the RM and retry\n")
            continue

        # Decode in raw ticks, with no conversion applied.
        raw = rm_learn.decode_packet(packet, tick_us=1.0)
        print("  learned {} intervals (sent {})".format(len(raw), len(REFERENCE)))

        n = min(len(raw), len(REFERENCE))
        if n < 6:
            print("  too short to fit\n")
            continue

        # A demodulator turns its AGC on slightly early and holds it slightly
        # late, so marks come back long and spaces come back short by roughly a
        # constant. Fit both the tick and that bias:
        #     mark:  ticks * T = true + bias
        #     space: ticks * T = true - bias
        sum_m_ticks = sum_m_true = sum_s_ticks = sum_s_true = 0
        n_m = n_s = 0
        for i in range(n):
            if raw[i] <= 0:
                continue
            if i % 2 == 0:                      # even indices are marks
                sum_m_ticks += raw[i]; sum_m_true += REFERENCE[i]; n_m += 1
            else:
                sum_s_ticks += raw[i]; sum_s_true += REFERENCE[i]; n_s += 1

        if not (n_m and n_s):
            print("  need both marks and spaces to fit\n")
            continue

        tick = ((n_s * sum_m_true + n_m * sum_s_true) /
                float(n_m * sum_s_ticks + n_s * sum_m_ticks))
        bias = (sum_m_ticks * tick - sum_m_true) / float(n_m)

        print("\n  idx  kind   sent(us)  ticks   ticks*T   residual")
        for i in range(n):
            if raw[i] <= 0:
                continue
            kind = "mark " if i % 2 == 0 else "space"
            conv = raw[i] * tick
            expect = REFERENCE[i] + (bias if i % 2 == 0 else -bias)
            print("  {:>3}  {}  {:>8}  {:>5}  {:>8.1f}  {:>+8.1f}"
                  .format(i, kind, REFERENCE[i], raw[i], conv, conv - expect))

        print("\n  fitted tick : {:.4f} us".format(tick))
        print("  fitted bias : {:+.1f} us (marks long, spaces short)".format(bias))
        print()
        for name, value in (("2^-15 s", 30.5176), ("269/8192 ms", 32.8369)):
            err = abs(tick - value) / value * 100
            flag = "   <== this one" if err < 2 else ""
            print("  vs {:<14} {:.4f} us -> {:5.2f}% off{}".format(name, value, err, flag))

        print("\n  Put these in tools/rm_learn.py as TICK_US and DEMOD_BIAS_US.")
        return tick, bias

    print("calibration failed -- could not learn the Pico's output")
    return None


if __name__ == "__main__":
    main()
