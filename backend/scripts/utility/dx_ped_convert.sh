#!/usr/bin/env bash
# dx_ped_convert.sh — Convert DX pedition listings with Unix epoch timestamps
# to human-readable dates.
#
# Input format  (comma-separated):
#   start_epoch,end_epoch,Description,Callsign,URL
#
# Output format:
#   Start Date | End Date | Description | Callsign | URL
#
# Usage:
#   chmod +x dx_ped_convert.sh
#   ./dx_ped_convert.sh listings.txt
#   ./dx_ped_convert.sh listings.txt > output.txt

set -euo pipefail

usage() {
    echo "Usage: $0 <input_file>"
    echo "  input_file  - text file with lines: epoch_start,epoch_end,desc,call,url"
    exit 1
}

# Convert a Unix epoch to a human-readable date.
# Tries GNU date first, then BSD date (macOS).
epoch_to_date() {
    local epoch="$1"
    if date --version &>/dev/null 2>&1; then
        # GNU date (Linux)
        date -d "@${epoch}" "+%Y-%m-%d %H:%M UTC" 2>/dev/null
    else
        # BSD date (macOS)
        date -r "${epoch}" "+%Y-%m-%d %H:%M UTC" 2>/dev/null
    fi
}

if [[ $# -lt 1 ]]; then
    usage
fi

INPUT="$1"

if [[ ! -f "$INPUT" ]]; then
    echo "Error: file not found: $INPUT" >&2
    exit 1
fi

printf "%-22s %-22s %-40s %-10s %s\n" \
    "START (UTC)" "END (UTC)" "DESCRIPTION" "CALLSIGN" "URL"
printf '%s\n' "$(printf '─%.0s' {1..120})"

line_num=0
while IFS= read -r line || [[ -n "$line" ]]; do
    line_num=$(( line_num + 1 ))

    # Skip blank lines and comment lines (starting with #)
    [[ -z "$line" || "$line" == \#* ]] && continue

    # Split on the first 4 commas only (URL may contain commas)
    IFS=',' read -r epoch_start epoch_end description callsign url <<< "$line"

    # Validate that epoch fields look numeric
    if ! [[ "$epoch_start" =~ ^[0-9]+$ ]] || ! [[ "$epoch_end" =~ ^[0-9]+$ ]]; then
        echo "  [line $line_num] WARNING: non-numeric epoch — skipping: $line" >&2
        continue
    fi

    start_date="$(epoch_to_date "$epoch_start")"
    end_date="$(epoch_to_date "$epoch_end")"

    printf "%-22s %-22s %-40s %-10s %s\n" \
        "$start_date" "$end_date" "$description" "$callsign" "$url"

done < "$INPUT"
