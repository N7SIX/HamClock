#!/usr/bin/env python3

import sys
import time

BZBT_NV = 150          # HamClock expects 150 rows
MAX_AGE_HOURS = -0.25 # newest must be within ~15 minutes

fname = sys.argv[1]

rows = []

with open(fname) as f:
    for ln in f:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        rows.append(int(parts[0]))

now = int(time.time())

print(f"Loaded rows: {len(rows)}")

if len(rows) != BZBT_NV:
    print("FAIL: wrong row count")
    sys.exit(1)

latest = rows[-1]

x_last = (latest - now) / 3600.0

print(f"Newest epoch : {latest}")
print(f"Now          : {now}")
print(f"x[last] hrs : {x_last:.3f}")

if x_last > MAX_AGE_HOURS:
    print("\nPASS: HamClock would accept this file")
else:
    print("\nFAIL: HamClock would reject as stale")


