#!/usr/bin/env python3
"""
poll_drap.py — Poll DRAP-S.bmp.z maps from HamClock every 5 minutes.
Captures Last-Modified headers only; files are discarded (sent to /dev/null).
Prints a live table after each full round, then a final report.

Usage:
    python3 poll_drap.py [--rounds N] [--interval SECONDS]

Defaults: 12 rounds (1 hour), 300-second interval (5 min).
"""

import subprocess
import re
import time
import argparse
from datetime import datetime, timezone

BASE_URL = "http://44.32.64.65/ham/HamClock/maps"

SIZES = [
    "660x330",
    "1320x660",
    "1980x990",
    "2640x1320",
    "3960x1980",
    "5280x2640",
    "5940x2970",
    "7920x3960",
]

VARIANTS = ["D", "N"]  # Day / Night


def build_urls():
    """Return list of (label, url) for every DRAP-S.bmp.z map."""
    entries = []
    for variant in VARIANTS:
        for size in SIZES:
            filename = f"map-{variant}-{size}-DRAP-S.bmp.z"
            url = f"{BASE_URL}/{filename}"
            label = f"{variant}-{size}"
            entries.append((label, url))
    return entries


def fetch_last_modified(url: str) -> str:
    """
    Run  curl -s -I  to get headers only, discard body.
    Returns the Last-Modified string, or an error token.
    """
    try:
        result = subprocess.run(
            ["curl", "-s", "-I", "--max-time", "30", url],
            capture_output=True,
            text=True,
            timeout=35,
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("last-modified:"):
                return line.split(":", 1)[1].strip()
        # If header missing, return HTTP status for debugging
        for line in result.stdout.splitlines():
            if line.startswith("HTTP/"):
                return f"NO-HEADER ({line.strip()})"
        return "NO-RESPONSE"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {e}"


def col_widths(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    return widths


def print_table(headers, rows, title=""):
    widths = col_widths(rows, headers)
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"

    if title:
        print(f"\n{'=' * len(sep)}")
        print(f"  {title}")
        print('=' * len(sep))
    print(sep)
    print(fmt.format(*headers))
    print(sep)
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))
    print(sep)


def run(rounds: int, interval: int):
    urls = build_urls()
    # results[label] = list of (poll_time_local, last_modified_str)
    results = {label: [] for label, _ in urls}

    print(f"\nHamClock DRAP-S Map Poller")
    print(f"  Maps   : {len(urls)} ({len(VARIANTS)} variants × {len(SIZES)} sizes)")
    print(f"  Rounds : {rounds}")
    print(f"  Interval: {interval}s ({interval/60:.1f} min)")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S local')}\n")

    for rnd in range(1, rounds + 1):
        round_start = datetime.now()
        print(f"\n{'─'*60}")
        print(f"  Round {rnd}/{rounds}  —  {round_start.strftime('%H:%M:%S')}")
        print(f"{'─'*60}")

        for label, url in urls:
            lm = fetch_last_modified(url)
            poll_time = datetime.now().strftime("%H:%M:%S")
            results[label].append((poll_time, lm))
            status = "✓" if "ERROR" not in lm and "TIMEOUT" not in lm and "NO-" not in lm else "✗"
            print(f"  {status} {label:<18}  {lm}")

        # --- Print rolling table after each round ---
        headers = ["Map", "Variant", "Size"] + [f"R{i}" for i in range(1, rnd + 1)]
        rows = []
        for label, _ in urls:
            variant = label.split("-")[0]
            size = label.split("-", 1)[1]
            lm_row = [r[1] for r in results[label]]
            rows.append([label, variant, size] + lm_row)

        print_table(headers, rows, title=f"Last-Modified timestamps — after round {rnd}")

        if rnd < rounds:
            next_time = time.time() + interval
            print(f"\n  ⏳  Waiting {interval}s until next poll …  (next at ~{datetime.fromtimestamp(next_time).strftime('%H:%M:%S')})")
            time.sleep(interval)

    # ------------------------------------------------------------------ #
    #  FINAL REPORT                                                        #
    # ------------------------------------------------------------------ #
    print(f"\n{'═'*70}")
    print("  FINAL REPORT")
    print(f"{'═'*70}")

    # For each map, show all observed Last-Modified values deduplicated
    change_summary = []
    for label, _ in urls:
        variant = label.split("-")[0]
        size = label.split("-", 1)[1]
        observations = [r[1] for r in results[label]]
        unique_lm = list(dict.fromkeys(observations))  # ordered unique
        changes = len(unique_lm) - 1
        change_summary.append((label, variant, size, changes, unique_lm[0], unique_lm[-1], "; ".join(unique_lm)))

    headers = ["Map", "V", "Size", "Changes", "First LM", "Last LM"]
    rows = [(r[0], r[1], r[2], r[3], r[4][:25], r[5][:25]) for r in change_summary]
    print_table(headers, rows, title="Summary of observed Last-Modified values")

    print("\n  Unique Last-Modified strings seen per map:")
    print()
    for row in change_summary:
        label, variant, size, changes, _, _, all_unique = row
        print(f"  {label:<20}  ({changes} change{'s' if changes != 1 else ''})")
        for lm in all_unique.split("; "):
            print(f"      → {lm}")

    print(f"\n  Poll completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poll HamClock DRAP-S maps for Last-Modified headers.")
    parser.add_argument("--rounds",   type=int, default=12,  help="Number of polling rounds (default: 12)")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between rounds (default: 300 = 5 min)")
    args = parser.parse_args()

    run(rounds=args.rounds, interval=args.interval)

