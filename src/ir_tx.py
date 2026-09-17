"""38 kHz IR transmitter for the RP2040/RP2350, driven by a PIO state machine.

Bit-banging a 38 kHz carrier from MicroPython is hopeless -- the jitter is worse
than the pulse widths. PIO does it exactly, and once started it needs nothing
from the CPU except a stream of interval lengths.

The state machine consumes those intervals in pairs, alternating:

    mark   carrier gated on at ~33% duty
    space  output held low

Lengths are counted in whole carrier periods (26.3 us at 38 kHz) rather than
microseconds, so one loop iteration is exactly one period and the state machine
never has to divide. The rounding error that introduces is ~1% on a typical
560 us pulse, against the +/-20% a receiver will tolerate.
"""

import gc
import time
from array import array

import rp2
from machine import Pin

CARRIER_HZ = 38000

# Both loops below are written to take exactly 30 state machine cycles, so the
# state machine has to be clocked at 30x the carrier frequency.
CYCLES_PER_PERIOD = 30

# Appended when a frame has an odd number of intervals, so that a frame always
# leaves the state machine waiting at the start of a mark.
PAD_SPACE_US = 2000


@rp2.asm_pio(set_init=rp2.PIO.OUT_LOW, fifo_join=rp2.PIO.JOIN_TX)
def _carrier_burst():
    wrap_target()

    # ---- mark: gate the carrier on for (x + 1) carrier periods -----------
    pull(block)
    mov(x, osr)
    label("mark")
    set(pins, 1)            [9]     # 10 cycles on  -> 33% duty
    set(pins, 0)            [18]    # 19 cycles off
    jmp(x_dec, "mark")              #  1 cycle      -> 30 total

    # ---- space: hold the output low for (x + 1) carrier periods ----------
    pull(block)
    mov(x, osr)
    label("space")
    nop()                   [28]    # 29 cycles
    jmp(x_dec, "space")             #  1 cycle      -> 30 total

    wrap()


class IRTransmitter:
    """Plays raw mark/space timings out of an IR LED.

    Deliberately knows nothing about protocols. Whatever the AC speaks, it
    arrives here as a list of microsecond durations.
    """

    def __init__(self, pin, sm_id=0, carrier_hz=CARRIER_HZ):
        self._period_us = 1000000.0 / carrier_hz
        self._sm = rp2.StateMachine(
            sm_id,
            _carrier_burst,
            freq=carrier_hz * CYCLES_PER_PERIOD,
            set_base=Pin(pin, Pin.OUT, value=0),
        )
        self._sm.active(1)

    def _encode(self, timings_us):
        """Convert microseconds to (carrier periods - 1), as the PIO wants them."""
        n = len(timings_us)
        if n == 0:
            raise ValueError("empty frame")

        padded = n + 1 if n % 2 else n
        counts = array("I", (0,) * padded)

        for i in range(n):
            periods = int(timings_us[i] / self._period_us + 0.5)
            if periods < 1:
                periods = 1          # the PIO cannot emit a zero-length interval
            counts[i] = periods - 1

        tail_us = timings_us[-1]
        if padded != n:
            counts[padded - 1] = int(PAD_SPACE_US / self._period_us) - 1
            tail_us += PAD_SPACE_US

        return counts, int(tail_us)

    def send(self, timings_us, repeat=1, gap_us=40000):
        """Transmit a frame.

        timings_us  alternating mark, space, ... starting with a mark
        repeat      how many times to send the frame
        gap_us      quiet time between repeats
        """
        counts, tail_us = self._encode(timings_us)

        # Take the garbage collection hit now rather than halfway through a
        # frame. The loop below allocates nothing, so nothing should trigger a
        # collection while the state machine is being fed.
        gc.collect()

        sm = self._sm
        for r in range(repeat):
            for c in counts:
                sm.put(c)                    # blocks while the FIFO is full
            while sm.tx_fifo():
                pass
            # The FIFO is drained but the state machine is still playing out
            # the interval it already pulled.
            time.sleep_us(tail_us + 200)
            if r + 1 < repeat:
                time.sleep_us(gap_us)

    def deinit(self):
        self._sm.active(0)
