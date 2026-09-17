"""Learn IR codes using a Broadlink RM on the LAN, and identify the protocol.

This stands in for the IR receiver: the RM's learning mode captures the original
remote, and we convert its packet format into the same microsecond mark/space
timings the Pico transmits.

    .venv/bin/python tools/rm_learn.py            # learn one code
    .venv/bin/python tools/rm_learn.py --label cool_20 --repeat 2

Captures are appended to captures/remote.json.
"""

import argparse
import json
import os
import sys
import time

import broadlink

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

CAPTURE_FILE = os.path.join(ROOT, "captures", "remote.json")

# Broadlink counts in units of 2^-15 s. Both this and 269/8192 ms (32.84 us)
# are widely cited; they differ by 7.6%, which is enough to misidentify a
# protocol. Measured against the Pico's known-good transmitter by
# tools/calibrate.py: 30.4523 us, i.e. 0.21% from this value and 7.26% from the
# other. See the README.
TICK_US = 30.5176

# A demodulator turns its AGC on slightly early and holds it slightly late, so
# marks come back long and spaces come back short by roughly a constant.
# Measured at +14.9 us by the same calibration.
DEMOD_BIAS_US = 15


def decode_packet(packet, tick_us=None, correct_bias=True):
    """Broadlink IR packet -> list of microsecond durations (mark, space, ...).

    Pass tick_us=1.0 to get the raw tick counts instead, for calibration."""
    if tick_us is None:
        tick_us = TICK_US
    if packet[0] != 0x26:
        raise ValueError("not an IR packet (leading byte 0x%02X, RF codes are 0xB2)"
                         % packet[0])
    length = packet[2] | (packet[3] << 8)
    data = packet[4:4 + length]

    timings = []
    i = 0
    while i < len(data):
        value = data[i]
        i += 1
        if value == 0:                       # 0x00 escapes a 16 bit big-endian value
            if i + 1 >= len(data):
                break
            value = (data[i] << 8) | data[i + 1]
            i += 2
        timings.append(int(round(value * tick_us)))

    # The trailing 0x0d 0x05 terminator decodes as two implausibly short
    # intervals. Compare in microseconds regardless of the unit requested.
    floor_ticks = 250.0 / tick_us
    while len(timings) > 2 and timings[-1] < floor_ticks:
        timings.pop()

    if correct_bias and tick_us > 5:         # not in raw-tick mode
        timings = [t - DEMOD_BIAS_US if i % 2 == 0 else t + DEMOD_BIAS_US
                   for i, t in enumerate(timings)]
    return timings


def buckets(values, tolerance=0.2):
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


# Header signatures of the protocols we can already encode, plus a few common
# ones we cannot, so a miss is still informative.
SIGNATURES = [
    ("coolix", 4692, 4416, 100),
    ("gree", 9000, 4500, 140),
    ("midea", 4480, 4480, 200),
    ("NEC (not an AC protocol)", 9000, 4500, 67),
    ("kelvinator", 9010, 4505, None),
    ("tcl112", 3000, 1650, None),
    ("haier", 3000, 4300, None),
    ("daikin", 3650, 1623, None),
    ("panasonic", 3456, 1728, None),
    ("samsung", 3000, 8900, None),
    ("whirlpool", 8950, 4484, None),
    ("hitachi", 3300, 1700, None),
    ("mitsubishi", 3400, 1750, None),
    ("fujitsu", 3324, 1574, None),
    ("electra", 9166, 4470, None),
    ("teco", 9000, 4440, None),
]


def identify(timings, tolerance=0.18):
    """Score the capture against known header signatures."""
    if len(timings) < 4:
        return []
    hdr_mark, hdr_space = timings[0], timings[1]
    hits = []
    for name, mark, space, nintervals in SIGNATURES:
        if (abs(hdr_mark - mark) <= tolerance * mark and
                abs(hdr_space - space) <= tolerance * space):
            exact = nintervals is not None and abs(len(timings) - nintervals) <= 2
            hits.append((name, exact))
    return hits


def analyse(timings):
    marks, spaces = timings[0::2], timings[1::2]
    print("  intervals : {} ({} marks, {} spaces)".format(len(timings), len(marks), len(spaces)))
    print("  duration  : {:.1f} ms".format(sum(timings) / 1000.0))
    print("  header    : mark {} us, space {} us".format(timings[0], timings[1]))

    for name, values in (("mark", marks), ("space", spaces)):
        bs = buckets(values)
        print("  {} clusters:".format(name))
        for b in sorted(bs, key=lambda x: x["lo"]):
            print("     {:>6}-{:<6} us  x{}".format(b["lo"], b["hi"], b["count"]))

    hits = identify(timings)
    print()
    if not hits:
        print("  header matches no protocol I know by signature.")
        print("  The cluster shape above is still the key to identifying it.")
    else:
        for name, exact in hits:
            mark = "  <== interval count matches too" if exact else ""
            print("  possible match: {}{}".format(name, mark))
    return hits


def load():
    try:
        with open(CAPTURE_FILE) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def save(label, timings, packet_hex):
    data = load()
    data.setdefault(label, []).append({"timings": timings, "broadlink": packet_hex})
    os.makedirs(os.path.dirname(CAPTURE_FILE), exist_ok=True)
    with open(CAPTURE_FILE, "w") as f:
        json.dump(data, f, indent=1)
    return len(data[label])


def connect():
    print("discovering Broadlink devices...")
    devices = broadlink.discover(timeout=5)
    if not devices:
        raise SystemExit("no Broadlink device found (same subnet? UDP broadcast blocked?)")
    dev = devices[0]
    dev.auth()
    print("using {} at {}\n".format(getattr(dev, "model", dev.type), dev.host[0]))
    return dev


def learn_one(dev, timeout_s=30):
    dev.enter_learning()
    print("  LEARNING -- point the CostWay remote at the RM and press a button")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            packet = dev.check_data()
        except Exception:
            continue
        if packet:
            return packet
        sys.stdout.write(".")
        sys.stdout.flush()
    print()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=None, help="name for this capture")
    ap.add_argument("--repeat", type=int, default=1, help="how many captures to take")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    dev = connect()
    for n in range(args.repeat):
        label = args.label or input("label for this capture> ").strip() or "unlabelled"
        print("[{}/{}] {}".format(n + 1, args.repeat, label))
        packet = learn_one(dev, args.timeout)
        if packet is None:
            print("  timed out, nothing learned\n")
            continue

        print("\n  raw packet: {} bytes".format(len(packet)))
        try:
            timings = decode_packet(packet)
        except ValueError as e:
            print("  {}".format(e))
            continue

        analyse(timings)
        count = save(label, timings, packet.hex())
        print("\n  saved as '{}' capture #{} in {}\n".format(
            label, count, os.path.relpath(CAPTURE_FILE, ROOT)))


if __name__ == "__main__":
    main()
