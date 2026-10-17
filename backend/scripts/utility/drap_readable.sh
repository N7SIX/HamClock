#!/bin/bash

# Usage: ./drap_readable.sh [file]
# Defaults to stats.txt in current dir if no arg given
# Shows timestamps in UTC and EST, highlights gaps in data
# Reports whether HC would accept or reject the file

INPUT="${1:-stats.txt}"

if [ ! -f "$INPUT" ]; then
    echo "ERROR: file not found: $INPUT" >&2
    exit 1
fi

# Color codes
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

# Gap thresholds in seconds
GAP_WARN=600      # 10 minutes - yellow
GAP_ALERT=1800    # 30 minutes - red

# HamClock DRAP constants (from spacewx.cpp)
DRAPDATA_INTERVAL=600        # 10 minutes in seconds
DRAPDATA_PERIOD=86400        # 24 hours in seconds
DRAPDATA_NPTS=$(( DRAPDATA_PERIOD / DRAPDATA_INTERVAL ))   # 144 slots
DRAPDATA_MAXMI=$(( DRAPDATA_NPTS / 10 ))                   # max missing: 14
DRAP_MINGOODI=$(( DRAPDATA_NPTS - 3600 / DRAPDATA_INTERVAL ))  # min index with good data: 138

NOW=$(date +%s)

# --- HC validity analysis (mirrors retrieveDRAP logic) ---
# Simulate the slot array: track which xi slots get filled
declare -A slot_filled

n_lines=0
maxi_good=0

while IFS= read -r line; do
    [ -z "$line" ] && continue
    epoch=$(echo "$line" | awk '{print $1}')
    [[ "$epoch" =~ ^[0-9]+$ ]] || continue
    n_lines=$(( n_lines + 1 ))
    age=$(( NOW - epoch ))
    xi=$(( DRAPDATA_NPTS * (DRAPDATA_PERIOD - age) / DRAPDATA_PERIOD ))
    if [ "$xi" -ge 0 ] && [ "$xi" -lt "$DRAPDATA_NPTS" ]; then
        slot_filled[$xi]=1
        if [ "$xi" -gt "$maxi_good" ]; then
            maxi_good=$xi
        fi
    fi
done < "$INPUT"

# Count missing slots (unfilled = missing)
n_missing=0
for (( i=0; i<DRAPDATA_NPTS; i++ )); do
    if [ -z "${slot_filled[$i]}" ]; then
        n_missing=$(( n_missing + 1 ))
    fi
done

# --- Transient invalidity detection ---
# Walk the in-range slots in order, tracking what maxi_good would have been
# at each point. A gap that pushes maxi_good below DRAP_MINGOODI would have
# caused HC to report invalid at that moment even if the file is valid now.
transient_invalid=0
transient_at=""
running_maxi=0
for (( i=0; i<DRAPDATA_NPTS; i++ )); do
    if [ -n "${slot_filled[$i]}" ]; then
        running_maxi=$i
    fi
    # Once we're past DRAP_MINGOODI in the slot scan, check if maxi_good
    # was lagging behind the minimum requirement
    if [ "$i" -gt "$DRAP_MINGOODI" ] && [ "$running_maxi" -lt "$DRAP_MINGOODI" ]; then
        transient_invalid=1
        transient_at="xi=$running_maxi (slot $i)"
        break
    fi
done

# Print HC validity report header
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║           HamClock DRAP Validity Analysis            ║${RESET}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════╣${RESET}"
echo -e "${BOLD}║${RESET} File:        $INPUT"
echo -e "${BOLD}║${RESET} Lines read:  $n_lines"
echo -e "${BOLD}║${RESET} Total slots: $DRAPDATA_NPTS  (${DRAPDATA_INTERVAL}s intervals over 24h)"
echo -e "${BOLD}║${RESET} Missing:     $n_missing / $DRAPDATA_NPTS  (max allowed: $DRAPDATA_MAXMI)"
echo -e "${BOLD}║${RESET} maxi_good:   $maxi_good  (min required: $DRAP_MINGOODI)"

# Verdict
if [ "$n_missing" -gt "$DRAPDATA_MAXMI" ] && [ "$maxi_good" -lt "$DRAP_MINGOODI" ]; then
    echo -e "${BOLD}║${RESET} ${RED}${BOLD}VERDICT:     INVALID — data too sparse AND too old${RESET}"
elif [ "$n_missing" -gt "$DRAPDATA_MAXMI" ]; then
    echo -e "${BOLD}║${RESET} ${RED}${BOLD}VERDICT:     INVALID — data too sparse${RESET}"
elif [ "$maxi_good" -lt "$DRAP_MINGOODI" ]; then
    echo -e "${BOLD}║${RESET} ${RED}${BOLD}VERDICT:     INVALID — data too old${RESET}"
else
    echo -e "${BOLD}║${RESET} ${GREEN}${BOLD}VERDICT:     VALID — HC should accept this file${RESET}"
fi

# Transient warning
if [ "$transient_invalid" -eq 1 ]; then
    echo -e "${BOLD}║${RESET} ${YELLOW}${BOLD}WARNING:     Gap caused transient invalidity (maxi_good stalled at ${transient_at})${RESET}"
    echo -e "${BOLD}║${RESET} ${YELLOW}             HC would have shown DRAP invalid until enough rows filled in after the gap${RESET}"
fi

echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

# --- Line-by-line output with gap highlighting ---
prev_epoch=""

while IFS= read -r line; do
    [ -z "$line" ] && continue

    epoch=$(echo "$line" | awk '{print $1}')
    [[ "$epoch" =~ ^[0-9]+$ ]] || { echo "$line"; continue; }

    # Convert to human readable UTC and EST
    utc=$(date -u -d "@$epoch" "+%Y-%m-%d %H:%M:%S UTC" 2>/dev/null \
       || date -u -r "$epoch" "+%Y-%m-%d %H:%M:%S UTC" 2>/dev/null)
    est=$(TZ="America/New_York" date -d "@$epoch" "+%H:%M:%S EST" 2>/dev/null \
       || TZ="America/New_York" date -r "$epoch" "+%H:%M:%S EST" 2>/dev/null)

    rest=$(echo "$line" | cut -d' ' -f2-)

    # Annotate whether this line falls in a valid HC slot
    age=$(( NOW - epoch ))
    xi=$(( DRAPDATA_NPTS * (DRAPDATA_PERIOD - age) / DRAPDATA_PERIOD ))
    if [ "$xi" -ge 0 ] && [ "$xi" -lt "$DRAPDATA_NPTS" ]; then
        slot_tag="${DIM}[xi=${xi}]${RESET}"
    else
        slot_tag="${RED}[OUT OF RANGE]${RESET}"
    fi

    # Check and display gap from previous line
    if [ -n "$prev_epoch" ]; then
        gap=$(( epoch - prev_epoch ))
        if [ "$gap" -gt "$GAP_ALERT" ]; then
            gap_min=$(( gap / 60 ))
            gap_hrs=$(echo "scale=1; $gap / 3600" | bc)
            echo -e "${RED}${BOLD}┌─ GAP: ${gap_hrs}h (${gap_min}m) ──────────────────────────────────┐${RESET}"
        elif [ "$gap" -gt "$GAP_WARN" ]; then
            gap_min=$(( gap / 60 ))
            echo -e "${YELLOW}╌╌ gap: ${gap_min}m ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌${RESET}"
        fi
    fi

    # Color the line based on gap and slot validity
    if [ "$xi" -lt 0 ] || [ "$xi" -ge "$DRAPDATA_NPTS" ]; then
        echo -e "${DIM}$epoch ($utc / $est) $rest${RESET} ${slot_tag}"
    elif [ -n "$prev_epoch" ] && [ $(( epoch - prev_epoch )) -gt "$GAP_ALERT" ]; then
        echo -e "${RED}│${RESET} ${CYAN}${BOLD}$epoch ($utc / $est)${RESET} $rest ${slot_tag}"
        echo -e "${RED}${BOLD}└──────────────────────────────────────────────────────${RESET}"
    elif [ -n "$prev_epoch" ] && [ $(( epoch - prev_epoch )) -gt "$GAP_WARN" ]; then
        echo -e "${YELLOW}$epoch ($utc / $est) $rest${RESET} ${slot_tag}"
    else
        echo -e "${DIM}$epoch${RESET} ${GREEN}($utc / $est)${RESET} $rest ${slot_tag}"
    fi

    prev_epoch="$epoch"

done < "$INPUT"

