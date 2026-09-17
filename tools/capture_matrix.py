"""Walk through a list of scenarios, capturing each one from the real remote.

The point is differential: capture states that differ in exactly one thing, then
diff the frames to see which bits carry that setting. That turns the documented
field map from an assumption into a measurement.

    .venv/bin/python tools/capture_matrix.py                 # the core set
    .venv/bin/python tools/capture_matrix.py --only fan      # just fan speeds
    .venv/bin/python tools/capture_matrix.py --list

For each scenario: set the remote to the described state, then point it at the RM
and press the button that applies it. The remote sends its whole state on every
press, so the last press carries the full configuration.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import rm_learn

# group, label, instruction
SCENARIOS = [
    ("base", "cool_25_fanauto", "MODE to cool (snowflake), TEMP to 25, FAN to auto"),

    ("fan", "cool_25_fan1", "same, but FAN to speed 1 (lowest bar)"),
    ("fan", "cool_25_fan2", "same, but FAN to speed 2"),
    ("fan", "cool_25_fan3", "same, but FAN to speed 3 (highest bar)"),

    ("temp", "cool_20_fanauto", "cool, FAN auto, TEMP down to 20"),
    ("temp", "cool_30_fanauto", "cool, FAN auto, TEMP up to 30"),
    ("temp", "cool_16_fanauto", "cool, FAN auto, TEMP down to 16 (minimum)"),

    ("mode", "heat_25", "MODE to heat (sun), TEMP 25, FAN auto"),
    ("mode", "dry_25", "MODE to dry (water drop), TEMP 25"),
    ("mode", "fanmode_25", "MODE to fan only, TEMP 25"),
    ("mode", "auto_25", "MODE to auto, TEMP 25"),

    ("extra", "cool_25_turbo", "back to cool 25 fan auto, then press TURBO on"),
    ("extra", "cool_25_eco", "cool 25 fan auto, then press ECO on"),
    ("extra", "cool_25_sleep", "cool 25 fan auto, then press SLEEP on"),
    ("extra", "cool_25_mute", "cool 25 fan auto, then press MUTE on"),
    ("extra", "cool_25_swing", "cool 25 fan auto, then press SWING on"),
    ("extra", "cool_25_ifeel", "cool 25 fan auto, then press I FEEL on"),
    ("extra", "power_off", "press the power button to turn OFF"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None,
                    help="limit to group(s): base, fan, temp, mode, extra")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    plan = SCENARIOS
    if args.only:
        wanted = set(args.only) | {"base"}
        plan = [s for s in SCENARIOS if s[0] in wanted]

    if args.list:
        for group, label, instruction in SCENARIOS:
            print("  [{:<5}] {:<18} {}".format(group, label, instruction))
        return

    dev = rm_learn.connect()
    print("{} scenarios. Enter to capture each, 's' to skip, 'q' to stop.\n".format(len(plan)))

    done = 0
    for i, (group, label, instruction) in enumerate(plan, 1):
        print("-" * 68)
        print("[{}/{}] {}".format(i, len(plan), label))
        print("   SET: {}".format(instruction))
        answer = input("   enter when ready (s=skip, q=quit) > ").strip().lower()
        if answer == "q":
            break
        if answer == "s":
            print("   skipped\n")
            continue

        packet = rm_learn.learn_one(dev, args.timeout)
        if packet is None:
            print("   timed out, nothing learned\n")
            continue
        try:
            timings = rm_learn.decode_packet(packet)
        except ValueError as e:
            print("   {}\n".format(e))
            continue

        n = rm_learn.save(label, timings, packet.hex())
        print("\n   captured {} intervals, saved as '{}' #{}\n".format(
            len(timings), label, n))
        done += 1

    print("=" * 68)
    print("{} scenarios captured. Now run:".format(done))
    print("   .venv/bin/python tools/analyse.py")


if __name__ == "__main__":
    main()
