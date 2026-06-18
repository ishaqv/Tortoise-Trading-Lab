"""
Filters NSE Top gainers CSV and prints potential LONG candidate symbols.
"""

from datetime import datetime

import pandas as pd

from util.global_variables import TRADING_CAPITAL, INTRADAY_LEVERAGE_MULTIPLIER

# ── CONFIG ────────────────────────────────────────────────
MIN_PCT_CHANGE = 2.0
MAX_PCT_CHANGE = 8.0

MIN_GAP_UP = 0.0
MAX_GAP_UP = 3.0

MAX_PARTICIPATION_RATE = 1.0

# ── FILE ──────────────────────────────────────────────────

date_str = datetime.now().strftime("%d-%b-%Y")
filename = f"T20-GL-gainers-allSec-{date_str}.csv"

# ── LIQUIDITY THRESHOLD ───────────────────────────────────

buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def main():
    # ── LOAD ──────────────────────────────────────────────────
    df = pd.read_csv(filename)

    # =========================
    # CALCULATIONS
    # =========================

    # Gap-up from previous close
    df["gap_up_%"] = (((df["Open"] - df["Prev. Close"]) / df["Prev. Close"]) * 100).round(1)

    # % price move from open
    df["price_change_%"] = (((df["LTP"] - df["Open"]) / df["Open"]) * 100).round(1)

    # Liquidity  condition
    df["participation_rate"] = (buying_power / (df["LTP"] * df["Volume"]) * 100).round(2)

    # =========================
    # FILTER CONDITIONS
    # =========================
    filtered = df[
        (df["price_change_%"] >= MIN_PCT_CHANGE) &
        (df["price_change_%"] <= MAX_PCT_CHANGE) &

        (df["gap_up_%"] >= MIN_GAP_UP) &
        (df["gap_up_%"] <= MAX_GAP_UP) &

        (df["participation_rate"] <= MAX_PARTICIPATION_RATE)
        ]

    # =========================
    # PRINT RESULTS
    # =========================
    if filtered.empty:
        print("No symbols passed the criteria")
    else:
        print("\nTop Gainers Wtachlist:\n")

        print(
            filtered[
                [
                    "Symbol",
                    "gap_up_%",
                    "price_change_%",
                    "participation_rate"
                ]
            ]
            .sort_values(by="participation_rate", ascending=True)
            .to_string(index=False)
        )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
