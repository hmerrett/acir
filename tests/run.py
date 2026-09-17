"""Run the host-side tests:  python3 tests/run.py"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import stubs

stubs.install()

import test_ir_tx
import test_ir_rx
import test_protocols

failures = 0
for mod in (test_ir_tx, test_ir_rx, test_protocols):
    print("=" * 62)
    print(mod.__name__)
    print("=" * 62)
    try:
        mod.main()
    except AssertionError as e:
        print("FAIL: {}".format(e))
        failures += 1
    print()

if failures:
    print("{} module(s) FAILED".format(failures))
    sys.exit(1)
print("all tests passed")
