"""Diff captured states to work out which bits carry which setting.

Reads everything in captures/remote.json, decodes each to its 14 byte TCL112
state, and compares against a base capture. Bits that move when exactly one
setting changed are that setting's bits.

Also checks our encoder against the real frames, which is the test that actually
matters: the documented field map is an assumption until a capture confirms it.

    .venv/bin/python tools/analyse.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import rm_learn
import protocols as p

CAPTURE_FILE = os.path.join(ROOT, "captures", "remote.json")
BLOCK_INTERVALS = 2 + 112 * 2 + 2


def to_states(timings):
    """Split a capture into its 14 byte blocks."""
    blocks = []
    for i in range(0, len(timings), BLOCK_INTERVALS):
        blk = timings[i:i + BLOCK_INTERVALS]
        if len(blk) < BLOCK_INTERVALS:
            break
        bits = [1 if s > 700 else 0 for s in blk[3:3 + 224:2]]
        st = bytearray(14)
        for j in range(14):
            for b in range(8):
                st[j] |= bits[j * 8 + b] << b
        blocks.append(bytes(st))
    return blocks


def state_message(blocks):
    """The block carrying the machine state (MsgType 1), not the preamble."""
    for b in blocks:
        if b[3] == 0x01:
            return b
    return blocks[-1] if blocks else None


def describe(state):
    """Decode a state using the field map we believe in."""
    mode_names = {v: k for k, v in p.TCL112_MODE.items()}
    fan_names = {v: k for k, v in p.TCL112_FAN.items()}
    return {
        "power": bool(state[5] & 0x04),
        "mode": mode_names.get(state[6] & 0x0F, "?%d" % (state[6] & 0x0F)),
        "temp": p.TCL112_TEMP_MAX - (state[7] & 0x0F),
        "fan": fan_names.get(state[8] & 0x07, "?%d" % (state[8] & 0x07)),
        "swingv": (state[8] >> 3) & 0x07,
    }


def bit_diff(a, b):
    out = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            bits = [j for j in range(8) if (a[i] ^ b[i]) >> j & 1]
            out.append((i, a[i], b[i], bits))
    return out


def main():
    try:
        data = json.load(open(CAPTURE_FILE))
    except (IOError, OSError, ValueError):
        raise SystemExit("no captures yet -- run tools/capture_matrix.py first")

    states = {}
    print("=" * 76)
    print("DECODED STATES")
    print("=" * 76)
    for label, caps in data.items():
        st = state_message(to_states(caps[-1]["timings"]))
        if st is None:
            print("  {:<18} could not decode".format(label))
            continue
        states[label] = st
        ok = "ok" if p.tcl112_checksum(st) == st[13] else "BAD"
        d = describe(st)
        print("  {:<18} {}  [{}]  power={:<3} mode={:<5} {:>2}C fan={:<5} swingV={}".format(
            label, " ".join("%02X" % b for b in st), ok,
            "on" if d["power"] else "off", d["mode"], d["temp"], d["fan"], d["swingv"]))

    base_label = "cool_25_fanauto" if "cool_25_fanauto" in states else None
    if base_label is None:
        for cand in ("power_on", "cool_25_fan1"):
            if cand in states:
                base_label = cand
                break
    if base_label is None:
        print("\nno base capture to diff against")
        return

    print()
    print("=" * 76)
    print("DIFFS vs '{}'".format(base_label))
    print("=" * 76)
    base = states[base_label]
    for label, st in states.items():
        if label == base_label:
            continue
        diffs = [d for d in bit_diff(base, st) if d[0] != 13]      # ignore checksum
        if not diffs:
            print("  {:<18} identical (apart from checksum)".format(label))
            continue
        parts = ["byte{} {:02X}->{:02X} bits{}".format(i, a, b, bits)
                 for i, a, b, bits in diffs]
        print("  {:<18} {}".format(label, "; ".join(parts)))

    print()
    print("=" * 76)
    print("ENCODER vs REALITY")
    print("=" * 76)
    print("Does tcl112_state() reproduce what the remote actually sent?\n")
    checks = [
        ("cool_25_fanauto", dict(mode="cool", temp=25, fan="auto", power=True)),
        ("cool_25_fan1", dict(mode="cool", temp=25, fan="min", power=True)),
        ("cool_25_fan2", dict(mode="cool", temp=25, fan="low", power=True)),
        ("cool_25_fan3", dict(mode="cool", temp=25, fan="med", power=True)),
        ("cool_20_fanauto", dict(mode="cool", temp=20, fan="auto", power=True)),
        ("cool_30_fanauto", dict(mode="cool", temp=30, fan="auto", power=True)),
        ("cool_16_fanauto", dict(mode="cool", temp=16, fan="auto", power=True)),
        ("heat_25", dict(mode="heat", temp=25, fan="auto", power=True)),
        ("dry_25", dict(mode="dry", temp=25, fan="auto", power=True)),
        ("fanmode_25", dict(mode="fan", temp=25, fan="auto", power=True)),
        ("auto_25", dict(mode="auto", temp=25, fan="auto", power=True)),
    ]
    passed = failed = 0
    for label, kwargs in checks:
        if label not in states:
            continue
        want = states[label]
        got = bytes(p.tcl112_state(**kwargs))
        if got == want:
            print("  PASS  {:<18} {}".format(label, " ".join("%02X" % b for b in got)))
            passed += 1
        else:
            print("  FAIL  {:<18}".format(label))
            print("          remote : {}".format(" ".join("%02X" % b for b in want)))
            print("          encoder: {}".format(" ".join("%02X" % b for b in got)))
            for i, a, b, bits in bit_diff(want, got):
                print("          byte{:<2} {:02X} -> {:02X}  bits {}".format(i, a, b, bits))
            failed += 1

    print("\n  {} passed, {} failed".format(passed, failed))
    if failed:
        print("  -> the field map needs correcting in src/protocols.py")


if __name__ == "__main__":
    main()
