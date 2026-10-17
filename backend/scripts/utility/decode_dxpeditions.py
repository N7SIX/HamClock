#!/usr/bin/env python3
"""
decode_dxpeditions.py — Print a dxpeditions.txt file in human-readable form.

Usage:
    python3 decode_dxpeditions.py /path/to/dxpeditions.txt
    python3 decode_dxpeditions.py /opt/hamclock-backend/htdocs/ham/HamClock/dxpeds/dxpeditions.txt
"""

import sys
from datetime import datetime, timezone
from pathlib import Path


def ts(t: int) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime('%Y-%m-%d')


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path/to/dxpeditions.txt>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}")
        sys.exit(1)

    lines = path.read_text().splitlines()

    # Parse header (first 6 lines)
    if len(lines) < 6:
        print("Error: file too short to be a valid dxpeditions.txt")
        sys.exit(1)

    version   = lines[0].strip()
    source1   = lines[1].strip()
    source1url= lines[2].strip()
    source2   = lines[3].strip()
    source2url= lines[4].strip()

    print(f"Format version : {version}")
    print(f"Sources        : {source1} ({source1url})")
    print(f"                 {source2} ({source2url})")
    print()

    records = []
    for i, line in enumerate(lines[5:], start=7):
        line = line.strip()
        if not line:
            continue
        parts = line.split(',', 4)
        if len(parts) != 5:
            print(f"  [line {i}] Skipped (unexpected format): {line}")
            continue
        start, end, loc, call, url = parts
        records.append((int(start), int(end), loc, call, url))

    print(f"{'#':<4} {'Call':<12} {'Location':<28} {'Start':<12} {'End':<12} {'URL'}")
    print('-' * 110)

    now = int(datetime.now(tz=timezone.utc).timestamp())
    for i, (start, end, loc, call, url) in enumerate(records, start=1):
        active = start <= now <= end
        marker = ' *' if active else '  '
        print(f"{i:<4} {call:<12} {loc:<28} {ts(start):<12} {ts(end):<12} {url}{marker}")

    print()
    print(f"Total: {len(records)} expeditions  (* = currently active)")


if __name__ == '__main__':
    main()

