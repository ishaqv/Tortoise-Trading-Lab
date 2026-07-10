"""
Uses Zerodha Kite Connect to build LONG (gainers) and SHORT (losers)
watchlists from live NSE equity data.

Kite Connect has NO built-in "top gainers/losers" endpoint - unlike the
NSE website scraper, this script:
    1. Downloads the full NSE equity instrument list (kite.instruments)
    2. Fetches live quotes for all of them (batched - quote() accepts
       up to 500 instruments per call)
    3. Computes gap_pct / price_change_% / participation_rate itself
    4. Filters into gainers + losers watchlists using the same logic
       as the CSV/NSE-live scanners

── AUTH REQUIREMENTS ──────────────────────────────────────────────
Kite Connect requires an api_key + a daily access_token. The
access_token expires every trading day and must be regenerated via
Kite's browser login flow (you cannot script around this - it's by
design, for security):

    1. Redirect user to: kite.login_url()
    2. User logs in/authorizes, Kite redirects back with a
       `request_token` in the URL
    3. kite.generate_session(request_token, api_secret=API_SECRET)
       returns the access_token for that day

This script assumes KITE_API_KEY and a *fresh* KITE_ACCESS_TOKEN are
already available in util.global_variables. Regenerating the token
each morning is on you (or wire up the login flow separately) - it's
not something that can be silently automated.

── RATE LIMITS ─────────────────────────────────────────────────────
Kite Connect's market-data endpoints (quote/ohlc/ltp) are limited to
roughly 1 request/second combined. This script batches 500 symbols per
call and sleeps between batches accordingly. Do not lower the sleep
without checking Kite's current published rate limits, or you risk
getting temporarily blocked.
"""

import time

import pandas as pd
from kiteconnect import KiteConnect

from util.global_variables import (
    TRADING_CAPITAL,
    INTRADAY_LEVERAGE_MULTIPLIER,
    KITE_API_KEY,
    KITE_ACCESS_TOKEN,
)

# ── CONFIG: LONG (GAINERS) ───────────────────────────────
GAINERS_MIN_PCT_CHANGE = 2.5
GAINERS_MAX_PCT_CHANGE = 6.5
GAINERS_MIN_GAP_PCT = 0.0
GAINERS_MAX_GAP_PCT = 2.5

# ── CONFIG: SHORT (LOSERS) ───────────────────────────────
LOSERS_MIN_PCT_CHANGE = -6.5
LOSERS_MAX_PCT_CHANGE = -2.5
LOSERS_MIN_GAP_PCT = -2.5
LOSERS_MAX_GAP_PCT = 0.0

MAX_PARTICIPATION_RATE = 0.75

BATCH_SIZE = 500  # Kite quote() hard limit per call
BATCH_SLEEP_SECONDS = 1.0  # stay under Kite's ~1 req/sec data-API limit

# ── LIQUIDITY THRESHOLD ───────────────────────────────────

buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def get_kite_client() -> KiteConnect:
    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(KITE_ACCESS_TOKEN)
    return kite


def fetch_nse_equity_symbols(kite: KiteConnect) -> list[str]:
    """
    Pulls the full NSE instrument dump and filters down to plain
    equities (excludes ETFs/indices/etc where possible).
    Returns fully-qualified symbols like 'NSE:RELIANCE'.
    """
    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    df = df[(df["segment"] == "NSE") & (df["instrument_type"] == "EQ")]

    return [f"NSE:{symbol}" for symbol in df["tradingsymbol"].tolist()]


def fetch_all_quotes(kite: KiteConnect, symbols: list[str]) -> dict:
    """
    Fetches quotes for every symbol in batches of BATCH_SIZE,
    respecting Kite's rate limit with a sleep between calls.
    """
    all_quotes = {}

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]
        try:
            quotes = kite.quote(batch)
            all_quotes.update(quotes)
        except Exception as exc:
            print(f"Warning: batch starting at index {i} failed ({exc}); skipping.")

        time.sleep(BATCH_SLEEP_SECONDS)

    return all_quotes


def build_dataframe(quotes: dict) -> pd.DataFrame:
    rows = []
    for full_symbol, q in quotes.items():
        ohlc = q.get("ohlc", {})
        rows.append({
            "Symbol": full_symbol.split(":", 1)[-1],
            "Open": ohlc.get("open"),
            "High": ohlc.get("high"),
            "Low": ohlc.get("low"),
            "Prev. Close": ohlc.get("close"),
            "LTP": q.get("last_price"),
            "Volume": q.get("volume"),
        })

    df = pd.DataFrame(rows)

    numeric_cols = ["Open", "High", "Low", "Prev. Close", "LTP", "Volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # drop symbols with no trade yet / zero prev close (avoids div-by-zero)
    df = df.dropna(subset=numeric_cols)
    df = df[(df["Prev. Close"] > 0) & (df["Open"] > 0) & (df["Volume"] > 0)]

    return df


def add_calculated_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["gap_pct"] = (((df["Open"] - df["Prev. Close"]) / df["Prev. Close"]) * 100).round(1)
    df["price_change_%"] = (((df["LTP"] - df["Open"]) / df["Open"]) * 100).round(1)
    df["participation_rate"] = (buying_power / (df["LTP"] * df["Volume"]) * 100).round(2)
    return df


def print_watchlist(df: pd.DataFrame, title: str):
    if df.empty:
        print(f"\n{title}: No symbols passed the criteria")
        return

    print(f"\n{title}:\n")
    print(
        df[["Symbol", "gap_pct", "price_change_%", "participation_rate"]]
        .sort_values(by="participation_rate", ascending=True)
        .to_string(index=False)
    )


def main():
    kite = get_kite_client()

    print("Fetching NSE equity instrument list...")
    symbols = fetch_nse_equity_symbols(kite)
    print(f"Found {len(symbols)} equity symbols. Fetching live quotes in batches of {BATCH_SIZE}...")

    quotes = fetch_all_quotes(kite, symbols)
    print(f"Received quotes for {len(quotes)} symbols.")

    df = build_dataframe(quotes)
    df = add_calculated_columns(df)

    # =========================
    # LONG (GAINERS)
    # =========================
    gainers = df[
        (df["price_change_%"] >= GAINERS_MIN_PCT_CHANGE) &
        (df["price_change_%"] <= GAINERS_MAX_PCT_CHANGE) &
        (df["gap_pct"] >= GAINERS_MIN_GAP_PCT) &
        (df["gap_pct"] <= GAINERS_MAX_GAP_PCT) &
        (df["participation_rate"] <= MAX_PARTICIPATION_RATE)
        ]

    # =========================
    # SHORT (LOSERS)
    # =========================
    losers = df[
        (df["price_change_%"] >= LOSERS_MIN_PCT_CHANGE) &
        (df["price_change_%"] <= LOSERS_MAX_PCT_CHANGE) &
        (df["gap_pct"] >= LOSERS_MIN_GAP_PCT) &
        (df["gap_pct"] <= LOSERS_MAX_GAP_PCT) &
        (df["participation_rate"] <= MAX_PARTICIPATION_RATE)
        ]

    print_watchlist(gainers, "Top Gainers Watchlist (Kite Live)")
    print_watchlist(losers, "Top Losers Watchlist (Kite Live)")


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
