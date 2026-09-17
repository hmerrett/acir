"""Raw IR capture from a demodulating receiver (TSOP38238 / VS1838B class).

The receiver has already stripped the 38 kHz carrier and given us clean logic
levels, so capture is just a matter of timing the gaps between edges. Its output
is active low: idle high, mark low.

Nothing here decodes a protocol. Air conditioners send their entire state in
every frame -- typically 100+ bits with a checksum -- and which dialect this
particular unit speaks is exactly what we are trying to find out. So we record
raw durations and work it out from the data.
"""

import machine
import time
from array import array

from machine import Pin

# A space longer than this means the frame has ended. AC frames contain internal
# gaps of up to ~20 ms between sections, so this needs headroom above that.
IDLE_GAP_US = 30000

# Long AC frames run to a few hundred intervals. 1024 is comfortable headroom.
MAX_INTERVALS = 1024


class IRReceiver:
    """Captures raw mark/space timings.

    Frames come out as a list of microsecond durations, alternating
    mark, space, ... always starting and ending with a mark.
    """

    def __init__(self, pin, max_intervals=MAX_INTERVALS, idle_gap_us=IDLE_GAP_US):
        self._buf = array("i", (0,) * max_intervals)
        self._max = max_intervals
        self._idle_gap = idle_gap_us
        self._n = 0
        self._last = 0
        self._active = False
        self._overflow = False

        self._pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self._pin.irq(
            trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
            handler=self._edge,
        )

    def _edge(self, pin):
        # Runs in interrupt context: no allocation, no method calls that might.
        now = time.ticks_us()

        if not self._active:
            # Only arm on a falling edge, so buf[0] is always a mark.
            if pin.value():
                return
            self._active = True
            self._last = now
            return

        n = self._n
        if n < self._max:
            self._buf[n] = time.ticks_diff(now, self._last)
            self._n = n + 1
        else:
            self._overflow = True
        self._last = now

    def poll(self):
        """Return a completed frame, or None if nothing is ready yet.

        A frame is considered complete once the line has been idle for
        idle_gap_us.
        """
        if not self._active or self._n == 0:
            return None
        if time.ticks_diff(time.ticks_us(), self._last) < self._idle_gap:
            return None

        # Brief, and only while no frame is arriving. Long enough that it would
        # be worth revisiting if this ever has to run alongside wifi.
        state = machine.disable_irq()
        try:
            n = self._n
            overflowed = self._overflow
            frame = [self._buf[i] for i in range(n)]
            self._n = 0
            self._active = False
            self._overflow = False
        finally:
            machine.enable_irq(state)

        if overflowed:
            print("! frame exceeded {} intervals and was truncated".format(self._max))
        return frame

    def line_idle(self):
        """True when the receiver output is in its idle (high) state."""
        return bool(self._pin.value())

    def reset(self):
        """Discard any partially captured frame."""
        state = machine.disable_irq()
        self._n = 0
        self._active = False
        self._overflow = False
        machine.enable_irq(state)

    def wait(self, timeout_ms=None):
        """Block until a frame arrives. Returns None on timeout."""
        start = time.ticks_ms()
        while True:
            frame = self.poll()
            if frame is not None:
                return frame
            if timeout_ms is not None:
                if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                    return None
            time.sleep_ms(5)

    def deinit(self):
        self._pin.irq(handler=None)


def buckets(values, tolerance=0.2):
    """Cluster durations that are within `tolerance` of one another.

    The fastest way to recognise a protocol by eye. A well behaved frame
    collapses to a handful of clusters: one long header mark, one header space,
    one bit mark, and two bit spaces (zero and one).
    """
    out = []
    for v in sorted(values):
        for b in out:
            if abs(v - b["mid"]) <= tolerance * b["mid"]:
                b["count"] += 1
                b["lo"] = min(b["lo"], v)
                b["hi"] = max(b["hi"], v)
                break
        else:
            out.append({"mid": v, "count": 1, "lo": v, "hi": v})
    return out


def summarise(frame):
    """Print a human readable breakdown of a captured frame."""
    marks = frame[0::2]
    spaces = frame[1::2]
    total = sum(frame)

    print("intervals : {}  ({} marks, {} spaces)".format(len(frame), len(marks), len(spaces)))
    print("duration  : {:.1f} ms".format(total / 1000))
    print("leader    : mark {} us, space {} us".format(
        frame[0], frame[1] if len(frame) > 1 else 0))

    for name, values in (("mark", marks), ("space", spaces)):
        print("\n{} clusters:".format(name))
        for b in buckets(values):
            print("  {:>6}-{:<6} us   x{}".format(b["lo"], b["hi"], b["count"]))
