"""Interactive capture tool: learn the air conditioner's remote.

Typical session over the REPL:

    >>> import capture
    >>> capture.run()

Point the original remote at the receiver from ~30 cm, set it to the state you
want, and press a button. Each frame is summarised and appended to captures.json
on the Pico's flash.

Capture the same button two or three times. Air conditioner remotes are stateful
-- every frame carries the whole machine configuration plus a checksum -- so two
presses of "temperature up" produce different frames. Two presses of the same
*resulting state* should produce identical ones, and that is the check that tells
you the capture is sound.
"""

import json
import time

import config
import ir_rx
from ir_rx import IRReceiver

# Two intervals this close are the same symbol as far as the protocol cares.
MATCH_TOLERANCE = 0.25


def load(path=None):
    path = path or config.CAPTURE_FILE
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(label, frame, path=None):
    path = path or config.CAPTURE_FILE
    data = load(path)
    data.setdefault(label, []).append(frame)
    with open(path, "w") as f:
        json.dump(data, f)
    return len(data[label])


def frames_match(a, b, tolerance=MATCH_TOLERANCE):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if abs(x - y) > tolerance * max(x, y):
            return False
    return True


def compare(a, b, tolerance=MATCH_TOLERANCE):
    """Show where two frames diverge.

    The useful move once you have several captures: take "cool 20" and
    "cool 21" and see which intervals changed. Those are the temperature bits,
    and the ones that always change alongside them are the checksum.
    """
    if len(a) != len(b):
        print("different lengths: {} vs {}".format(len(a), len(b)))
        return

    diffs = 0
    for i, (x, y) in enumerate(zip(a, b)):
        if abs(x - y) > tolerance * max(x, y):
            kind = "mark " if i % 2 == 0 else "space"
            print("  [{:>3}] {} {:>6} -> {:>6}".format(i, kind, x, y))
            diffs += 1

    if diffs == 0:
        print("  identical")
    else:
        print("  {} of {} intervals differ".format(diffs, len(a)))


def run(path=None):
    rx = IRReceiver(config.IR_RX_PIN)
    print("Ready. Point the remote at the receiver from about 30 cm.")
    print("Label each capture with the resulting state, e.g. 'cool_20_fan_high'.")
    print("Blank label to quit.\n")

    try:
        while True:
            label = input("label> ").strip()
            if not label:
                break

            rx.reset()                     # discard anything already buffered
            print("  waiting for a press...")
            frame = rx.wait(timeout_ms=30000)
            if frame is None:
                print("  timed out, nothing received\n")
                continue

            print()
            ir_rx.summarise(frame)

            previous = load(path).get(label, [])
            n = save(label, frame, path)
            print("\n  saved as '{}' capture #{}".format(label, n))

            if previous:
                if frames_match(previous[-1], frame):
                    print("  matches the previous capture of this label -- good")
                else:
                    print("  DIFFERS from the previous capture of this label:")
                    compare(previous[-1], frame)
            print()
    finally:
        rx.deinit()

    data = load(path)
    print("\n{} label(s) captured: {}".format(len(data), ", ".join(data.keys())))


def dump(path=None):
    """Print every stored capture as Python lists, ready to paste elsewhere."""
    for label, frames in load(path).items():
        for i, frame in enumerate(frames):
            print("# {} #{} -- {} intervals".format(label, i + 1, len(frame)))
            print("{} = {}\n".format(label.upper(), frame))


if __name__ == "__main__":
    run()
