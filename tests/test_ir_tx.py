"""Checks on the PIO encoding: carrier accuracy, rounding, mark/space phasing."""

import stubs
import ir_tx

CARRIER = 38000
PERIOD_US = 1e6 / CARRIER


def check_carrier_accuracy():
    print("carrier period      : %.4f us" % PERIOD_US)
    print("state machine clock : %d Hz" % (CARRIER * ir_tx.CYCLES_PER_PERIOD))
    target = CARRIER * ir_tx.CYCLES_PER_PERIOD
    for sysclk, name in ((125e6, "RP2040 @125MHz"), (150e6, "RP2350 @150MHz")):
        raw = sysclk / target
        quantised = round(raw * 256) / 256      # clkdiv is 16.8 fixed point
        actual = sysclk / quantised / ir_tx.CYCLES_PER_PERIOD
        err = abs(actual - CARRIER) / CARRIER * 100
        print("  %-16s divider %.4f -> %.4f, carrier %.1f Hz (%.3f%% error)"
              % (name, raw, quantised, actual, err))
        assert err < 1.0, "%s carrier is %.2f%% off" % (name, err)


def check_encoding():
    tx = ir_tx.IRTransmitter(15)

    # An odd-length frame gets padded, so the state machine always finishes
    # waiting at the start of a mark.
    frame = [9000, 4500, 560, 1690, 560, 560, 560]
    counts, tail = tx._encode(frame)
    assert len(counts) % 2 == 0, "frame must be an even number of intervals"
    assert len(counts) == len(frame) + 1

    # counts hold (periods - 1); the PIO runs its loop body (x + 1) times.
    replayed = [round((c + 1) * PERIOD_US) for c in counts]
    errs = [abs(replayed[i] - frame[i]) / frame[i] * 100 for i in range(len(frame))]
    print("  rounding error max %.2f%% (receivers tolerate ~20%%)" % max(errs))
    assert max(errs) < 3, "rounding error too large: %.2f%%" % max(errs)

    # An even-length frame is left alone.
    counts2, tail2 = tx._encode([9000, 4500, 560, 1690])
    assert len(counts2) == 4
    assert tail2 == 1690

    # Nothing may encode to a zero-length interval; the PIO cannot emit one.
    counts3, _ = tx._encode([10, 10])
    assert all(c >= 0 for c in counts3)
    assert list(counts3) == [0, 0], list(counts3)

    # Order into the FIFO must be preserved.
    tx._sm.written = []
    tx.send([9000, 4500, 560])
    assert len(tx._sm.written) == 4, tx._sm.written
    assert tx._sm.written[0] == counts[0]


def check_repeat():
    tx = ir_tx.IRTransmitter(15)
    tx._sm.written = []
    tx.send([9000, 4500], repeat=3)
    assert len(tx._sm.written) == 6, tx._sm.written
    print("  repeat=3 wrote %d words" % len(tx._sm.written))


def main():
    check_carrier_accuracy()
    check_encoding()
    check_repeat()
    print("ir_tx OK")
