"""Stubs for the MicroPython-only modules, so the firmware can be exercised
under CPython on a laptop.

The timing logic is the part most likely to be wrong and the most painful to
debug on hardware, so it is worth being able to test it without a Pico attached.
"""

import sys
import time
import types

CLOCK = {"us": 0}


def advance(us):
    CLOCK["us"] += us


def install():
    # --- machine ------------------------------------------------------------
    machine = types.ModuleType("machine")

    class Pin:
        OUT = IN = PULL_UP = 0
        IRQ_RISING = 1
        IRQ_FALLING = 2

        def __init__(self, *a, **k):
            self._v = 1
            self.handler = None

        def value(self, v=None):
            if v is None:
                return self._v
            self._v = v

        def irq(self, **k):
            self.handler = k.get("handler")

    machine.Pin = Pin
    machine.disable_irq = lambda: 0
    machine.enable_irq = lambda s: None
    sys.modules["machine"] = machine

    # --- rp2 ----------------------------------------------------------------
    rp2 = types.ModuleType("rp2")

    class PIO:
        OUT_LOW = 0
        JOIN_TX = 1

    class StateMachine:
        def __init__(self, *a, **k):
            self.written = []

        def active(self, v):
            pass

        def put(self, v):
            self.written.append(v)

        def tx_fifo(self):
            return 0

    rp2.PIO = PIO
    rp2.StateMachine = StateMachine
    rp2.asm_pio = lambda **kw: (lambda fn: fn)
    sys.modules["rp2"] = rp2

    # --- MicroPython time extensions ---------------------------------------
    time.sleep_us = lambda us: advance(us)
    time.sleep_ms = lambda ms: advance(ms * 1000)
    time.ticks_us = lambda: CLOCK["us"]
    time.ticks_ms = lambda: CLOCK["us"] // 1000
    time.ticks_diff = lambda a, b: a - b
