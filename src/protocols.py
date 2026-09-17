"""Encoders for documented air conditioner IR protocols.

Everything here turns a logical command into raw mark/space microsecond timings
for ir_tx.IRTransmitter. Constants are taken from IRremoteESP8266, which is the
best documentation that exists for these protocols.

Only Coolix is implemented so far. It is the most likely dialect for a budget
Chinese portable air conditioner, and unusually for an AC it is stateless enough
to be useful without decoding anything: each command is a self-contained 24 bit
value with no checksum.
"""

# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def bits_msb(value, nbits):
    """Most significant bit first."""
    return [(value >> (nbits - 1 - i)) & 1 for i in range(nbits)]


def bits_lsb(value, nbits):
    """Least significant bit first."""
    return [(value >> i) & 1 for i in range(nbits)]


def pulse_encode(bits, bit_mark, one_space, zero_space):
    """Turn a bit sequence into alternating mark/space durations."""
    out = []
    for b in bits:
        out.append(bit_mark)
        out.append(one_space if b else zero_space)
    return out


# ---------------------------------------------------------------------------
# Coolix
# ---------------------------------------------------------------------------
# Timings are kCoolixTick (276 us) multiples.
COOLIX_HDR_MARK = 4692       # 17 ticks
COOLIX_HDR_SPACE = 4416      # 16 ticks
COOLIX_BIT_MARK = 552        #  2 ticks
COOLIX_ONE_SPACE = 1656      #  6 ticks
COOLIX_ZERO_SPACE = 552      #  2 ticks
COOLIX_MIN_GAP = 5244        # 19 ticks

# Complete, ready to send states.
COOLIX_OFF = 0xB27BE0
COOLIX_SWING = 0xB26BE0
COOLIX_SWING_H = 0xB5F5A2
COOLIX_SWING_V = 0xB20FE0
COOLIX_SLEEP = 0xB2E003
COOLIX_TURBO = 0xB5F5A2
COOLIX_LED = 0xB5F5A5
COOLIX_CLEAN = 0xB5F5AA
COOLIX_CMD_FAN = 0xB2BFE4
COOLIX_DEFAULT_STATE = 0xB21FC8

COOLIX_MODE = {"cool": 0b00, "dry": 0b01, "auto": 0b10, "heat": 0b11}

COOLIX_FAN = {
    "auto": 0b101,
    "auto0": 0b000,
    "min": 0b100,
    "med": 0b010,
    "max": 0b001,
    "fixed": 0b111,
}

COOLIX_TEMP_MIN = 17
COOLIX_TEMP_MAX = 30

# The temperature field is not a plain integer -- it is a lookup, and the codes
# are deliberately out of order.
COOLIX_TEMP_MAP = (
    0b0000,  # 17C
    0b0001,  # 18C
    0b0011,  # 19C
    0b0010,  # 20C
    0b0110,  # 21C
    0b0111,  # 22C
    0b0101,  # 23C
    0b0100,  # 24C
    0b1100,  # 25C
    0b1101,  # 26C
    0b1001,  # 27C
    0b1000,  # 28C
    0b1010,  # 29C
    0b1011,  # 30C
)

COOLIX_SENSOR_TEMP_IGNORE = 0b11111

# Bit layout of the 24 bit state, least significant bit first:
#   [0]      unknown
#   [1]      zone follow 1
#   [2:4]    mode
#   [4:8]    temperature (via COOLIX_TEMP_MAP)
#   [8:13]   sensor temperature (0b11111 = ignore)
#   [13:16]  fan
#   [16:19]  unknown, observed as 0b010
#   [19]     zone follow 2
#   [20:24]  fixed 0b1011


def coolix_state(mode="cool", temp=24, fan="auto"):
    """Build a 24 bit Coolix state.

    Returns the raw value; pass it to coolix_frame() to get timings.
    """
    if mode not in COOLIX_MODE:
        raise ValueError("mode must be one of {}".format(sorted(COOLIX_MODE)))
    if fan not in COOLIX_FAN:
        raise ValueError("fan must be one of {}".format(sorted(COOLIX_FAN)))
    if not COOLIX_TEMP_MIN <= temp <= COOLIX_TEMP_MAX:
        raise ValueError("temp must be {}-{} C".format(COOLIX_TEMP_MIN, COOLIX_TEMP_MAX))

    raw = 0xB << 20                                   # fixed nibble
    raw |= 0b010 << 16                                # unknown, as observed
    raw |= COOLIX_FAN[fan] << 13
    raw |= COOLIX_SENSOR_TEMP_IGNORE << 8
    raw |= COOLIX_TEMP_MAP[temp - COOLIX_TEMP_MIN] << 4
    raw |= COOLIX_MODE[mode] << 2
    return raw


def coolix_frame(value):
    """Timings for one Coolix frame (header, data, footer).

    Each byte is sent most significant first, immediately followed by its own
    inverse -- a self-checking scheme that stands in for a checksum.

    Send this twice; the reference implementation repeats once by default.
    """
    timings = [COOLIX_HDR_MARK, COOLIX_HDR_SPACE]
    for shift in (16, 8, 0):                          # most significant byte first
        byte = (value >> shift) & 0xFF
        timings += pulse_encode(bits_msb(byte, 8),
                                COOLIX_BIT_MARK, COOLIX_ONE_SPACE, COOLIX_ZERO_SPACE)
        timings += pulse_encode(bits_msb(byte ^ 0xFF, 8),
                                COOLIX_BIT_MARK, COOLIX_ONE_SPACE, COOLIX_ZERO_SPACE)
    timings.append(COOLIX_BIT_MARK)                   # footer mark
    timings.append(COOLIX_MIN_GAP)
    return timings


def coolix_send(tx, value, repeat=2):
    """Transmit a Coolix state."""
    tx.send(coolix_frame(value), repeat=repeat, gap_us=COOLIX_MIN_GAP)


# ---------------------------------------------------------------------------
# Gree
# ---------------------------------------------------------------------------
# Unusual framing: the 8 byte state is split into two blocks, separated by a
# 3 bit marker and a long gap. Bytes go out least significant bit first.
GREE_HDR_MARK = 9000
GREE_HDR_SPACE = 4500
GREE_BIT_MARK = 620
GREE_ONE_SPACE = 1600
GREE_ZERO_SPACE = 540
GREE_MSG_SPACE = 19980
GREE_BLOCK_FOOTER = 0b010
GREE_BLOCK_FOOTER_BITS = 3

GREE_MODE = {"auto": 0, "cool": 1, "dry": 2, "fan": 3, "heat": 4}
GREE_FAN = {"auto": 0, "min": 1, "med": 2, "max": 3}
GREE_TEMP_MIN = 16
GREE_TEMP_MAX = 30

# Gree borrows Kelvinator's block checksum, which starts from a fixed seed.
_KELVINATOR_CHECKSUM_START = 10


def gree_checksum(state):
    """Low nibbles of the first four bytes, high nibbles of the next three."""
    total = _KELVINATOR_CHECKSUM_START
    for i in range(4):
        total += state[i] & 0x0F
    for i in range(4, 7):
        total += state[i] >> 4
    return total & 0x0F


def gree_state(mode="cool", temp=25, fan="auto", power=True, light=True):
    """Build an 8 byte Gree state with a valid checksum."""
    if mode not in GREE_MODE:
        raise ValueError("mode must be one of {}".format(sorted(GREE_MODE)))
    if fan not in GREE_FAN:
        raise ValueError("fan must be one of {}".format(sorted(GREE_FAN)))
    if not GREE_TEMP_MIN <= temp <= GREE_TEMP_MAX:
        raise ValueError("temp must be {}-{} C".format(GREE_TEMP_MIN, GREE_TEMP_MAX))

    s = bytearray(8)
    s[0] = GREE_MODE[mode] | ((1 if power else 0) << 3) | (GREE_FAN[fan] << 4)
    s[1] = temp - GREE_TEMP_MIN
    s[2] = (1 if light else 0) << 5
    s[3] = 0b0101 << 4                    # fixed, per the reference implementation
    s[4] = 0
    s[5] = 0b100 << 3                     # fixed
    s[6] = 0
    s[7] = gree_checksum(s) << 4
    return s


def gree_frame(state):
    """Timings for one Gree message (two blocks plus separator)."""
    timings = [GREE_HDR_MARK, GREE_HDR_SPACE]

    # Block 1: bytes 0-3, no footer of its own.
    bits = []
    for byte in state[:4]:
        bits += bits_lsb(byte, 8)
    timings += pulse_encode(bits, GREE_BIT_MARK, GREE_ONE_SPACE, GREE_ZERO_SPACE)

    # Separator: a 3 bit marker, then a long gap.
    timings += pulse_encode(bits_lsb(GREE_BLOCK_FOOTER, GREE_BLOCK_FOOTER_BITS),
                            GREE_BIT_MARK, GREE_ONE_SPACE, GREE_ZERO_SPACE)
    timings += [GREE_BIT_MARK, GREE_MSG_SPACE]

    # Block 2: bytes 4-7, no header.
    bits = []
    for byte in state[4:]:
        bits += bits_lsb(byte, 8)
    timings += pulse_encode(bits, GREE_BIT_MARK, GREE_ONE_SPACE, GREE_ZERO_SPACE)
    timings += [GREE_BIT_MARK, GREE_MSG_SPACE]
    return timings


def gree_send(tx, state, repeat=1):
    tx.send(gree_frame(state), repeat=repeat, gap_us=GREE_MSG_SPACE)


# ---------------------------------------------------------------------------
# Midea
# ---------------------------------------------------------------------------
# 48 bits, sent twice per message: once normally, once entirely inverted.
MIDEA_HDR_MARK = 4480        # 56 ticks of 80 us
MIDEA_HDR_SPACE = 4480
MIDEA_BIT_MARK = 560         #  7 ticks
MIDEA_ONE_SPACE = 1680       # 21 ticks
MIDEA_ZERO_SPACE = 560       #  7 ticks
MIDEA_MIN_GAP = 5600         # 70 ticks

MIDEA_MODE = {"cool": 0, "dry": 1, "auto": 2, "heat": 3, "fan": 4}
MIDEA_FAN = {"auto": 0, "min": 1, "med": 2, "max": 3}
MIDEA_TEMP_MIN = 17
MIDEA_TEMP_MAX = 30

# The reference implementation's known-good state: power on, auto, fan auto, 25C.
MIDEA_DEFAULT_STATE = 0xA1826FFFFF62


def _reverse_bits(value, nbits=8):
    out = 0
    for _ in range(nbits):
        out = (out << 1) | (value & 1)
        value >>= 1
    return out


def midea_checksum(state):
    """Sum of the upper five bytes, bit-reversed going in and coming out."""
    total = 0
    temp = state
    for _ in range(5):
        temp >>= 8
        total = (total + _reverse_bits(temp & 0xFF)) & 0xFF
    return _reverse_bits((256 - total) & 0xFF)


def midea_state(mode="cool", temp=24, fan="auto", power=True):
    """Build a 48 bit Midea state with a valid checksum."""
    if mode not in MIDEA_MODE:
        raise ValueError("mode must be one of {}".format(sorted(MIDEA_MODE)))
    if fan not in MIDEA_FAN:
        raise ValueError("fan must be one of {}".format(sorted(MIDEA_FAN)))
    if not MIDEA_TEMP_MIN <= temp <= MIDEA_TEMP_MAX:
        raise ValueError("temp must be {}-{} C".format(MIDEA_TEMP_MIN, MIDEA_TEMP_MAX))

    byte5 = (0b10100 << 3) | 0b001                    # header nibble + message type
    byte4 = ((1 if power else 0) << 7) | (MIDEA_FAN[fan] << 3) | MIDEA_MODE[mode]
    byte3 = temp - MIDEA_TEMP_MIN                     # Celsius; bit 5 would select F
    byte2 = 0xFF                                      # no off timer, beep enabled
    byte1 = 0xFF                                      # sensor temperature unused

    state = (byte5 << 40) | (byte4 << 32) | (byte3 << 24) | (byte2 << 16) | (byte1 << 8)
    return state | midea_checksum(state)


def midea_frame(state):
    """Timings for one Midea message: the payload, then its inverse."""
    timings = []
    for payload in (state, ~state & 0xFFFFFFFFFFFF):
        timings += [MIDEA_HDR_MARK, MIDEA_HDR_SPACE]
        for shift in (40, 32, 24, 16, 8, 0):          # most significant byte first
            timings += pulse_encode(bits_msb((payload >> shift) & 0xFF, 8),
                                    MIDEA_BIT_MARK, MIDEA_ONE_SPACE, MIDEA_ZERO_SPACE)
        timings += [MIDEA_BIT_MARK, MIDEA_MIN_GAP]
    return timings


def midea_send(tx, state, repeat=1):
    tx.send(midea_frame(state), repeat=repeat, gap_us=MIDEA_MIN_GAP)


# ---------------------------------------------------------------------------
# TCL112  -- this is what the CostWay unit actually speaks
# ---------------------------------------------------------------------------
# Identified by capture: 112 bit frames prefixed 23 CB 26, checksums verifying
# against the documented algorithm, and the isTcl flag set in byte 12.
#
# Every button press sends two blocks: a constant "special" preamble
# (MsgType 0x02) and then the state itself (MsgType 0x01).
TCL112_HDR_MARK = 3000
TCL112_HDR_SPACE = 1650
TCL112_BIT_MARK = 500
TCL112_ONE_SPACE = 1050
TCL112_ZERO_SPACE = 325
TCL112_BLOCK_GAP = 69900       # measured between the two blocks
TCL112_MSG_GAP = 101730        # measured after the second block

TCL112_MODE = {"heat": 1, "dry": 2, "cool": 3, "fan": 7, "auto": 8}
TCL112_FAN = {"auto": 0, "min": 1, "low": 2, "med": 3, "high": 5}
TCL112_TEMP_MIN = 16
TCL112_TEMP_MAX = 31

# The constant preamble this remote emits before every state message.
TCL112_PREAMBLE = bytes((0x23, 0xCB, 0x26, 0x02, 0x00, 0x40, 0x40, 0x00,
                         0x80, 0x00, 0x00, 0x00, 0x00, 0x25))

# Base state captured from the real remote: power on, cool, 25 C, fan low.
# Preferred over the reference implementation's generic template because it
# carries this unit's own quirks -- notably the isTcl flag in byte 12.
TCL112_BASE = bytes((0x23, 0xCB, 0x26, 0x01, 0x00, 0x24, 0x03, 0x06,
                     0x02, 0x00, 0x00, 0x00, 0x80, 0xC4))

# Bit positions within the state, from the documented layout:
#   byte 3  bits 0-1  message type (1 = state, 2 = special)
#   byte 5  bit  2    power
#   byte 6  bits 0-3  mode
#   byte 7  bits 0-3  temperature, encoded as 31 - celsius
#   byte 8  bits 0-2  fan
#   byte 12 bit  7    isTcl
#   byte 13           checksum
_TCL112_POWER_BIT = 0x04       # byte 5
_TCL112_ECONO_BIT = 0x80       # byte 5
_TCL112_TURBO_BIT = 0x40       # byte 6 -- see note below
_TCL112_IFEEL_BIT = 0x80       # byte 6
_TCL112_SWINGV_ON = 0x07       # byte 6 bits 3-5, full vertical swing

# Measured deviation from the documented layout: the reference implementation
# puts Turbo at byte 6 bit 5 and calls bits 6-7 unused. On this unit, pressing
# TURBO sets bit *6*, and I FEEL sets bit 7. Captures beat documentation.


def tcl112_checksum(state):
    """Sum of the first 13 bytes; a special message needs a 0xF offset."""
    total = sum(state[:13]) & 0xFF
    if state[3] == 0x02:
        total = (total + 0x0F) & 0xFF
    return total


def tcl112_state(mode="cool", temp=24, fan="auto", power=True,
                 swing=False, turbo=False, econo=False):
    """Build a 14 byte TCL112 state with a valid checksum.

    swing/turbo/econo were mapped by capturing the corresponding button on the
    real remote. Note the remote couples some of these to other fields -- TURBO
    also forces fan high, ECO also forces 26 C -- but that is remote behaviour,
    not protocol, so it is left to the caller.
    """
    if mode not in TCL112_MODE:
        raise ValueError("mode must be one of {}".format(sorted(TCL112_MODE)))
    if fan not in TCL112_FAN:
        raise ValueError("fan must be one of {}".format(sorted(TCL112_FAN)))
    if not TCL112_TEMP_MIN <= temp <= TCL112_TEMP_MAX:
        raise ValueError("temp must be {}-{} C".format(TCL112_TEMP_MIN, TCL112_TEMP_MAX))

    s = bytearray(TCL112_BASE)
    s[5] = (s[5] | _TCL112_POWER_BIT) if power else (s[5] & ~_TCL112_POWER_BIT)
    s[6] = (s[6] & 0xF0) | TCL112_MODE[mode]
    s[7] = (s[7] & 0xF0) | (TCL112_TEMP_MAX - temp)
    s[8] = (s[8] & 0xF8) | TCL112_FAN[fan]

    s[5] = (s[5] | _TCL112_ECONO_BIT) if econo else (s[5] & ~_TCL112_ECONO_BIT)
    s[6] = (s[6] | _TCL112_TURBO_BIT) if turbo else (s[6] & ~_TCL112_TURBO_BIT)
    s[8] = (s[8] & 0xC7) | ((_TCL112_SWINGV_ON if swing else 0) << 3)

    s[13] = tcl112_checksum(s)
    return s


def tcl112_block(state, gap):
    """Timings for one 112 bit block. Bytes go out least significant bit first."""
    timings = [TCL112_HDR_MARK, TCL112_HDR_SPACE]
    bits = []
    for byte in state:
        bits += bits_lsb(byte, 8)
    timings += pulse_encode(bits, TCL112_BIT_MARK, TCL112_ONE_SPACE, TCL112_ZERO_SPACE)
    timings += [TCL112_BIT_MARK, gap]
    return timings


def tcl112_frame(state, preamble=True):
    """Timings for a complete message, as the original remote sends it."""
    timings = []
    if preamble:
        timings += tcl112_block(TCL112_PREAMBLE, TCL112_BLOCK_GAP)
    timings += tcl112_block(state, TCL112_MSG_GAP)
    return timings


def tcl112_send(tx, state, preamble=True, repeat=1):
    tx.send(tcl112_frame(state, preamble), repeat=repeat, gap_us=TCL112_MSG_GAP)
