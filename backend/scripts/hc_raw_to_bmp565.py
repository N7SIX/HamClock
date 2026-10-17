#!/usr/bin/env python3
"""
hc_raw_to_bmp565.py

CLI: convert raw RGB888 (packed) to HamClock-compatible BMPv4 RGB565 top-down.

Usage:
  hc_raw_to_bmp565.py --in raw.rgb --out out.bmp --width 660 --height 330
"""

from __future__ import annotations
import argparse
import numpy as np
from hc_bmp import rgb888_to_rgb565, write_bmp_v4_rgb565_topdown


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="infile", required=True, help="Input raw RGB888 file")
    p.add_argument("--out", required=True, help="Output BMP path")
    p.add_argument("--width", type=int, required=True)
    p.add_argument("--height", type=int, required=True)
    return p.parse_args()


def main():
    args = parse_args()
    W, H = args.width, args.height
    raw = open(args.infile, "rb").read()
    exp = W * H * 3
    if len(raw) != exp:
        raise SystemExit(f"ERROR: raw size {len(raw)} != expected {exp} ({W}x{H}x3)")
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape((H, W, 3))
    arr565 = rgb888_to_rgb565(rgb)
    write_bmp_v4_rgb565_topdown(args.out, arr565)


if __name__ == "__main__":
    main()

