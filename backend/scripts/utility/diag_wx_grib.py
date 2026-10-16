#!/usr/bin/env python3
"""
diag_wx_grib.py

Diagnostic script to verify GFS GRIB2 data and render_wx_mb_map.py pipeline.

Usage:
  # Download a fresh GRIB and run diagnostics:
  python3 diag_wx_grib.py --download

  # Run against an existing GRIB file:
  python3 diag_wx_grib.py --grib /path/to/gfs.grb2

  # Check a specific lat/lon spot (default: Melbourne FL):
  python3 diag_wx_grib.py --download --lat 28.1 --lon -80.6 --label "Melbourne FL"

  # Also check actual BMP output pixel and reverse-engineer the alpha blend:
  python3 diag_wx_grib.py --download --bmp /opt/hamclock-backend/htdocs/ham/HamClock/maps/map-N-800x400-Wx-mB.bmp
  python3 diag_wx_grib.py --download --bmp /path/to/map.bmp --base /path/to/wxbase.bmp
"""

import argparse
import sys
import subprocess
from datetime import datetime, timezone, timedelta

import numpy as np

# ── Optional pygrib import ────────────────────────────────────────────────────
try:
    import pygrib
except ImportError:
    print("ERROR: pygrib not installed. Try: pip install pygrib --break-system-packages")
    sys.exit(1)

# ── Optional matplotlib import (for colormap check) ──────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.colors import LinearSegmentedColormap
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("WARNING: matplotlib not available — colormap checks will be skipped.\n")


# ── HamClock colormap (copied from render_wx_mb_map.py) ──────────────────────
def hamclock_temp_cmap():
    stops = [
        (-50, "#D0E4F8"),
        (-40, "#B0D4F8"),
        (-30, "#80BCF8"),
        (-20, "#70A4F8"),
        (-10, "#3874D0"),
        (  0, "#2060A8"),
        ( 10, "#009CD8"),
        ( 20, "#B8E4B0"),
        ( 30, "#F88C20"),
        ( 40, "#E80050"),
        ( 50, "#680028"),
    ]
    vals = np.array([v for v, _ in stops], dtype=np.float64)
    vals = (vals - vals.min()) / (vals.max() - vals.min())
    cols = [c for _, c in stops]
    return LinearSegmentedColormap.from_list("hamclock_celsius", list(zip(vals, cols)))


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    return f"#{r:02X}{g:02X}{b:02X}"


# ── BMP565 reader (matches hc_bmp.py logic) ───────────────────────────────────
def read_bmp565_pixel(bmp_path: str, px: int, py: int):
    """
    Read a single pixel from a HamClock BMP v4 RGB565 top-down file.
    Returns (R, G, B) as 0-255 integers, or None on error.
    """
    try:
        with open(bmp_path, "rb") as f:
            data = f.read()

        # BMP header: pixel data offset at bytes 10-13
        px_offset = int.from_bytes(data[10:14], "little")
        # DIB header: width at 18-21, height at 22-25 (negative = top-down)
        width  = int.from_bytes(data[18:22], "little")
        height_raw = int.from_bytes(data[22:26], "little", signed=True)
        height = abs(height_raw)

        if px >= width or py >= height:
            return None, width, height

        # RGB565: 2 bytes per pixel, rows padded to 4-byte boundary
        row_bytes = ((width * 2) + 3) & ~3
        offset = px_offset + py * row_bytes + px * 2
        word = int.from_bytes(data[offset:offset+2], "little")

        r5 = (word >> 11) & 0x1F
        g6 = (word >>  5) & 0x3F
        b5 =  word        & 0x1F

        # Expand to 8-bit using same method as hc_bmp.py rgb565_to_rgb888
        r8 = (r5 * 255 + 15) // 31
        g8 = (g6 * 255 + 31) // 63
        b8 = (b5 * 255 + 15) // 31

        return (r8, g8, b8), width, height
    except Exception as e:
        return None, 0, 0


def latlon_to_pixel(lat: float, lon: float, width: int, height: int):
    """
    Convert lat/lon to pixel coordinates for an equirectangular
    -180/180 x -90/90 map of given pixel dimensions.
    """
    # lon: -180..180 → 0..width
    # lat: 90..-90   → 0..height  (top = 90N)
    px = int((lon + 180.0) / 360.0 * width)
    py = int((90.0 - lat)  / 180.0 * height)
    px = max(0, min(px, width  - 1))
    py = max(0, min(py, height - 1))
    return px, py


def alpha_blend(fg, bg, alpha=0.72):
    """Simulate matplotlib imshow alpha blend: fg*alpha + bg*(1-alpha)."""
    return tuple(int(f * alpha + b * (1.0 - alpha)) for f, b in zip(fg, bg))


def reverse_alpha(blended, fg, alpha=0.72):
    """
    Solve for the base (bg) color given blended and fg:
      blended = fg*alpha + bg*(1-alpha)
      bg = (blended - fg*alpha) / (1-alpha)
    Returns (R,G,B) clamped to 0-255.
    """
    bg = []
    for bl, f in zip(blended, fg):
        val = (bl - f * alpha) / (1.0 - alpha)
        bg.append(int(max(0, min(255, round(val)))))
    return tuple(bg)


def cmap_color_at(temp_c, cmap, tmin=-40.0, tmax=50.0):
    """Return (R,G,B) 0-255 for a given Celsius value using the HamClock cmap."""
    t = np.clip((temp_c - tmin) / (tmax - tmin), 0.0, 1.0)
    rgba = cmap(t)
    return tuple(int(x * 255) for x in rgba[:3])


# ── NOMADS download (mirrors pick_and_download logic from the shell script) ───
NOMADS_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"

def build_nomads_url(ymd: str, hh: str) -> str:
    file_ = f"gfs.t{hh}z.pgrb2.0p25.f000"
    dir_  = f"%2Fgfs.{ymd}%2F{hh}%2Fatmos"
    return (
        f"{NOMADS_FILTER}?file={file_}"
        f"&lev_mean_sea_level=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on"
        f"&var_PRMSL=on&var_UGRD=on&var_VGRD=on&var_TMP=on"
        f"&leftlon=0&rightlon=359.75&toplat=90&bottomlat=-90"
        f"&dir={dir_}"
    )

def download_latest_grib(out_path: str) -> bool:
    """Try the last 4 GFS cycles (6-hourly, offset 2h for availability)."""
    MAP_INTERVAL = 6
    MAP_READY    = 2
    now = datetime.now(timezone.utc) - timedelta(hours=MAP_READY)
    hour_aligned = (now.hour // MAP_INTERVAL) * MAP_INTERVAL
    base = now.replace(hour=hour_aligned, minute=0, second=0, microsecond=0)

    for i in range(4):
        cycle = base - timedelta(hours=MAP_INTERVAL * i)
        ymd = cycle.strftime("%Y%m%d")
        hh  = cycle.strftime("%H")
        url = build_nomads_url(ymd, hh)
        print(f"  Trying GFS {ymd} {hh}Z ...")
        result = subprocess.run(
            ["curl", "-fs", "-A", "open-hamclock-backend/diag/1.0",
             "--retry", "2", "--retry-delay", "2", url, "-o", out_path],
            capture_output=True
        )
        if result.returncode == 0:
            print(f"  Downloaded: GFS {ymd} {hh}Z -> {out_path}")
            return True
        else:
            print(f"  Failed (curl exit {result.returncode})")
    return False


# ── GRIB field finder (mirrors pick_required) ─────────────────────────────────
def find_field(msgs, short_names, type_of_level=None, level=None):
    for sn in short_names:
        for g in msgs:
            if getattr(g, "shortName", None) != sn:
                continue
            if type_of_level and getattr(g, "typeOfLevel", None) != type_of_level:
                continue
            if level is not None and getattr(g, "level", None) != level:
                continue
            return g
    return None


# ── Diagnostic sections ───────────────────────────────────────────────────────
def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def ok(msg):   print(f"  [OK]   {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def err(msg):  print(f"  [ERR]  {msg}")


def check_inventory(msgs):
    section("GRIB Inventory")
    print(f"  Total messages: {len(msgs)}")
    for i, g in enumerate(msgs, 1):
        try:
            print(f"  {i:02d}: shortName={g.shortName!r:8s} typeOfLevel={g.typeOfLevel!r:25s} "
                  f"level={g.level!r:5} name={g.name!r}")
        except Exception as e:
            print(f"  {i:02d}: <error reading metadata: {e}>")


def check_required_fields(msgs):
    section("Required Fields Check")
    fields = [
        ("2m Temperature",         ["2t","tmp"],    "heightAboveGround", 2),
        ("Mean Sea Level Pressure", ["prmsl","msl"], "meanSea",           None),
        ("10m U Wind",             ["10u","ugrd"],  "heightAboveGround", 10),
        ("10m V Wind",             ["10v","vgrd"],  "heightAboveGround", 10),
    ]
    all_ok = True
    found = {}
    for label, snames, tol, lev in fields:
        g = find_field(msgs, snames, tol, lev)
        if g:
            ok(f"{label}: shortName={g.shortName!r} typeOfLevel={g.typeOfLevel!r} level={g.level}")
            found[label] = g
        else:
            err(f"{label}: NOT FOUND (tried shortNames={snames})")
            all_ok = False
    return found, all_ok


def check_value_ranges(found):
    section("Value Range Sanity Check")

    g_t = found.get("2m Temperature")
    if g_t:
        t_k = g_t.values
        t_c = t_k - 273.15
        print(f"  Temperature (K):  min={t_k.min():.2f}  max={t_k.max():.2f}  mean={t_k.mean():.2f}")
        print(f"  Temperature (°C): min={t_c.min():.1f}  max={t_c.max():.1f}  mean={t_c.mean():.1f}")
        if 180 < t_k.min() < 340 and 180 < t_k.max() < 340:
            ok("Temperature Kelvin range looks realistic")
        else:
            warn("Temperature range looks suspicious — check units")

    g_p = found.get("Mean Sea Level Pressure")
    if g_p:
        pr_pa = g_p.values
        pr_hpa = pr_pa / 100.0
        print(f"  Pressure (Pa):  min={pr_pa.min():.0f}  max={pr_pa.max():.0f}")
        print(f"  Pressure (hPa): min={pr_hpa.min():.1f}  max={pr_hpa.max():.1f}")
        if 900 < pr_hpa.min() and pr_hpa.max() < 1100:
            ok("Pressure hPa range looks realistic (900-1100 hPa)")
        else:
            warn("Pressure range looks suspicious")

    g_u = found.get("10m U Wind")
    g_v = found.get("10m V Wind")
    if g_u and g_v:
        spd = np.hypot(g_u.values, g_v.values)
        print(f"  Wind speed (m/s): min={spd.min():.1f}  max={spd.max():.1f}  mean={spd.mean():.1f}")
        if spd.max() < 200:
            ok("Wind speed range looks realistic")
        else:
            warn("Wind speed max looks very high — possible unit issue")


def check_spot(found, lat, lon, label):
    section(f"Spot Check: {label} ({lat:.2f}°N, {lon:.2f}°E)")

    g_t = found.get("2m Temperature")
    g_p = found.get("Mean Sea Level Pressure")
    g_u = found.get("10m U Wind")
    g_v = found.get("10m V Wind")

    if not g_t:
        warn("No temperature field available for spot check")
        return

    lats2d, lons2d = g_t.latlons()
    lats1d = lats2d[:, 0]
    lons1d = lons2d[0, :]

    # Convert input lon to 0-360 if needed (GFS native is 0-360)
    lon_gfs = lon % 360.0

    lat_idx = int(np.argmin(np.abs(lats1d - lat)))
    lon_idx = int(np.argmin(np.abs(lons1d - lon_gfs)))

    actual_lat = lats1d[lat_idx]
    actual_lon = lons1d[lon_idx]
    print(f"  Nearest grid point: ({actual_lat:.2f}°N, {actual_lon:.2f}°E)  "
          f"[row={lat_idx}, col={lon_idx}]")

    if g_t:
        t_c = g_t.values[lat_idx, lon_idx] - 273.15
        print(f"  2m Temperature : {t_c:.1f}°C")
        if HAS_MPL:
            cmap = hamclock_temp_cmap()
            r, g_ch, b = cmap_color_at(t_c, cmap)
            print(f"  Colormap color : RGB({r},{g_ch},{b})  #{r:02X}{g_ch:02X}{b:02X}")

    if g_p:
        pr_hpa = g_p.values[lat_idx, lon_idx] / 100.0
        pr_inhg = pr_hpa * 0.02953
        print(f"  MSLP           : {pr_hpa:.1f} hPa  /  {pr_inhg:.2f} inHg")

    if g_u and g_v:
        u = g_u.values[lat_idx, lon_idx]
        v = g_v.values[lat_idx, lon_idx]
        spd = np.hypot(u, v)
        deg = (270 - np.degrees(np.arctan2(v, u))) % 360
        print(f"  10m Wind       : {spd:.1f} m/s  from {deg:.0f}°  (u={u:.1f}, v={v:.1f})")


def check_bmp_pixel(bmp_path, base_bmp_path, lat, lon, label, temp_c):
    """
    Read the actual rendered BMP at the spot lat/lon, compare to predicted
    color, and reverse-engineer what the base map color must have been.
    """
    section(f"BMP Pixel Check: {label} ({lat:.2f}°N, {lon:.2f}°E)")

    if not HAS_MPL:
        warn("matplotlib not available — skipping BMP pixel check")
        return

    # ── Read output BMP ───────────────────────────────────────────────────────
    pixel, W, H = read_bmp565_pixel(bmp_path, 0, 0)  # dummy read to get size
    if W == 0:
        err(f"Could not open BMP: {bmp_path}")
        return

    px, py = latlon_to_pixel(lat, lon, W, H)
    print(f"  BMP size       : {W}x{H}")
    print(f"  Pixel coords   : ({px}, {py})")

    actual, _, _ = read_bmp565_pixel(bmp_path, px, py)
    if actual is None:
        err(f"Pixel ({px},{py}) out of range for {W}x{H} BMP")
        return

    print(f"  Actual BMP pixel : RGB{actual}  {rgb_to_hex(*actual)}")

    # ── Predicted colormap color ──────────────────────────────────────────────
    cmap = hamclock_temp_cmap()
    fg = cmap_color_at(temp_c, cmap)
    blended       = alpha_blend(fg, (0, 0, 0), alpha=0.72)
    predicted_565 = rgb888_to_565_and_back(*blended)
    print(f"  Colormap (fg)    : RGB{fg}  {rgb_to_hex(*fg)}  ({temp_c:.1f}°C)")
    print(f"  Predicted blend  : RGB{predicted_565}  {rgb_to_hex(*predicted_565)}  "
          f"(fg*0.72 over black + 565)")

    # ── BGR swap test ─────────────────────────────────────────────────────────
    print()
    print("  BGR swap test (checking if R↔B are swapped in BMP read/write):")
    actual_bgr = (actual[2], actual[1], actual[0])   # swap R and B
    diff_rgb = tuple(abs(a - p) for a, p in zip(actual,     predicted_565))
    diff_bgr = tuple(abs(a - p) for a, p in zip(actual_bgr, predicted_565))
    print(f"    As RGB : {rgb_to_hex(*actual)}     "
          f"dR={diff_rgb[0]:3d} dG={diff_rgb[1]:3d} dB={diff_rgb[2]:3d}  "
          f"max={max(diff_rgb)}")
    print(f"    As BGR : {rgb_to_hex(*actual_bgr)}     "
          f"dR={diff_bgr[0]:3d} dG={diff_bgr[1]:3d} dB={diff_bgr[2]:3d}  "
          f"max={max(diff_bgr)}")
    improvement = max(diff_rgb) - max(diff_bgr)
    if improvement >= 20:
        warn(f"BGR interpretation is {improvement} counts closer to prediction — "
             f"BMP is likely stored as BGR565, not RGB565. "
             f"Check hc_bmp.py channel order in rgb888_to_rgb565 / rgb565_to_rgb888.")
    elif improvement >= 5:
        print(f"    BGR slightly closer ({improvement} counts) — inconclusive at single pixel")
    else:
        ok("RGB interpretation matches better — channel order looks correct")

    # ── Read base BMP pixel if provided ───────────────────────────────────────
    if base_bmp_path:
        base_pixel, bW, bH = read_bmp565_pixel(base_bmp_path, 0, 0)
        bpx, bpy = latlon_to_pixel(lat, lon, bW, bH)
        base_pixel, _, _ = read_bmp565_pixel(base_bmp_path, bpx, bpy)
        if base_pixel:
            print()
            print(f"  Base BMP pixel   : RGB{base_pixel}  {rgb_to_hex(*base_pixel)}")
            predicted_with_base = alpha_blend(fg, base_pixel, alpha=0.72)
            pred_with_base_565  = rgb888_to_565_and_back(*predicted_with_base)
            print(f"  Pred (fg+base)   : RGB{pred_with_base_565}  "
                  f"{rgb_to_hex(*pred_with_base_565)}  (fg*0.72 + base*0.28 + 565)")
            diff2 = tuple(abs(a - p) for a, p in zip(actual, pred_with_base_565))
            print(f"  Diff (fg+base)   : dR={diff2[0]}  dG={diff2[1]}  dB={diff2[2]}  "
                  f"max={max(diff2)}")
            if max(diff2) <= 8:
                ok("Predicted color with base matches actual within 565 tolerance")
            elif max(diff2) <= 20:
                warn(f"Minor diff with base ({max(diff2)}) — may be border overlay or boost")
            else:
                warn(f"Larger diff with base ({max(diff2)}) — check border overlay / boost")
        else:
            warn("Could not read base BMP pixel")


def check_neighborhood(found, bmp_path, lat, lon, label, radius=2):
    """
    Sample a grid of GRIB temperature values and (optionally) BMP pixels
    around the spot to reveal coastline blending effects.
    radius = number of GRIB grid steps each direction (0.25° each).
    """
    section(f"Neighborhood Scan: {label} ±{radius} GRIB steps (~{radius*0.25:.2f}°)")

    g_t = found.get("2m Temperature")
    if not g_t:
        warn("No temperature field — skipping neighborhood scan")
        return

    if not HAS_MPL:
        warn("matplotlib not available — skipping neighborhood scan")
        return

    lats2d, lons2d = g_t.latlons()
    lats1d = lats2d[:, 0]
    lons1d = lons2d[0, :]
    lon_gfs = lon % 360.0

    clat = int(np.argmin(np.abs(lats1d - lat)))
    clon = int(np.argmin(np.abs(lons1d - lon_gfs)))

    cmap = hamclock_temp_cmap()

    # ── BMP setup ─────────────────────────────────────────────────────────────
    bmp_ok = False
    W = H = 0
    if bmp_path:
        _, W, H = read_bmp565_pixel(bmp_path, 0, 0)
        bmp_ok = (W > 0)

    # ── Header ────────────────────────────────────────────────────────────────
    print(f"  Center GRIB cell: row={clat} col={clon}  "
          f"({lats1d[clat]:.2f}°N, {lons1d[clon]:.2f}°E → "
          f"{lons1d[clon]-360:.2f}°E)")
    print()

    if bmp_ok:
        print(f"  dR/dG/dB = actual BMP pixel vs. predicted (cmap blended*0.72 over black + 565 round-trip)")
        print(f"  Tolerance: ok=≤8  ~ok=≤20  WARN/>20  ANOMALY/>60  ISOBAR=near-white pixel")
        print()
        print(f"  {'Lat':>6} {'Lon':>7}  {'Temp':>7}  {'Pred565':>8}  "
              f"{'Actual':>8}  {'dR':>4} {'dG':>4} {'dB':>4}  {'MaxErr':>7}  Flag")
        print(f"  {'-'*95}")
    else:
        print(f"  {'Lat':>6} {'Lon':>7}  {'Temp':>7}  {'CmapHex':>8}  "
              f"{'Pred(blend+565)':>16}  Note")
        print(f"  {'-'*65}")

    t_vals    = []
    anomalies = []
    bgr_better_count = 0   # how many pixels are closer when R↔B swapped
    rgb_better_count = 0

    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            r = clat + dr
            c = (clon + dc) % len(lons1d)

            cell_lat      = lats1d[r]
            cell_lon      = lons1d[c]
            cell_lon_disp = cell_lon if cell_lon <= 180 else cell_lon - 360

            t_c = g_t.values[r, c] - 273.15
            t_vals.append(t_c)

            fg            = cmap_color_at(t_c, cmap)
            blended       = alpha_blend(fg, (0, 0, 0), alpha=0.72)
            predicted_565 = rgb888_to_565_and_back(*blended)

            center_tag = " <--CENTER" if (dr == 0 and dc == 0) else ""

            if bmp_ok:
                bpx, bpy = latlon_to_pixel(cell_lat, cell_lon_disp, W, H)
                bpix, _, _ = read_bmp565_pixel(bmp_path, bpx, bpy)
                if bpix:
                    diff    = tuple(abs(a - b) for a, b in zip(bpix, predicted_565))
                    max_err = max(diff)

                    # BGR vote: does swapping R↔B bring us closer?
                    bpix_bgr   = (bpix[2], bpix[1], bpix[0])
                    diff_bgr   = tuple(abs(a - b) for a, b in zip(bpix_bgr, predicted_565))
                    max_bgr    = max(diff_bgr)
                    # Only count non-isobar pixels for the vote
                    is_isobar  = bpix[0] > 200 and bpix[1] > 200 and bpix[2] > 200
                    if not is_isobar:
                        if max_bgr < max_err - 5:
                            bgr_better_count += 1
                        elif max_err < max_bgr - 5:
                            rgb_better_count += 1

                    if max_err <= 8:
                        flag = "ok"
                    elif max_err <= 20:
                        flag = "~ok"
                    elif is_isobar:
                        flag = "ISOBAR/TEXT"
                        anomalies.append((cell_lat, cell_lon_disp, max_err, "isobar/text pixel"))
                    elif max_err > 60:
                        flag = "ANOMALY"
                        anomalies.append((cell_lat, cell_lon_disp, max_err, "large unexplained error"))
                    else:
                        flag = "WARN"
                        anomalies.append((cell_lat, cell_lon_disp, max_err, f"err={max_err}"))

                    print(f"  {cell_lat:>6.2f} {cell_lon_disp:>7.2f}  "
                          f"{t_c:>6.1f}°C  "
                          f"{rgb_to_hex(*predicted_565):>8}  "
                          f"{rgb_to_hex(*bpix):>8}  "
                          f"{diff[0]:>4} {diff[1]:>4} {diff[2]:>4}  "
                          f"{max_err:>7}  {flag}{center_tag}")
                else:
                    print(f"  {cell_lat:>6.2f} {cell_lon_disp:>7.2f}  "
                          f"{t_c:>6.1f}°C  "
                          f"{rgb_to_hex(*predicted_565):>8}  "
                          f"[pixel OOB]{center_tag}")
            else:
                print(f"  {cell_lat:>6.2f} {cell_lon_disp:>7.2f}  "
                      f"{t_c:>6.1f}°C  "
                      f"{rgb_to_hex(*fg):>8}  "
                      f"{rgb_to_hex(*predicted_565):>16}  {center_tag}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    t_arr = np.array(t_vals)
    print(f"  Neighborhood temp range: {t_arr.min():.1f}°C – {t_arr.max():.1f}°C  "
          f"(spread={t_arr.max()-t_arr.min():.1f}°C)")
    if t_arr.max() - t_arr.min() > 5.0:
        warn(f"Temp spread {t_arr.max()-t_arr.min():.1f}°C — bilinear resize mixing "
             "temps across boundary (coastline likely nearby)")
    else:
        ok(f"Temp spread {t_arr.max()-t_arr.min():.1f}°C — bilinear blending minor")

    if bmp_ok:
        n_cells = (2*radius+1)**2
        n_anom  = len(anomalies)
        n_ok    = n_cells - n_anom
        if n_anom == 0:
            ok(f"All {n_cells} sampled pixels match predicted blend+565 within tolerance")
        else:
            print(f"  Pixel accuracy: {n_ok}/{n_cells} cells clean  |  {n_anom} anomalies:")
            for a_lat, a_lon, a_err, a_note in anomalies:
                print(f"    ({a_lat:.2f}°N, {a_lon:.2f}°E)  max_err={a_err}  {a_note}")
            isobar_count = sum(1 for _, _, _, n in anomalies if "isobar" in n)
            large_count  = sum(1 for _, _, e, _ in anomalies if e > 60)
            if isobar_count:
                warn(f"{isobar_count} near-white pixel(s) — isobar label text landing "
                     "on sampled cells (expected, not a pipeline error)")
            real_issues = large_count - isobar_count
            if real_issues > 0:
                warn(f"{real_issues} pixel(s) with large unexplained error — "
                     "possible border overlay, bilinear coast blending, or pipeline issue")

    # ── BGR swap vote ─────────────────────────────────────────────────────────
    if bmp_ok:
        total_votes = bgr_better_count + rgb_better_count
        print()
        print(f"  BGR swap vote (non-isobar pixels only):")
        print(f"    BGR closer to prediction : {bgr_better_count}")
        print(f"    RGB closer to prediction : {rgb_better_count}")
        print(f"    Inconclusive (tie ±5)    : {(2*radius+1)**2 - total_votes - sum(1 for _,_,_,n in anomalies if 'isobar' in n)}")
        if total_votes > 0:
            bgr_pct = 100 * bgr_better_count / total_votes
            if bgr_pct >= 75:
                warn(f"STRONG BGR SIGNAL ({bgr_pct:.0f}% of decisive pixels better as BGR) — "
                     f"BMP is almost certainly stored BGR565. "
                     f"Fix: swap R↔B in hc_bmp.py rgb565_to_rgb888() and rgb888_to_rgb565().")
            elif bgr_pct >= 55:
                warn(f"Moderate BGR signal ({bgr_pct:.0f}%) — likely BGR, worth investigating hc_bmp.py")
            else:
                ok(f"No BGR swap signal ({bgr_pct:.0f}% BGR) — channel order looks correct")


def check_longitude_roll(found):
    section("Longitude Roll Check (0-360 → -180/180)")
    g_t = found.get("2m Temperature")
    if not g_t:
        warn("No temperature field — skipping roll check")
        return

    _, lons2d = g_t.latlons()
    lons1d = lons2d[0, :]
    print(f"  Native GFS lons: {lons1d[0]:.2f} → {lons1d[-1]:.2f} ({len(lons1d)} cols)")
    roll_col = int(np.argmin(np.abs(lons1d - 180.0)))
    print(f"  Roll column (lon≈180°): {roll_col}  (col {roll_col} = {lons1d[roll_col]:.2f}°)")
    if 710 < roll_col < 730:
        ok("Roll column is in expected range (~720 for 0.25° GFS)")
    else:
        warn(f"Roll column {roll_col} is outside expected range 710-730")


def rgb888_to_565_and_back(r, g, b, method="division"):
    """
    Round-trip RGB888 through RGB565 encoding, return expanded RGB888.
    method="division"    — matches hc_bmp.py: (x*255+bias)//max
    method="bitreplica"  — matches ImageMagick/browsers: (x<<shift)|(x>>shift)
    """
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    if method == "division":
        # Matches hc_bmp.py rgb565_to_rgb888 exactly
        r8 = (r5 * 255 + 15) // 31
        g8 = (g6 * 255 + 31) // 63
        b8 = (b5 * 255 + 15) // 31
    else:
        # Bit-replication: used by ImageMagick, browsers, matplotlib
        r8 = (r5 << 3) | (r5 >> 2)
        g8 = (g6 << 2) | (g6 >> 4)
        b8 = (b5 << 3) | (b5 >> 2)
    return r8, g8, b8


def check_colormap_stops():
    section("Colormap Sanity Check + RGB565 Quantization Analysis")
    if not HAS_MPL:
        warn("matplotlib not available — skipping")
        return

    cmap = hamclock_temp_cmap()
    test_temps = [-40, -30, -20, -10, 0, 10, 20, 28, 30, 36, 40, 50]

    # ── Raw colormap colors ───────────────────────────────────────────────────
    print(f"  Raw colormap colors (pre-565):")
    print(f"  {'Temp(°C)':>10}  {'R':>4} {'G':>4} {'B':>4}  Hex")
    print(f"  {'-'*40}")
    for t in test_temps:
        r, g, b = cmap_color_at(t, cmap)
        print(f"  {t:>10}°C  {r:>4} {g:>4} {b:>4}  #{r:02X}{g:02X}{b:02X}")

    # ── Division vs bit-replication comparison ───────────────────────────────
    print()
    print(f"  Expansion method comparison (hc_bmp.py division vs bit-replication):")
    print(f"  {'Temp':>8}  {'Raw':>8}  {'Division':>10}  {'BitReplic':>10}  "
          f"{'Diff':>6}  Note")
    print(f"  {'-'*65}")
    max_method_diff = 0
    for t in test_temps:
        r, g, b   = cmap_color_at(t, cmap)
        bl        = alpha_blend((r,g,b), (0,0,0), alpha=0.72)
        div_565   = rgb888_to_565_and_back(*bl, method="division")
        bit_565   = rgb888_to_565_and_back(*bl, method="bitreplica")
        diff      = max(abs(a-b2) for a,b2 in zip(div_565, bit_565))
        max_method_diff = max(max_method_diff, diff)
        note = "same" if diff == 0 else f"delta={diff}"
        print(f"  {t:>7}°C  "
              f"{rgb_to_hex(*bl):>8}  "
              f"{rgb_to_hex(*div_565):>10}  "
              f"{rgb_to_hex(*bit_565):>10}  "
              f"{diff:>6}  {note}")
    print()
    if max_method_diff <= 2:
        ok(f"Division and bit-replication methods agree within {max_method_diff} counts — "
           "expansion method is NOT the source of the color discrepancy")
        warn("BGR channel swap is still the most likely cause of the observed errors. "
             "Re-examine hc_bmp.py and the rendering pipeline for a BGR/RGB mismatch.")
    else:
        warn(f"Methods differ by up to {max_method_diff} counts — "
             "switching hc_bmp.py to bit-replication would bring it in line with "
             "ImageMagick/matplotlib. But this alone does not explain errors of 50-80 counts.")
    print()
    print(f"  RGB565 round-trip quantization loss:")
    print(f"  {'Temp':>8}  {'Original':>9}  {'After565':>9}  "
          f"{'dR':>4} {'dG':>4} {'dB':>4}  {'MaxErr':>7}  Note")
    print(f"  {'-'*70}")

    max_b_err = 0
    max_g_err = 0
    max_r_err = 0
    worst_t   = None
    worst_err = 0

    for t in test_temps:
        r, g, b   = cmap_color_at(t, cmap)
        r2, g2, b2 = rgb888_to_565_and_back(r, g, b)
        dr = abs(r - r2)
        dg = abs(g - g2)
        db = abs(b - b2)
        mx = max(dr, dg, db)

        # Track worst offenders per channel
        if db > max_b_err: max_b_err = db
        if dg > max_g_err: max_g_err = dg
        if dr > max_r_err: max_r_err = dr
        if mx > worst_err:
            worst_err = mx
            worst_t   = t

        note = ""
        if db >= 6:  note += "B-crush "
        if dg >= 4:  note += "G-crush "
        if dr >= 4:  note += "R-crush "
        if not note: note  = "clean"

        print(f"  {t:>7}°C  "
              f"#{r:02X}{g:02X}{b:02X}      "
              f"#{r2:02X}{g2:02X}{b2:02X}      "
              f"{dr:>4} {dg:>4} {db:>4}  {mx:>7}  {note}")

    print()
    print(f"  Max channel errors across all stops:")
    print(f"    Red   max loss: {max_r_err} counts")
    print(f"    Green max loss: {max_g_err} counts  "
          f"(6-bit green = {64} levels, step={4})")
    print(f"    Blue  max loss: {max_b_err} counts  "
          f"(5-bit blue  = {32} levels, step={8})")

    print()
    if max_b_err >= 6:
        warn(f"Blue channel has worst quantization loss ({max_b_err} counts max) — "
             "5-bit blue only has 32 levels (step size=8), so any blue value not "
             "divisible by 8 loses up to 7 counts. This is EXPECTED for RGB565 "
             "and explains systematic dB errors in the neighborhood scan.")
    else:
        ok("Blue quantization loss is within normal range")

    if max_g_err >= 4:
        warn(f"Green channel loss ({max_g_err} counts) — 6-bit green has step size=4")
    else:
        ok("Green quantization loss is within normal range")

    # ── Alpha-blend + 565 combined error ─────────────────────────────────────
    print()
    print(f"  Combined alpha-blend (over black, alpha=0.72) + 565 round-trip error:")
    print(f"  {'Temp':>8}  {'Blended':>8}  {'Blend+565':>10}  "
          f"{'dR':>4} {'dG':>4} {'dB':>4}  Note")
    print(f"  {'-'*60}")

    for t in test_temps:
        r, g, b      = cmap_color_at(t, cmap)
        bl           = alpha_blend((r, g, b), (0, 0, 0), alpha=0.72)
        bl2          = rgb888_to_565_and_back(*bl)
        dr = abs(bl[0] - bl2[0])
        dg = abs(bl[1] - bl2[1])
        db = abs(bl[2] - bl2[2])
        note = "clean" if max(dr,dg,db) < 4 else f"max_err={max(dr,dg,db)}"
        print(f"  {t:>7}°C  "
              f"#{bl[0]:02X}{bl[1]:02X}{bl[2]:02X}      "
              f"#{bl2[0]:02X}{bl2[1]:02X}{bl2[2]:02X}        "
              f"{dr:>4} {dg:>4} {db:>4}  {note}")

    print()
    ok("RGB565 quantization analysis complete")


# ── Main ──────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Diagnose GFS GRIB + HamClock Wx pipeline")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--grib",     help="Path to existing GFS GRIB2 file")
    grp.add_argument("--download", action="store_true",
                     help="Download latest GFS subset from NOMADS first")
    p.add_argument("--out",   default="/tmp/diag_gfs.grb2",
                   help="Where to save downloaded GRIB (default: /tmp/diag_gfs.grb2)")
    p.add_argument("--lat",   type=float, default=28.1,   help="Spot check latitude")
    p.add_argument("--lon",   type=float, default=-80.6,  help="Spot check longitude")
    p.add_argument("--label", default="Melbourne FL",     help="Spot check label")
    p.add_argument("--inventory", action="store_true",
                   help="Print full GRIB inventory (verbose)")
    p.add_argument("--bmp",  default=None,
                   help="Path to rendered output BMP to check actual pixel color "
                        "(e.g. map-N-800x400-Wx-mB.bmp)")
    p.add_argument("--base", default=None,
                   help="Path to base BMP used as background in rendering "
                        "(optional, enables exact blend prediction)")
    p.add_argument("--radius", type=int, default=2,
                   help="Neighborhood scan radius in GRIB grid steps (default: 2 = ±0.5°)")
    return p.parse_args()


def main():
    args = parse_args()

    grib_path = args.grib
    if args.download:
        grib_path = args.out
        section("Downloading Latest GFS Subset from NOMADS")
        if not download_latest_grib(grib_path):
            err("Could not download a recent GFS subset. Check NOMADS availability.")
            sys.exit(1)

    print(f"\nOpening GRIB: {grib_path}")
    grbs  = pygrib.open(grib_path)
    msgs  = list(grbs)
    grbs.close()
    print(f"  Messages found: {len(msgs)}")

    if args.inventory:
        check_inventory(msgs)

    found, fields_ok = check_required_fields(msgs)

    if not fields_ok:
        err("One or more required fields missing — pipeline will fail. Check GRIB filter URL.")
        sys.exit(1)

    check_value_ranges(found)
    check_spot(found, args.lat, args.lon, args.label)

    # BMP pixel check — needs temp_c from the spot, re-derive it quickly
    if args.bmp:
        g_t = found.get("2m Temperature")
        if g_t:
            lats2d, lons2d = g_t.latlons()
            lats1d = lats2d[:, 0]
            lons1d = lons2d[0, :]
            lon_gfs = args.lon % 360.0
            lat_idx = int(np.argmin(np.abs(lats1d - args.lat)))
            lon_idx = int(np.argmin(np.abs(lons1d - lon_gfs)))
            temp_c = g_t.values[lat_idx, lon_idx] - 273.15
            check_bmp_pixel(args.bmp, args.base, args.lat, args.lon,
                            args.label, temp_c)

    # Neighborhood scan — always run if BMP provided, or standalone
    check_neighborhood(found, args.bmp, args.lat, args.lon,
                       args.label, radius=args.radius)

    check_longitude_roll(found)
    check_colormap_stops()

    section("Summary")
    if fields_ok:
        ok("All required GRIB fields present")
        ok("Pipeline should work correctly")
    print()


if __name__ == "__main__":
    main()

