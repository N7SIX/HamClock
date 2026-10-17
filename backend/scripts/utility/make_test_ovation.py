#!/usr/bin/env python3
"""
Generate a synthetic OVATION JSON for testing aurora map generation.
Produces val=100 along the auroral ovals (north and south) with realistic
lat/lon coverage matching the real OVATION format.

Usage:
    python3 make_test_ovation.py > ovation_test_100.json
    sudo bash update_aurora_maps.sh --ovation ovation_test_100.json --output /tmp/aurora_test
"""

import json
import math

# Real OVATION covers every lon 0-359, every lat -90 to +90
# but only has nonzero values near the auroral ovals
# We'll generate the full coordinate list with 0s everywhere
# except along the auroral ovals where we put val=100

# Auroral oval centers (approximate magnetic lat converted to geographic)
# Northern oval: ~67-70° geographic lat, peaks around 68°
# Southern oval: ~-67 to -70° geographic lat
NORTH_LAT = 68.0
SOUTH_LAT = -68.0
OVAL_WIDTH = 8.0   # degrees — how wide to make the oval
PEAK_VAL   = 100

def auroral_val(lat, oval_center, width, peak):
    """Gaussian-shaped value centered on oval_center."""
    dist = abs(lat - oval_center)
    if dist > width * 2:
        return 0
    val = peak * math.exp(-(dist**2) / (2 * (width/2)**2))
    return round(val, 1)

coordinates = []
for lon in range(0, 360):
    for lat in range(-90, 91):
        # North oval
        n_val = auroral_val(lat, NORTH_LAT, OVAL_WIDTH, PEAK_VAL)
        # South oval
        s_val = auroral_val(lat, SOUTH_LAT, OVAL_WIDTH, PEAK_VAL)
        val = max(n_val, s_val)
        coordinates.append([lon, lat, val])

output = {
    "Observation Time": "2026-01-01T00:00:00Z",
    "Forecast Time": "2026-01-01T00:30:00Z",
    "Data Format": "[Longitude, Latitude, Aurora]",
    "coordinates": coordinates
}

print(json.dumps(output))

