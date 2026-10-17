#!/usr/bin/env python3
"""
hc_bmp.py

Shared helpers for HamClock-compatible BMPv4 RGB565 top-down images.
"""

from __future__ import annotations
import struct
import numpy as np


def read_bmp_v4_rgb565_topdown(blob: bytes):
    if blob[0:2] != b"BM":
        raise ValueError("Not BMP")
    bfOffBits = struct.unpack_from("<I", blob, 10)[0]
    dib = struct.unpack_from("<I", blob, 14)[0]
    w = struct.unpack_from("<i", blob, 18)[0]
    h = struct.unpack_from("<i", blob, 22)[0]
    planes = struct.unpack_from("<H", blob, 26)[0]
    bpp = struct.unpack_from("<H", blob, 28)[0]
    comp = struct.unpack_from("<I", blob, 30)[0]

    if bfOffBits != 122 or dib != 108 or planes != 1 or bpp != 16 or comp != 3:
        raise ValueError(
            f"Unexpected BMP header off={bfOffBits} dib={dib} planes={planes} "
            f"bpp={bpp} comp={comp}"
        )
    if h >= 0:
        raise ValueError("Expected top-down BMP (negative height)")

    h0 = -h
    pix = blob[bfOffBits:bfOffBits + (w * h0 * 2)]
    if len(pix) != w * h0 * 2:
        raise ValueError("Truncated BMP pixel data")

    arr = np.frombuffer(pix, dtype="<u2").reshape((h0, w))
    return w, h0, arr


def rgb565_to_rgb888(arr565: np.ndarray) -> np.ndarray:
    a = arr565.astype(np.uint16)
    r = ((a >> 11) & 0x1F).astype(np.uint16)
    g = ((a >> 5) & 0x3F).astype(np.uint16)
    b = (a & 0x1F).astype(np.uint16)

    r8 = ((r * 255 + 15) // 31).astype(np.uint8)
    g8 = ((g * 255 + 31) // 63).astype(np.uint8)
    b8 = ((b * 255 + 15) // 31).astype(np.uint8)
    return np.stack([r8, g8, b8], axis=2)


def rgb888_to_rgb565(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"Expected HxWx3 RGB array, got shape {rgb.shape}")
    r = (rgb[:, :, 0].astype(np.uint16) >> 3) & 0x1F
    g = (rgb[:, :, 1].astype(np.uint16) >> 2) & 0x3F
    b = (rgb[:, :, 2].astype(np.uint16) >> 3) & 0x1F
    return (r << 11) | (g << 5) | b


def write_bmp_v4_rgb565_topdown(path: str, arr565: np.ndarray):
    if arr565.ndim != 2:
        raise ValueError(f"Expected HxW uint16 array, got shape {arr565.shape}")

    h0, w0 = arr565.shape
    bfOffBits = 122
    pix = arr565.astype("<u2").tobytes()
    bfSize = bfOffBits + len(pix)

    filehdr = struct.pack("<2sIHHI", b"BM", bfSize, 0, 0, bfOffBits)

    biSize = 108
    biWidth = w0
    biHeight = -h0  # top-down
    biPlanes = 1
    biBitCount = 16
    biCompression = 3  # BI_BITFIELDS
    biSizeImage = len(pix)

    rmask, gmask, bmask, amask = 0xF800, 0x07E0, 0x001F, 0x0000
    cstype = 0x73524742  # 'sRGB'
    endpoints = b"\x00" * 36
    gamma0 = b"\x00" * 12

    v4hdr = struct.pack(
        "<IiiHHIIIIII",
        biSize, biWidth, biHeight, biPlanes, biBitCount, biCompression,
        biSizeImage, 0, 0, 0, 0
    ) + struct.pack("<IIII", rmask, gmask, bmask, amask) \
      + struct.pack("<I", cstype) + endpoints + gamma0

    with open(path, "wb") as f:
        f.write(filehdr)
        f.write(v4hdr)
        f.write(pix)

