"""
Filters NSE Top losers CSV and prints potential SHORT candidate symbols.
"""

from datetime import datetime

import pandas as pd

from util.global_variables import TRADING_CAPITAL, INTRADAY_LEVERAGE_MULTIPLIER

# ── CONFIG ────────────────────────────────────────────────
MAX_PCT_CHANGE = 6.5
MIN_PCT_CHANGE = 2.5
MAX_OPENING_GAP_PCT = 3.0
MAX_PARTICIPATION_RATE = 1.0

# ── FILE ──────────────────────────────────────────────────

date_str = datetime.now().strftime("%d-%b-%Y")
filename = f"T20-GL-loosers-allSec-{date_str}.csv"

# ── LIQUIDITY THRESHOLD ───────────────────────────────────

buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def main():
    # ── LOAD ──────────────────────────────────────────────────
    df = pd.read_csv(filename)

    # =========================
    # CALCULATIONS
    # =========================

    # Gap-down from previous close
    df["gap_pct"] = (((df["Open"] - df["Prev. Close"]) / df["Prev. Close"]) * 100).abs().round(1)

    # % price move from open
    df["price_change_%"] = (((df["LTP"] - df["Open"]) / df["Open"]) * 100).abs().round(1)

    # Liquidity condition
    df["participation_rate"] = (buying_power / (df["LTP"] * df["Volume"]) * 100).round(2)

    # =========================
    # FILTER CONDITIONS
    # =========================
    filtered = df[
        (df["price_change_%"] >= MIN_PCT_CHANGE) &
        (df["price_change_%"] <= MAX_PCT_CHANGE) &
        (df["gap_pct"] <= MAX_OPENING_GAP_PCT) &
        (df["participation_rate"] <= MAX_PARTICIPATION_RATE)
        ]

    # =========================
    # PRINT RESULTS
    # =========================
    if filtered.empty:
        print("No symbols passed the criteria")
    else:
        print("\nTop Losers Watchlist:\n")

        print(
            filtered[
                [
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


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
