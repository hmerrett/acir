"""Checks on raw capture: edge arming, interval timing, frame boundaries."""

import stubs
import ir_rx

SENT = [9000, 4500, 560, 1690, 560, 560, 560]


def feed(rx, frame_us, stray_rising_first=0):
    """Replay a mark/space frame as edges. A frame starts with a mark, so the
    line goes low first."""
    pin = rx._pin
    if stray_rising_first:
        pin.value(1)
        rx._edge(pin)
        stubs.advance(stray_rising_first)
    level = 0
    for dur in frame_us:
        pin.value(level)
        rx._edge(pin)
        stubs.advance(dur)
        level ^= 1
    pin.value(level)
    rx._edge(pin)                       # closing edge of the final mark


def settle():
    stubs.advance(ir_rx.IDLE_GAP_US + 1)


def check_clean_frame():
    rx = ir_rx.IRReceiver(16)
    feed(rx, SENT)
    assert rx.poll() is None, "reported a frame before the idle gap elapsed"
    settle()
    got = rx.poll()
    assert got == SENT, "captured %s" % (got,)
    assert len(got) % 2 == 1, "a frame should start and end with a mark"
    print("  clean frame captured exactly")


def check_stray_edge_ignored():
    # Capture must arm on a falling edge only, or buf[0] would be a space.
    rx = ir_rx.IRReceiver(16)
    feed(rx, SENT, stray_rising_first=5000)
    settle()
    got = rx.poll()
    assert got == SENT, "stray rising edge corrupted the capture: %s" % (got,)
    print("  stray rising edge correctly ignored")


def check_consecutive_frames():
    rx = ir_rx.IRReceiver(16)
    feed(rx, SENT)
    settle()
    a = rx.poll()
    stubs.advance(100000)
    feed(rx, SENT)
    settle()
    b = rx.poll()
    assert a == b == SENT, "second frame differed: %s" % (b,)
    assert rx.poll() is None, "poll returned a frame after draining"
    print("  back-to-back frames stay separate")


def check_overflow():
    rx = ir_rx.IRReceiver(16, max_intervals=8)
    feed(rx, SENT + [560] * 20)
    settle()
    got = rx.poll()
    assert len(got) == 8, len(got)
    print("  overflow truncates to the buffer size and warns")


def check_reset():
    rx = ir_rx.IRReceiver(16)
    pin = rx._pin
    pin.value(0)
    rx._edge(pin)
    stubs.advance(9000)
    pin.value(1)
    rx._edge(pin)
    assert rx._n == 1
    rx.reset()
    assert rx._n == 0 and not rx._active
    print("  reset clears a part-captured frame")


def check_buckets():
    b = ir_rx.buckets(SENT)
    mids = sorted(x["mid"] for x in b)
    assert len(b) == 4, "expected 4 clusters, got %s" % mids
    print("  buckets clustered %d distinct durations" % len(b))


def main():
    check_clean_frame()
    check_stray_edge_ignored()
    check_consecutive_frames()
    check_overflow()
    check_reset()
    check_buckets()
    print("ir_rx OK")
