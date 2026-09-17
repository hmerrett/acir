"""Checks on the Coolix encoder.

The strong test here is the round trip: encode a state to timings, then decode
those timings back independently and confirm we get the same value. That
exercises the framing, the bit order and the byte inversion in one go.
"""

import protocols as p


def decode_coolix(timings):
    """Independent decoder, written from the wire format rather than from the
    encoder, so it does not share the encoder's bugs."""
    assert abs(timings[0] - p.COOLIX_HDR_MARK) < 50, "bad header mark"
    assert abs(timings[1] - p.COOLIX_HDR_SPACE) < 50, "bad header space"

    body = timings[2:-2]                       # strip header and footer
    spaces = body[1::2]
    bits = [1 if s > 1000 else 0 for s in spaces]
    assert len(bits) == 48, "expected 48 bits (3 bytes x normal+inverted), got %d" % len(bits)

    value = 0
    for b in range(3):
        chunk = bits[b * 16:(b + 1) * 16]
        normal, inverted = chunk[:8], chunk[8:]
        for i in range(8):
            assert normal[i] != inverted[i], "byte %d bit %d is not its own inverse" % (b, i)
        byte = 0
        for bit in normal:
            byte = (byte << 1) | bit
        value = (value << 8) | byte
    return value


def check_default_state_matches_reference():
    """The acid test: our field packing must reproduce the library's own constant."""
    got = p.coolix_state(mode="auto", temp=25, fan="auto0")
    assert got == p.COOLIX_DEFAULT_STATE, \
        "got 0x%06X, reference is 0x%06X" % (got, p.COOLIX_DEFAULT_STATE)
    print("  coolix_state(auto, 25C, auto0) == 0x%06X, matches the reference" % got)


def check_round_trip():
    for mode in sorted(p.COOLIX_MODE):
        for temp in (17, 20, 24, 30):
            for fan in sorted(p.COOLIX_FAN):
                state = p.coolix_state(mode, temp, fan)
                assert decode_coolix(p.coolix_frame(state)) == state, \
                    "round trip failed for %s %dC %s" % (mode, temp, fan)
    n = len(p.COOLIX_MODE) * 4 * len(p.COOLIX_FAN)
    print("  %d state combinations survive an encode/decode round trip" % n)


def check_fixed_states_round_trip():
    for name in ("COOLIX_OFF", "COOLIX_SWING", "COOLIX_SWING_V", "COOLIX_SLEEP",
                 "COOLIX_CMD_FAN", "COOLIX_DEFAULT_STATE"):
        value = getattr(p, name)
        assert decode_coolix(p.coolix_frame(value)) == value, "%s failed" % name
    print("  the documented fixed states all round trip")


def check_frame_shape():
    frame = p.coolix_frame(p.COOLIX_OFF)
    # header (2) + 3 bytes x 16 bits x 2 intervals (96) + footer (2)
    assert len(frame) == 100, len(frame)
    assert frame[-1] == p.COOLIX_MIN_GAP
    duration = sum(frame)
    print("  frame is %d intervals, %.1f ms; x2 repeats ~%.0f ms total"
          % (len(frame), duration / 1000, duration * 2 / 1000))
    assert 50000 < duration < 120000, "implausible frame duration %d us" % duration


def check_validation():
    for bad in (lambda: p.coolix_state(temp=16), lambda: p.coolix_state(temp=31),
                lambda: p.coolix_state(mode="banana"), lambda: p.coolix_state(fan="turbo")):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("bad input was accepted")
    print("  out of range inputs are rejected")


def main():
    check_default_state_matches_reference()
    check_round_trip()
    check_fixed_states_round_trip()
    check_frame_shape()
    check_validation()
    print("protocols OK")


# ---------------------------------------------------------------------------
# Gree
# ---------------------------------------------------------------------------

def decode_gree(timings):
    """Independent decoder, from the wire format."""
    assert abs(timings[0] - p.GREE_HDR_MARK) < 100, "bad header mark"
    assert abs(timings[1] - p.GREE_HDR_SPACE) < 100, "bad header space"
    spaces = timings[3::2]
    bits = [1 if s > 1000 else 0 for s in spaces]

    block1, marker, block2 = bits[:32], bits[32:35], bits[36:68]
    assert marker == [0, 1, 0], "block separator should be 0b010 LSB-first, got %s" % marker

    out = bytearray(8)
    for i in range(4):
        for b in range(8):
            out[i] |= block1[i * 8 + b] << b          # least significant bit first
    for i in range(4):
        for b in range(8):
            out[4 + i] |= block2[i * 8 + b] << b
    return out


def check_gree_matches_reference():
    """The reference stateReset() is: power off, mode auto, fan auto, 25C, light on.
    It documents the exact bytes, so our builder must reproduce them."""
    s = p.gree_state(mode="auto", temp=25, fan="auto", power=False, light=True)
    expected = bytes([0x00, 0x09, 0x20, 0x50, 0x00, 0x20, 0x00, 0x50])
    assert bytes(s) == expected, "got %s, reference is %s" % (
        [hex(b) for b in s], [hex(b) for b in expected])
    print("  gree_state(auto, 25C, off) == %s, matches the reference"
          % " ".join("%02X" % b for b in s))
    assert p.gree_checksum(s) == 5, p.gree_checksum(s)


def check_gree_round_trip():
    for mode in sorted(p.GREE_MODE):
        for temp in (16, 20, 25, 30):
            for fan in sorted(p.GREE_FAN):
                s = p.gree_state(mode, temp, fan)
                assert decode_gree(p.gree_frame(s)) == s, \
                    "round trip failed for %s %dC %s" % (mode, temp, fan)
                assert p.gree_checksum(s) == (s[7] >> 4), "checksum not embedded"
    n = len(p.GREE_MODE) * 4 * len(p.GREE_FAN)
    print("  %d Gree states survive an encode/decode round trip" % n)


def check_gree_frame_shape():
    frame = p.gree_frame(p.gree_state())
    # hdr(2) + 32 bits(64) + 3 marker bits(6) + sep(2) + 32 bits(64) + tail(2)
    assert len(frame) == 140, len(frame)
    print("  Gree frame is %d intervals, %.1f ms" % (len(frame), sum(frame) / 1000))


# ---------------------------------------------------------------------------
# Midea
# ---------------------------------------------------------------------------

def check_midea_checksum_matches_reference():
    """The reference known-good state carries its own checksum in the low byte,
    so recomputing it is a direct test of the algorithm."""
    ref = p.MIDEA_DEFAULT_STATE
    got = p.midea_checksum(ref & ~0xFF)
    assert got == (ref & 0xFF), "got 0x%02X, reference low byte is 0x%02X" % (got, ref & 0xFF)
    print("  midea_checksum(0x%012X) == 0x%02X, matches the reference" % (ref & ~0xFF, got))


def decode_midea(timings):
    """Independent decoder. Also checks the second half really is the inverse."""
    half = len(timings) // 2
    values = []
    for chunk in (timings[:half], timings[half:]):
        assert abs(chunk[0] - p.MIDEA_HDR_MARK) < 100, "bad header mark"
        spaces = chunk[3:-2:2]
        bits = [1 if s > 1000 else 0 for s in spaces]
        assert len(bits) == 48, len(bits)
        v = 0
        for b in bits:
            v = (v << 1) | b                          # most significant bit first
        values.append(v)
    assert values[0] == (~values[1] & 0xFFFFFFFFFFFF), \
        "second half is not the inverse of the first"
    return values[0]


def check_midea_round_trip():
    for mode in sorted(p.MIDEA_MODE):
        for temp in (17, 22, 30):
            for fan in sorted(p.MIDEA_FAN):
                state = p.midea_state(mode, temp, fan)
                assert p.midea_checksum(state & ~0xFF) == (state & 0xFF), \
                    "checksum not embedded for %s %dC %s" % (mode, temp, fan)
                assert decode_midea(p.midea_frame(state)) == state, \
                    "round trip failed for %s %dC %s" % (mode, temp, fan)
    n = len(p.MIDEA_MODE) * 3 * len(p.MIDEA_FAN)
    print("  %d Midea states survive an encode/decode round trip" % n)


def check_midea_frame_shape():
    frame = p.midea_frame(p.midea_state())
    # 2 halves x (hdr(2) + 48 bits(96) + tail(2))
    assert len(frame) == 200, len(frame)
    print("  Midea frame is %d intervals, %.1f ms" % (len(frame), sum(frame) / 1000))


_orig_main = main


def main():
    _orig_main()
    print("\n--- Gree ---")
    check_gree_matches_reference()
    check_gree_round_trip()
    check_gree_frame_shape()
    print("\n--- Midea ---")
    check_midea_checksum_matches_reference()
    check_midea_round_trip()
    check_midea_frame_shape()
    print("all protocols OK")


# ---------------------------------------------------------------------------
# TCL112 -- validated against frames captured from the actual remote
# ---------------------------------------------------------------------------

# Exactly what the RM Pro learned from the CostWay remote.
CAPTURED_POWER_ON = bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x24, 0x03, 0x06,
                           0x02, 0x00, 0x00, 0x00, 0x80, 0xC4))
CAPTURED_POWER_OFF = bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x06,
                            0x02, 0x00, 0x00, 0x00, 0x80, 0xC0))
CAPTURED_PREAMBLE = bytes((0x23, 0xCB, 0x26, 0x02, 0x00, 0x40, 0x40, 0x00,
                           0x80, 0x00, 0x00, 0x00, 0x00, 0x25))


def check_tcl_reproduces_captures():
    """The encoder must reproduce real frames byte for byte."""
    on = p.tcl112_state("cool", 25, "low", power=True)
    assert bytes(on) == CAPTURED_POWER_ON, \
        "power-on: got %s" % " ".join("%02X" % b for b in on)
    off = p.tcl112_state("cool", 25, "low", power=False)
    assert bytes(off) == CAPTURED_POWER_OFF, \
        "power-off: got %s" % " ".join("%02X" % b for b in off)
    print("  reproduces both captured frames byte for byte")


def check_tcl_checksums():
    for name, frame in (("power on", CAPTURED_POWER_ON),
                        ("power off", CAPTURED_POWER_OFF),
                        ("preamble", CAPTURED_PREAMBLE)):
        assert p.tcl112_checksum(frame) == frame[13], \
            "%s checksum failed: calc %02X want %02X" % (
                name, p.tcl112_checksum(frame), frame[13])
    print("  checksums verify on all three captured blocks (incl. the 0xF special rule)")


def decode_tcl112(timings):
    """Independent decoder, from the wire format."""
    per = 2 + 112 * 2 + 2
    blocks = []
    for i in range(0, len(timings), per):
        blk = timings[i:i + per]
        assert abs(blk[0] - p.TCL112_HDR_MARK) < 100, "bad header mark"
        bits = [1 if s > 700 else 0 for s in blk[3:3 + 224:2]]
        assert len(bits) == 112, len(bits)
        st = bytearray(14)
        for j in range(14):
            for b in range(8):
                st[j] |= bits[j * 8 + b] << b       # least significant bit first
        blocks.append(bytes(st))
    return blocks


def check_tcl_round_trip():
    for mode in sorted(p.TCL112_MODE):
        for temp in (16, 20, 25, 31):
            for fan in sorted(p.TCL112_FAN):
                for power in (True, False):
                    s = p.tcl112_state(mode, temp, fan, power)
                    assert p.tcl112_checksum(s) == s[13], "checksum not embedded"
                    blocks = decode_tcl112(p.tcl112_frame(s))
                    assert len(blocks) == 2, len(blocks)
                    assert blocks[0] == CAPTURED_PREAMBLE, "preamble corrupted"
                    assert blocks[1] == bytes(s), "state round trip failed"
    n = len(p.TCL112_MODE) * 4 * len(p.TCL112_FAN) * 2
    print("  %d TCL112 states survive an encode/decode round trip" % n)


def check_tcl_temp_encoding():
    for temp in range(16, 32):
        s = p.tcl112_state("cool", temp, "auto")
        assert (s[7] & 0x0F) == (31 - temp), temp
    print("  temperature encodes as 31 - celsius across the full 16-31 C range")


def check_tcl_frame_shape():
    frame = p.tcl112_frame(p.tcl112_state())
    assert len(frame) == 456, len(frame)
    print("  frame is %d intervals, %.1f ms -- matches the 456 captured"
          % (len(frame), sum(frame) / 1000))


_prev_main = main


def main():
    _prev_main()
    print("\n--- TCL112 (the real one) ---")
    check_tcl_reproduces_captures()
    check_tcl_checksums()
    check_tcl_round_trip()
    check_tcl_temp_encoding()
    check_tcl_frame_shape()


# ---------------------------------------------------------------------------
# Regression fixtures: frames captured from the real CostWay remote via a
# Broadlink RM Pro, decoded and checksum-verified. These are ground truth --
# if the encoder stops reproducing them, it is the encoder that is wrong.
# ---------------------------------------------------------------------------

CAPTURED = [
    ("cool_25_fanauto",
     dict(mode="cool", temp=25, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x06, 0x00, 0x00, 0x00, 0x00, 0x80, 0xBE))),
    ("cool_25_fan1",
     dict(mode="cool", temp=25, fan="low",  power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x06, 0x02, 0x00, 0x00, 0x00, 0x80, 0xC0))),
    ("cool_25_fan2",
     dict(mode="cool", temp=25, fan="med",  power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x06, 0x03, 0x00, 0x00, 0x00, 0x80, 0xC1))),
    ("cool_20_fanauto",
     dict(mode="cool", temp=20, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x0B, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC3))),
    ("cool_30_fanauto",
     dict(mode="cool", temp=30, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x80, 0xB9))),
    ("cool_16_fanauto",
     dict(mode="cool", temp=16, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x03, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC7))),
    ("heat_25",
     dict(mode="heat", temp=25, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x01, 0x06, 0x00, 0x00, 0x00, 0x00, 0x80, 0xBC))),
    ("dry_25",
     dict(mode="dry",  temp=26, fan="low",  power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x02, 0x05, 0x02, 0x00, 0x00, 0x00, 0x80, 0xBE))),
    ("fanmode_25",
     dict(mode="fan",  temp=26, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x07, 0x05, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC1))),
    ("auto_25",
     dict(mode="auto", temp=25, fan="auto", power=False),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x08, 0x06, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC3))),
    ("cool_25_sleep",
     dict(mode="cool", temp=25, fan="min",  power=True),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x24, 0x03, 0x06, 0x01, 0x00, 0x00, 0x00, 0x80, 0xC3))),
    ("cool_25_turbo",
     dict(mode="cool", temp=25, fan="high", power=True, turbo=True),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x24, 0x43, 0x06, 0x05, 0x00, 0x00, 0x00, 0x80, 0x07))),
    ("cool_25_eco",
     dict(mode="cool", temp=26, fan="auto", power=True, econo=True),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0xA4, 0x03, 0x05, 0x00, 0x00, 0x00, 0x00, 0x80, 0x41))),
    ("cool_25_swing",
     dict(mode="cool", temp=25, fan="min",  power=True, swing=True),
     bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x24, 0x03, 0x06, 0x39, 0x00, 0x00, 0x00, 0x80, 0xFB))),
]


def check_against_real_remote():
    """Every captured frame must be reproducible from its logical description."""
    for label, kwargs, expected in CAPTURED:
        got = bytes(p.tcl112_state(**kwargs))
        assert got == expected, "%s\n    remote : %s\n    encoder: %s" % (
            label, " ".join("%02X" % b for b in expected),
            " ".join("%02X" % b for b in got))
        assert p.tcl112_checksum(expected) == expected[13], "%s checksum" % label
    print("  %d frames captured from the real remote reproduce exactly" % len(CAPTURED))


def check_fan_values_observed():
    """The documented fan set has an odd gap at 4. Captures confirm it."""
    seen = sorted({st[8] & 0x07 for _, _, st in CAPTURED})
    assert 4 not in seen, "value 4 turned up after all: %s" % seen
    assert set(seen).issubset(set(p.TCL112_FAN.values())), seen
    print("  fan values seen in captures: %s (4 unused, as documented)" % seen)


_p2 = main


def main():
    _p2()
    print("\n--- against the real remote ---")
    check_against_real_remote()
    check_fan_values_observed()
