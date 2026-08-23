"""
Filters NSE Top gainers CSV files and prints potential LONG candidate symbols.
Can scan a single file (today's, as before) or every matching file in a folder,
one by one.
"""

import glob
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd

from util.global_variables import TRADING_CAPITAL, INTRADAY_LEVERAGE_MULTIPLIER

# ── CONFIG ────────────────────────────────────────────────
MIN_PCT_CHANGE = 2.5
MIN_PCT_CHANGE_LOW_PARTICIPATION = 1.5
MAX_PCT_CHANGE = 8.0
MAX_OPENING_GAP_PCT = 3.0
MAX_PARTICIPATION_RATE = 0.75
PARTICIPATION_THRESHOLD = 0.35

# ── FILE ──────────────────────────────────────────────────

date_str = datetime.now().strftime("%d-%b-%Y")
DEFAULT_FILENAME = f"T20-GL-gainers-allSec-{date_str}.csv"

# Directory to scan, and the glob pattern used to pick up every gainers CSV
# for TODAY's date only (e.g. multiple exports for the same day).
SCAN_DIR = "."
FILE_PATTERN = f"*{date_str}.csv"

# ── LIQUIDITY THRESHOLD ───────────────────────────────────

buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def get_label(filename):
    """Extract the short segment between 'gainers-' and today's date_str,
    e.g. 'T20-GL-gainers-NIFTYNEXT50-06-Aug-2026.csv' -> 'NIFTYNEXT50'.
    Falls back to the full filename if the pattern isn't found."""
    match = re.search(rf"gainers-(.+)-{re.escape(date_str)}", os.path.basename(filename))
    return match.group(1) if match else os.path.basename(filename)


def scan_file(filename):
    """Load one CSV, apply the filter conditions, and print the watchlist for it
    (each row tagged with the source filename)."""
    try:
        df = pd.read_csv(filename)
    except FileNotFoundError:
        print(f"File not found, skipping: {filename}")
        return
    except Exception as e:
        print(f"Could not read {filename}: {e}")
        return

    # =========================
    # CALCULATIONS
    # =========================

    # Gap-up from previous close
    df["gap_pct"] = (((df["Open"] - df["Prev. Close"]) / df["Prev. Close"]) * 100).abs().round(1)

    # % price move from open
    df["price_change_%"] = (((df["LTP"] - df["Open"]) / df["Open"]) * 100).round(1)

    # Liquidity condition
    df["participation_rate"] = (buying_power / (df["LTP"] * df["Volume"]) * 100).round(2)

    # Tag every row with the index it came from (short label, e.g. NIFTY, allSec)
    df["Index"] = get_label(filename)

    # =========================
    # FILTER CONDITIONS
    # =========================
    filtered = df[
        (df["price_change_%"] >= np.where(
            df["participation_rate"] < PARTICIPATION_THRESHOLD,
            MIN_PCT_CHANGE_LOW_PARTICIPATION,
            MIN_PCT_CHANGE
        )) &
        (df["price_change_%"] <= MAX_PCT_CHANGE) &
        (df["gap_pct"] <= MAX_OPENING_GAP_PCT) &
        (df["participation_rate"] < MAX_PARTICIPATION_RATE)
        ]

    # =========================
    # PRINT RESULTS
    # =========================
    if not filtered.empty:
        print(
            filtered[
                [
                    "Index",
                    "Symbol",
                    "gap_pct",
                    "price_change_%",
                    "participation_rate"
                ]
            ]
            .sort_values(
                by=["participation_rate", "price_change_%"],
                ascending=[True, False],
            )
            .to_string(index=False)

        )
        print("\n")


def scan_files(filenames):
    """Scan a list of CSV files one by one."""
    for filename in filenames:
        scan_file(filename)


def scan_directory(directory=SCAN_DIR, pattern=FILE_PATTERN):
    """Find every CSV matching `pattern` in `directory` and scan them one by one."""
    matches = sorted(glob.glob(os.path.join(directory, pattern)))
    if not matches:
        print(f"No files matching '{pattern}' found in '{directory}'")
        return
    scan_files(matches)


def main():
    # Scan every CSV in SCAN_DIR that matches today's date (FILE_PATTERN =
    # f"*{date_str}.csv"), one by one.
    print(f"\n----------------  Top Gainers Watchlist  ------------------\n")
    scan_directory()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
