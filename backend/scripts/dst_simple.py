#!/usr/bin/env python3
"""
gen_dst.py — HamClock-style dst.txt from Kyoto DST realtime monthly file (CSI-like behavior)

Outputs 24 UTC hourly points:
YYYY-MM-DDTHH:00:00 <value>

Behavior implemented:
- Parse Kyoto DST monthly realtime file using fixed-width columns
- Ignore trailing extra column
- Stop row parsing at filler (9999) or packed filler (X999)
- Anchor to latest parsed hour, clamped to floor(now_utc)-1h
- Full rewrite every run — matches CSI which re-fetches and rewrites from live source
- Month-boundary-safe: if current month alone cannot build a full 24h window,
  auto-fetch previous month archive and merge
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests


KYOTO_URL_TMPL = "https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/presentmonth/dst{yy}{mm}.for.request"
KYOTO_ARCHIVE_URL_TMPL = "https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/{yyyy}{mm}/dst{yy}{mm}.for.request"


@dataclass
class ParsedDstRow:
    year: int
    month: int
    day: int
    hours: Dict[int, int]   # hour -> value for valid parsed hours only


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prev_month(dt: datetime) -> datetime:
    first = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first - timedelta(days=1)


def build_presentmonth_url(dt_utc: Optional[datetime] = None) -> str:
    dt_utc = dt_utc or utc_now()
    return KYOTO_URL_TMPL.format(yy=dt_utc.strftime("%y"), mm=dt_utc.strftime("%m"))


def build_archive_url(dt_utc: datetime) -> str:
    return KYOTO_ARCHIVE_URL_TMPL.format(
        yyyy=dt_utc.strftime("%Y"),
        yy=dt_utc.strftime("%y"),
        mm=dt_utc.strftime("%m"),
    )


def download_text(url: str, timeout: int = 20) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def _parse_int_token(tok: str) -> Optional[int]:
    tok = tok.strip()
    if not tok:
        return None
    if not re.fullmatch(r"[+-]?\d+", tok):
        return None
    return int(tok)


def parse_dst_line_fixed(line: str) -> Optional[ParsedDstRow]:
    """
    Kyoto fixed-width parsing.

    Observed layout (1-based columns):
      1..3     "DST"
      4..5     YY
      6..7     MM
      8        '*'
      9..10    DD
      ...
      17..20   pre-field (ignored)
      21..24   hour00
      25..28   hour01
      ...
      113..116 hour23
      117..120 trailing extra column (ignored)
    """
    if not line.startswith("DST"):
        return None
    if len(line) < 24:
        return None

    yy = line[3:5]
    mm = line[5:7]
    dd = line[8:10]
    if not (yy.isdigit() and mm.isdigit() and dd.isdigit()):
        return None

    year = 2000 + int(yy)
    month = int(mm)
    day = int(dd)

    hours: Dict[int, int] = {}

    for hour in range(24):
        start = 20 + (hour * 4)  # 1-based col 21 => 0-based 20
        end = start + 4
        tok = line[start:end].strip()

        if tok == "" or tok == "9999":
            break

        # Packed filler: "0999" -> value 0 then stop, "2999" -> value 2 then stop, etc.
        m_packed = re.fullmatch(r"([+-]?\d)999", tok)
        if m_packed:
            hours[hour] = int(m_packed.group(1))
            break

        val = _parse_int_token(tok)
        if val is None:
            break

        hours[hour] = val

    return ParsedDstRow(year=year, month=month, day=day, hours=hours)


def parse_all_rows(text: str) -> List[ParsedDstRow]:
    rows: List[ParsedDstRow] = []
    for line in text.splitlines():
        if line.startswith("DST"):
            row = parse_dst_line_fixed(line)
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda r: (r.year, r.month, r.day))
    return rows


def merge_rows(*row_lists: List[ParsedDstRow]) -> List[ParsedDstRow]:
    # Deduplicate by (year, month, day); later lists win
    merged: Dict[Tuple[int, int, int], ParsedDstRow] = {}
    for rows in row_lists:
        for r in rows:
            merged[(r.year, r.month, r.day)] = r
    out = list(merged.values())
    out.sort(key=lambda r: (r.year, r.month, r.day))
    return out


def rows_to_map(rows: List[ParsedDstRow]) -> Dict[datetime, int]:
    pts: Dict[datetime, int] = {}
    for r in rows:
        for h, v in r.hours.items():
            ts = datetime(r.year, r.month, r.day, h, 0, 0, tzinfo=timezone.utc)
            pts[ts] = v
    return pts


def compute_end_hour(rows: List[ParsedDstRow], now_utc: Optional[datetime] = None) -> datetime:
    """
    End hour = min(floor(now_utc) - 1h, latest parsed timestamp).
    CSI emits whatever Kyoto has actually written — no synthetic hours beyond parsed data.
    """
    if not rows:
        raise ValueError("no rows")

    now_utc = (now_utc or utc_now()).astimezone(timezone.utc)
    now_floor = now_utc.replace(minute=0, second=0, microsecond=0)
    desired_end = now_floor - timedelta(hours=1)

    parsed_map = rows_to_map(rows)
    if not parsed_map:
        raise ValueError("no parsed points")

    latest_parsed_ts = max(parsed_map.keys())
    return min(desired_end, latest_parsed_ts)


def build_last24(rows: List[ParsedDstRow], now_utc: Optional[datetime] = None) -> pd.DataFrame:
    end_hour = compute_end_hour(rows, now_utc=now_utc)
    parsed_map = rows_to_map(rows)

    target_times = [end_hour - timedelta(hours=i) for i in range(23, -1, -1)]

    out_rows: List[Tuple[datetime, int]] = []
    for ts in target_times:
        val = parsed_map.get(ts)
        if val is None:
            raise ValueError(f"No DST value available for {ts.isoformat()}")
        out_rows.append((ts, val))

    return pd.DataFrame(out_rows, columns=["ts", "value"])


def format_line(ts: datetime, value: int) -> str:
    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return f"{ts:%Y-%m-%dT%H:%M:%S} {int(value)}"


def write_dst_file(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    for _, row in df.iterrows():
        ts = row["ts"]
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        lines.append(format_line(ts, int(row["value"])))
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_rows(now_utc: datetime, timeout: int, debug: bool = False) -> List[ParsedDstRow]:
    """
    Fetch current month. If it alone cannot fill a 24h window, also fetch previous month.
    """
    current_url = build_presentmonth_url(now_utc)
    if debug:
        print(f"[debug] fetching {current_url}", file=sys.stderr)
    current_text = download_text(current_url, timeout=timeout)
    current_rows = parse_all_rows(current_text)

    # Fast path: current month alone works
    try:
        df = build_last24(current_rows, now_utc=now_utc)
        if len(df) == 24:
            if debug:
                print(f"[debug] source: current month only", file=sys.stderr)
            return current_rows
    except Exception:
        pass

    # Fallback: merge previous month archive + current month
    prev_dt = prev_month(now_utc)
    prev_url = build_archive_url(prev_dt)
    if debug:
        print(f"[debug] fetching previous month {prev_url}", file=sys.stderr)

    prev_rows: List[ParsedDstRow] = []
    try:
        prev_text = download_text(prev_url, timeout=timeout)
        prev_rows = parse_all_rows(prev_text)
    except Exception as e:
        if debug:
            print(f"[debug] previous month fetch failed: {e}", file=sys.stderr)

    merged_rows = merge_rows(prev_rows, current_rows)

    # Validate
    _ = build_last24(merged_rows, now_utc=now_utc)

    if debug:
        print(f"[debug] source: merged previous+current months", file=sys.stderr)

    return merged_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="/opt/hamclock-backend/htdocs/ham/HamClock/dst/dst.txt")
    ap.add_argument("--url", default=None, help="Override source URL")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    now = utc_now()
    output_path = Path(args.output)

    try:
        if args.url:
            text = download_text(args.url, timeout=args.timeout)
            rows = parse_all_rows(text)
        else:
            rows = fetch_rows(now, timeout=args.timeout, debug=args.debug)
    except requests.RequestException as e:
        print(f"{int(now.timestamp())} Error: download failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"{int(now.timestamp())} Error: source preparation failed: {e}", file=sys.stderr)
        return 1

    if not rows:
        print(f"{int(now.timestamp())} Error: no DST rows parsed", file=sys.stderr)
        return 1

    try:
        window_df = build_last24(rows, now_utc=now)

        if len(window_df) != 24:
            raise ValueError(f"expected 24 rows, got {len(window_df)}")
        if window_df["ts"].duplicated().any():
            raise ValueError("duplicate timestamps in computed window")
        if not window_df["ts"].is_monotonic_increasing:
            raise ValueError("computed timestamps not increasing")
        diffs = window_df["ts"].diff().dropna()
        if not (diffs == pd.Timedelta(hours=1)).all():
            raise ValueError("computed window has non-hourly cadence")

    except Exception as e:
        print(f"{int(now.timestamp())} Error: failed to compute DST window: {e}", file=sys.stderr)
        return 1

    try:
        write_dst_file(window_df, output_path)
    except Exception as e:
        print(f"{int(now.timestamp())} Error: dst write failed: {e}", file=sys.stderr)
        return 1

    if args.debug:
        try:
            print(window_df.to_string(index=False))
            end_hour = window_df.iloc[-1]["ts"]
            end_val = int(window_df.iloc[-1]["value"])
            print(f"\nend_hour={end_hour} end_val={end_val}")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

