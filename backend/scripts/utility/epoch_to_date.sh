#!/usr/bin/env bash

FILE="${1:-stats.txt}"

while IFS= read -r line; do
    epoch=$(echo "$line" | awk '{print $1}')
    rest=$(echo "$line" | cut -d' ' -f2-)

    human=$(date -u -d "@$epoch" "+%Y-%m-%d %H:%M:%S UTC")

    echo "$human $rest"
done < "$FILE"


