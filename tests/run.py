#!/usr/bin/env python3
"""Run every suite and report the total.

    python3 tests/run.py

They exercise bot.py directly with the network faked out - no mailbox, no API
key and no state file of your own is touched.
"""
import glob, os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
total = failed = 0
for path in sorted(glob.glob(os.path.join(here, "test_*.py"))):
    name = os.path.basename(path)
    out = subprocess.run([sys.executable, path], capture_output=True, text=True)
    line = next((l for l in out.stdout.splitlines() if "passed," in l), "no result")
    print("%-32s %s" % (name, line))
    if out.returncode and "passed," not in line:
        print(out.stdout[-2000:], out.stderr[-2000:])
    for l in out.stdout.splitlines():
        if l.strip().startswith("FAILED:"):
            print("   ", l.strip()); failed += 1
    if "passed," in line:
        total += int(line.split()[0])
print("-" * 52)
print("%d assertions, %d failures" % (total, failed))
sys.exit(1 if failed else 0)
