#!/usr/bin/env python3
"""
check_psk.py — Flag PSK reporter CSV lines that would cause HamClock sscanf failures.

HamClock sscanf format:
  "%ld,%6[^,],%11[^,],%6[^,],%11[^,],%7[^,],%ld,%f"
   t    s_grid  s_call  r_grid  r_call  mode   hz   snr

Field limits (chars before null terminator):
  s_grid : 6   (Maidenhead 4 or 6 char)
  s_call : 10  (ITU max callsign length; buffer is 11 = 10 + null)
  r_grid : 6
  r_call : 10
  mode   : 7

A single line exceeding these limits causes HamClock's goto out,
abandoning ALL remaining lines in the response.

Usage:
  python3 check_psk.py <file>
  curl "http://..." | python3 check_psk.py -
"""

import sys
import re

# HamClock sscanf field limits
LIMITS = {
    's_grid': 6,
    's_call': 10,
    'r_grid': 6,
    'r_call': 10,
    'mode':   7,
}

MAID_RE = re.compile(r'^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$')

def check_file(path):
    if path == '-':
        lines = sys.stdin.readlines()
    else:
        with open(path) as f:
            lines = f.readlines()

    total       = len(lines)
    bad_lines   = []
    first_fatal = None  # first line that would trigger goto out

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue

        parts = line.split(',')
        if len(parts) != 8:
            bad_lines.append((i, line, [f"wrong field count: {len(parts)} (expected 8)"]))
            if first_fatal is None:
                first_fatal = i
            continue

        t, s_grid, s_call, r_grid, r_call, mode, hz, snr = parts
        issues = []

        # Timestamp
        try:
            int(t)
        except ValueError:
            issues.append(f"t not integer: '{t}'")

        # Field length checks
        for name, value in [('s_grid', s_grid), ('s_call', s_call),
                             ('r_grid', r_grid), ('r_call', r_call),
                             ('mode',   mode)]:
            limit = LIMITS[name]
            if len(value) > limit:
                issues.append(f"{name} too long: '{value}' ({len(value)} > {limit})")

        # Maidenhead validity
        if not MAID_RE.match(s_grid):
            issues.append(f"s_grid invalid maidenhead: '{s_grid}'")
        if not MAID_RE.match(r_grid):
            issues.append(f"r_grid invalid maidenhead: '{r_grid}'")

        # Hz and snr numeric
        try:
            int(hz)
        except ValueError:
            issues.append(f"hz not integer: '{hz}'")
        try:
            float(snr)
        except ValueError:
            issues.append(f"snr not numeric: '{snr}'")

        if issues:
            bad_lines.append((i, line, issues))
            if first_fatal is None:
                first_fatal = i

    # Report
    print(f"{'='*60}")
    print(f"PSK Field Check Report")
    print(f"{'='*60}")
    print(f"Total lines  : {total}")
    print(f"Bad lines    : {len(bad_lines)}")
    print(f"Clean lines  : {total - len(bad_lines)}")
    if first_fatal:
        lost = total - first_fatal
        print(f"First fatal  : line {first_fatal}  ->  {lost} lines abandoned by HamClock goto out")
    print()

    if bad_lines:
        print(f"{'='*60}")
        print(f"Flagged Lines")
        print(f"{'='*60}")
        for lineno, raw, issues in bad_lines:
            print(f"Line {lineno:5d}: {raw}")
            for issue in issues:
                print(f"           *** {issue}")
        print()

    # Summary by issue type
    from collections import Counter
    issue_counts = Counter()
    for _, _, issues in bad_lines:
        for issue in issues:
            # Bucket by field name
            key = issue.split(':')[0].strip()
            issue_counts[key] += 1

    if issue_counts:
        print(f"{'='*60}")
        print(f"Issue Summary")
        print(f"{'='*60}")
        for issue, count in issue_counts.most_common():
            print(f"  {count:4d}  {issue}")

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '-'
    check_file(path)

