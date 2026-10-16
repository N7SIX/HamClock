#!/usr/bin/env python3
"""
Parse HamClock User-Agent strings from lighttpd access logs.

HamClock's sendUserAgent() is called on *every* backend request (map tiles,
PSK reporter, Bz, DRAP, ONTA, solar-wind, diagnostic POSTs, ...). The UA
encodes a rich state snapshot, see ESPHamClock wifi.cpp.

Log format handled: host vhost authuser [time] "req" status size "ref" "ua"
(the second field is the requesting vhost, not classical ident)

Usage:
    python3 hamclock_logparse.py access.log [access.log2 ...]
    cat access.log | python3 hamclock_logparse.py -
"""

import argparse
import gzip
import io
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional


# --- log line regex ----------------------------------------------------------
# host vhost authuser [time] "req" status size "referer" "ua"
LOG_RE = re.compile(
    r'^(?P<host>\S+)\s+(?P<vhost>\S+)\s+\S+\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<request>[^"]*)"\s+'
    r'(?P<status>\d+)\s+'
    r'(?P<size>\S+)\s+'
    r'"(?P<referer>[^"]*)"\s+'
    r'"(?P<ua>[^"]*)"'
)

DIAG_PATH_RE = re.compile(
    r'^/ham/HamClock/diagnostic-logs/dl-(\d+)-([^-]+(?:-[^-]+)*)-(\d+)\.txt$'
)

UA_PREFIX_RE = re.compile(
    r'^(?P<platform>\S+)/(?P<version>\S+)\s+'
    r'\(id\s+(?P<chipid>\d+)\s+up\s+(?P<uptime>-?\d+)\)\s+'
    r'crc\s+(?P<crc>-?\d+)'
    r'(?P<rest>.*)$'
)

# Any HamClock-ish UA so we can skip healthchecks/Prometheus/scanners.
HAMCLOCK_UA_RE = re.compile(r'^(HamClock[-\w]*|ESPHamClock|hamclock-\S+)/', re.I)


# --- decoders ----------------------------------------------------------------
MAIN_PAGE_NAMES = {0: "Mercator", 1: "Azimuthal", 2: "StopwatchMain",
                   3: "BigClockAnalog", 4: "BigClockDigital",
                   5: "Azim1", 6: "Robinson"}
DPY_MODE_NAMES  = {0: "X11", 1: "fb0", 2: "X11full",
                   3: "X11+live", 4: "X11full+live", 5: "web-only"}
UNITS_NAMES     = {0: "imperial", 1: "metric", 2: "british"}
SPOTS_NAMES     = {0: "none", 1: "prefix", 2: "call", 3: "dot"}
NTP_NAMES       = {0: "default", 1: "local", 2: "os"}


def decode_pane(v):
    if v >= 100: return {"plot_ch": v - 100, "rotating": True}
    return {"plot_ch": v, "rotating": False}

def decode_map_style(s):
    night, rotating, i = True, False, 0
    if i < len(s) and s[i] == 'N': night = False; i += 1
    if i < len(s) and s[i] == 'R': rotating = True; i += 1
    return {"style": s[i:], "night_on": night, "rotating": rotating}

def decode_io(v):
    return {"phot": bool(v&1), "ltr": bool(v&2), "mcp": bool(v&4), "i2c": bool(v&8)}

def decode_alarms(v): return {"daily": bool(v&1), "onetime": bool(v&2)}
def decode_gpsd(v):   return {"time":  bool(v&1), "loc":     bool(v&2)}

def decode_rr(v):
    gbl = v & 3
    return {"gimbal": {0:"off",1:"az-only",2:"az+el"}.get(gbl, f"?{gbl}"),
            "rigctld": bool(v&4), "flrig": bool(v&8)}

def decode_dayf(v): return {"format": v&3, "week_starts_monday": bool(v&4)}
def decode_crc(v):  return {"flash_crc_ok": v & 0x7FFF, "kbcursor": bool(v & 0x8000)}


# Field order matches wifi.cpp:1367 snprintf argument list.
LONG_FIELDS = [
    ("map_style",            decode_map_style),
    ("main_page",            lambda v: MAIN_PAGE_NAMES.get(v, f"?{v}")),
    ("mapgrid_choice",       None),
    ("pane1",                decode_pane),
    ("pane2",                decode_pane),
    ("pane3",                decode_pane),
    ("de_time_fmt",          None),
    ("brb",                  lambda v: {"mode": v-100 if v>=100 else v,
                                        "rotating": v>=100}),
    ("dx_info_for_sat",      None),
    ("rss_code",             lambda v: {"on": bool(v&1), "local": bool(v&2)}),
    ("units",                lambda v: UNITS_NAMES.get(v, f"?{v}")),
    ("n_bme",                None),
    ("gpio",                 None),
    ("io",                   decode_io),
    ("bme_temp_corr",        None),
    ("bme_pres_corr",        None),
    ("desrss",               None),
    ("dxsrss",               None),
    ("build_w",              None),
    ("dpy_mode",             lambda v: DPY_MODE_NAMES.get(v, f"?{v}")),
    ("alarms",               decode_alarms),
    ("center_lng",           None),
    ("auxtime",              None),
    ("names_on",             None),
    ("demo_mode",            None),
    ("sw_engine_state",      None),
    ("big_clock_bits",       None),
    ("utc_offset",           None),
    ("gpsd",                 decode_gpsd),
    ("rss_interval",         None),
    ("dayf",                 decode_dayf),
    ("rr_score",             decode_rr),
    ("use_mag_bearing",      None),
    ("n_dashed",             None),
    ("ntp",                  lambda v: NTP_NAMES.get(v, f"?{v}")),
    ("path",                 None),
    ("spots",                lambda v: SPOTS_NAMES.get(v, f"?{v}")),
    ("call_fg",              None),
    ("call_bg",              lambda v: {"value": v, "rainbow": v == 1}),
    ("clock_bad",            None),
    ("scroll_top_to_bottom", None),
    ("_reserved_47",         None),
    ("_reserved_48",         None),
    ("show_new_dxde_wx",     None),
    ("pane_rot_period",      None),
    ("has_pw_file",          None),
    ("n_roweb",              None),
    ("pan_zoom_active",      None),
    ("pane0",                decode_pane),
    ("screen_locked",        None),
    ("show_pip",             None),
    ("gray_display",         None),
    ("watchlist_bits",       None),
    ("auto_upgrade_hr",      None),
    ("_reserved_60",         None),
]
N_LONG_FIELDS = len(LONG_FIELDS)


@dataclass
class UARecord:
    raw_ua: str
    form: str                         # short | long | unknown | nonhc
    platform: Optional[str] = None
    version: Optional[str] = None
    chipid: Optional[int] = None
    uptime: Optional[int] = None
    crc_raw: Optional[int] = None
    crc: Optional[dict] = None
    schema: Optional[str] = None
    fields: dict = field(default_factory=dict)
    parse_error: Optional[str] = None


def _to_num(tok):
    try:
        return float(tok) if '.' in tok else int(tok)
    except ValueError:
        return tok


def parse_ua(ua):
    if not HAMCLOCK_UA_RE.match(ua):
        return UARecord(raw_ua=ua, form="nonhc")

    rec = UARecord(raw_ua=ua, form="unknown")
    m = UA_PREFIX_RE.match(ua)
    if not m:
        rec.parse_error = "prefix regex failed"
        return rec

    rec.platform = m.group("platform")
    rec.version  = m.group("version")
    rec.chipid   = int(m.group("chipid"))
    rec.uptime   = int(m.group("uptime"))
    rec.crc_raw  = int(m.group("crc"))
    rec.crc      = decode_crc(rec.crc_raw)

    rest = m.group("rest").strip()
    if not rest:
        rec.form = "short"
        return rec

    tokens = rest.split()
    if not tokens or not re.match(r'^LV\d+$', tokens[0]):
        rec.parse_error = f"expected LV marker, got {tokens[:1]!r}"
        return rec

    rec.form = "long"
    rec.schema = tokens[0]
    data = [t for t in tokens if not re.match(r'^LV\d+$', t)]

    out = {}
    for i in range(min(len(data), N_LONG_FIELDS)):
        name, decoder = LONG_FIELDS[i]
        val = _to_num(data[i])
        if decoder is not None:
            try:
                val = decoder(val)
            except Exception as e:
                val = {"raw": data[i], "decode_error": str(e)}
        out[name] = val
    rec.fields = out
    return rec


def open_any(path):
    if path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"),
                                encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def iter_records(paths):
    for path in paths:
        with open_any(path) as fh:
            for line in fh:
                m = LOG_RE.match(line)
                if not m:
                    continue
                req = m.group("request").split(" ", 2)
                if len(req) < 2:
                    continue
                method, target = req[0], req[1]

                diag_info = None
                dm = DIAG_PATH_RE.match(target)
                if dm and method == "POST":
                    diag_info = {"epoch": int(dm.group(1)),
                                 "path_ip": dm.group(2),
                                 "path_chipid": int(dm.group(3))}

                ua_rec = parse_ua(m.group("ua"))
                log = {"host":   m.group("host"),
                       "vhost":  m.group("vhost"),
                       "time":   m.group("time"),
                       "method": method,
                       "target": target,
                       "status": int(m.group("status")),
                       "size":   m.group("size"),
                       "diag":   diag_info}
                yield log, ua_rec


def summarize(it):
    s = {"total_lines": 0, "hc_lines": 0, "short_form": 0, "long_form": 0,
         "parse_errors": 0, "nonhc": 0, "diag_posts": 0}
    unique_chips = set()
    uptime_samples = []

    c_vhost    = Counter()
    c_nonhc    = Counter()
    c_target   = Counter()
    c_platform = Counter()
    c_version  = Counter()
    c_plat_ver = Counter()
    c_schema   = Counter()

    # Per-install (deduped by chipid) buckets, filled in pass 2
    c_mainpage = Counter(); c_dpy = Counter(); c_units = Counter()
    c_map      = Counter(); c_spots = Counter(); c_ntp = Counter()
    c_pane     = {i: Counter() for i in range(4)}
    rot_counts = Counter(); feat_counts = Counter()

    last_by_chip = {}
    # Per-chip "most recent" identity/context — used for per-install tallies.
    chip_platform = {}     # chipid -> latest platform string
    chip_version  = {}     # chipid -> latest version string
    chip_vhost    = {}     # chipid -> latest vhost seen
    chip_req_ct   = Counter()   # chipid -> number of requests (for heavy-hitter list)

    for log, rec in it:
        s["total_lines"] += 1
        c_vhost[log["vhost"]] += 1

        if rec.form == "nonhc":
            s["nonhc"] += 1
            c_nonhc[rec.raw_ua[:60]] += 1
            continue
        if rec.parse_error:
            s["parse_errors"] += 1
            continue

        s["hc_lines"] += 1
        if log["diag"]:
            s["diag_posts"] += 1

        parts = log["target"].split("?", 1)[0].split("/")
        if len(parts) >= 4 and parts[1] == "ham" and parts[2] == "HamClock":
            c_target[parts[3] or "(root)"] += 1

        if rec.chipid is not None and rec.chipid != 0xFFFFFFFF:
            unique_chips.add(rec.chipid)
            chip_req_ct[rec.chipid] += 1
            if rec.platform: chip_platform[rec.chipid] = rec.platform
            if rec.version:  chip_version[rec.chipid]  = rec.version
            chip_vhost[rec.chipid] = log["vhost"]
        if rec.platform:
            c_platform[rec.platform] += 1
        if rec.version:
            c_version[rec.version] += 1
        if rec.platform and rec.version:
            c_plat_ver[(rec.platform, rec.version)] += 1
        if rec.uptime and rec.uptime > 0:
            uptime_samples.append(rec.uptime)

        if rec.form == "short":
            s["short_form"] += 1
            if rec.chipid != 0xFFFFFFFF:
                last_by_chip.setdefault(rec.chipid, rec)
            continue
        s["long_form"] += 1
        if rec.chipid != 0xFFFFFFFF:
            last_by_chip[rec.chipid] = rec
        if rec.schema:
            c_schema[rec.schema] += 1

    unique_installs = 0
    for chip, rec in last_by_chip.items():
        if rec.form != "long":
            continue
        unique_installs += 1
        f = rec.fields
        if "main_page" in f: c_mainpage[f["main_page"]] += 1
        if "dpy_mode"  in f: c_dpy[f["dpy_mode"]] += 1
        if "units"     in f: c_units[f["units"]] += 1
        if "spots"     in f: c_spots[f["spots"]] += 1
        if "ntp"       in f: c_ntp[f["ntp"]] += 1
        if "map_style" in f and isinstance(f["map_style"], dict):
            c_map[f["map_style"]["style"]] += 1
            if f["map_style"].get("rotating"): rot_counts["map"] += 1
            if not f["map_style"].get("night_on"): feat_counts["night_off"] += 1
        for i, k in enumerate(("pane0","pane1","pane2","pane3")):
            if k in f and isinstance(f[k], dict):
                c_pane[i][f[k]["plot_ch"]] += 1
                if f[k]["rotating"]: rot_counts[k] += 1
        if "brb" in f and isinstance(f["brb"], dict) and f["brb"].get("rotating"):
            rot_counts["brb"] += 1

        def flag(k):
            v = f.get(k)
            return bool(v) if isinstance(v, (bool, int)) else False

        for k in ("pan_zoom_active","screen_locked","show_pip","has_pw_file",
                  "show_new_dxde_wx","scroll_top_to_bottom","use_mag_bearing",
                  "demo_mode","names_on","clock_bad","gray_display"):
            if flag(k): feat_counts[k] += 1
        if "gpsd" in f and isinstance(f["gpsd"], dict):
            if f["gpsd"].get("time"): feat_counts["gpsd_time"] += 1
            if f["gpsd"].get("loc"):  feat_counts["gpsd_loc"]  += 1
        if "rr_score" in f and isinstance(f["rr_score"], dict):
            rr = f["rr_score"]
            if rr.get("gimbal") != "off": feat_counts["gimbal"]  += 1
            if rr.get("rigctld"):         feat_counts["rigctld"] += 1
            if rr.get("flrig"):           feat_counts["flrig"]   += 1
        if rec.crc and rec.crc.get("kbcursor"): feat_counts["kbcursor"] += 1
        if "io" in f and isinstance(f["io"], dict):
            for k in ("phot","ltr","mcp","i2c"):
                if f["io"].get(k): feat_counts[f"io_{k}"] += 1

    s.update({
        "unique_chips":    len(unique_chips),
        "unique_installs": unique_installs,
        "uptime_samples":  uptime_samples,
        "vhost": c_vhost, "nonhc_ua": c_nonhc, "target": c_target,
        "platform": c_platform, "version": c_version, "plat_ver": c_plat_ver,
        "schema": c_schema,
        "main_page": c_mainpage, "dpy_mode": c_dpy, "units": c_units,
        "map_style": c_map, "spots": c_spots, "ntp": c_ntp,
        "pane0": c_pane[0], "pane1": c_pane[1],
        "pane2": c_pane[2], "pane3": c_pane[3],
        "rotating": rot_counts, "features": feat_counts,
    })

    # --- per-install (chip-deduped) tallies for identity/context -------------
    # Each chipid contributes one vote, based on its most-recently-seen value.
    # This answers "how many unique installs run armbian?" etc.
    ci_platform = Counter(chip_platform.values())
    ci_version  = Counter(chip_version.values())
    ci_plat_ver = Counter((chip_platform[c], chip_version[c])
                          for c in chip_platform if c in chip_version)
    ci_vhost    = Counter(chip_vhost.values())
    s.update({
        "ci_platform": ci_platform,
        "ci_version":  ci_version,
        "ci_plat_ver": ci_plat_ver,
        "ci_vhost":    ci_vhost,
        "chip_req_ct": chip_req_ct,
    })
    return s


def print_table(title, counter, total=None, limit=None):
    print(f"\n=== {title} ===")
    items = counter.most_common(limit) if isinstance(counter, Counter) else \
            sorted(counter.items(), key=lambda kv: -kv[1])[:limit]
    if not items:
        print("  (none)"); return
    key_w = max(len(str(k)) for k, _ in items)
    val_w = max(len(str(v)) for _, v in items)
    for k, v in items:
        pct = f"  {100.0*v/total:5.1f}%" if total else ""
        print(f"  {str(k):<{key_w}}  {v:>{val_w}d}{pct}")


def print_stats(s):
    print("="*64)
    print("HamClock lighttpd log — summary")
    print("="*64)
    print(f"  total log lines:            {s['total_lines']}")
    print(f"  HamClock requests:          {s['hc_lines']}")
    print(f"    short-form UAs:           {s['short_form']}")
    print(f"    long-form UAs:            {s['long_form']}")
    print(f"  diag POSTs:                 {s['diag_posts']}")
    print(f"  non-HamClock requests:      {s['nonhc']}")
    print(f"  parse errors:               {s['parse_errors']}")
    print(f"  unique chip IDs:            {s['unique_chips']}")
    print(f"  installs w/ long-form UA:   {s['unique_installs']}")

    u = s["uptime_samples"]
    if u:
        u_sorted = sorted(u)
        med = u_sorted[len(u_sorted)//2]
        d = lambda x: f"{x/86400:.1f}d" if x >= 86400 else f"{x}s"
        print(f"  uptime:  min={d(min(u))}  median={d(med)}  max={d(max(u))}")

    print_table("vhost (request-weighted)", s["vhost"], total=s["total_lines"])
    print_table("non-HamClock UAs", s["nonhc_ua"], limit=10)
    print_table("request categories (HamClock only)",
                s["target"], total=s["hc_lines"], limit=25)
    print_table("platforms (request-weighted)", s["platform"],
                total=s["hc_lines"], limit=15)
    print_table("versions (request-weighted)", s["version"],
                total=s["hc_lines"], limit=15)
    print_table("platform+version (request-weighted)",
                s["plat_ver"], total=s["hc_lines"], limit=15)
    print_table("UA schema (long form)", s["schema"], total=s["long_form"] or 1)

    # --- per-install identity (one vote per chipid) --------------------------
    ci = s["unique_chips"] or 1
    print(f"\n--- below: per-install identity (one vote per chip id, {ci} unique chips) ---")
    print_table("platforms (unique installs)",    s["ci_platform"], total=ci)
    print_table("versions (unique installs)",     s["ci_version"],  total=ci, limit=20)
    print_table("platform+version (unique installs)",
                s["ci_plat_ver"], total=ci, limit=20)
    print_table("vhost (unique installs)",        s["ci_vhost"],    total=ci)

    # Top noisy chips — useful for spotting broken/runaway installs.
    top = s["chip_req_ct"].most_common(10)
    if top:
        print("\n=== top 10 chips by request count ===")
        key_w = max(len(str(k)) for k, _ in top)
        for chip, n in top:
            plat = s.get("chip_platform_latest", {}).get(chip, "")  # optional
            print(f"  {chip:<{key_w}}  {n:>8d}")

    ni = s["unique_installs"] or 1
    print(f"\n--- below: per-install state (long-form UAs only, {ni} installs) ---")
    print_table("main page",           s["main_page"], total=ni)
    print_table("display mode",        s["dpy_mode"],  total=ni)
    print_table("units",               s["units"],     total=ni)
    print_table("map style",           s["map_style"], total=ni, limit=20)
    print_table("spot labels",         s["spots"],     total=ni)
    print_table("NTP source",          s["ntp"],       total=ni)
    print_table("pane 0 choice",       s["pane0"],     total=ni, limit=20)
    print_table("pane 1 choice",       s["pane1"],     total=ni, limit=20)
    print_table("pane 2 choice",       s["pane2"],     total=ni, limit=20)
    print_table("pane 3 choice",       s["pane3"],     total=ni, limit=20)
    print_table("rotating components", s["rotating"],  total=ni)
    print_table("feature flags set",   s["features"],  total=ni)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logfiles", nargs="+",
                    help="lighttpd access log(s); - for stdin; .gz supported")
    ap.add_argument("--dump", action="store_true",
                    help="emit one JSON object per record instead of summary")
    args = ap.parse_args()

    if args.dump:
        import json
        for log, rec in iter_records(args.logfiles):
            print(json.dumps({"log": log, "form": rec.form,
                              "platform": rec.platform, "version": rec.version,
                              "chipid": rec.chipid, "uptime": rec.uptime,
                              "schema": rec.schema, "crc": rec.crc,
                              "fields": rec.fields,
                              "parse_error": rec.parse_error}, default=str))
        return
    print_stats(summarize(iter_records(args.logfiles)))


if __name__ == "__main__":
    main()

