import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from util.global_variables import TRADING_CAPITAL, MAX_RISK_PER_TRADE_PERCENT, \
    LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH
from util.kite_util import get_kite
from util.shariah_stock_filter import get_symbol_instrument_token
from util.trade_logger import initialize_logger
from util.trade_type import TradeType

INTERVAL = "week"
DAYS_PER_CHUNK = 2000  # Kite's max span per request for the "day" interval
DATA_FOLDER = f"data/{INTERVAL}"
REPORT_FOLDER = "reports"
HOLDING_PERIOD_DAYS = 3

# --- Costs / execution frictions ----------------------------------------
entry_slippage_bp = 0
stop_slippage_bp = 4

INTRABAR_BOTH_HIT_POLICY = "stop_first"

R = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT

NSE_EQUITY_DELIVERY_CHARGES = {
    "brokerage_rate": 0.0,  # many discount brokers: ₹0 for delivery
    "brokerage_cap": 0.0,
    "stt": 0.001,  # 0.1%, BOTH buy and sell for delivery
    "exchange": 0.0000345,  # NSE transaction charges
    "sebi": 0.000001,  # ₹10 / crore
    "stamp": 0.00015,  # 0.015%, buy side only (delivery rate)
    "gst": 0.18,
    "dp_charge_per_exit": 15.34,  # flat, incl. GST, charged once per sell leg
}


def get_tick_size(price: float) -> float:
    """NSE tick size based on stock price (unchanged from intraday version)."""
    if price < 250:
        return 0.01
    elif price <= 1000:
        return 0.05
    elif price <= 5000:
        return 0.10
    elif price <= 10000:
        return 0.50
    elif price <= 20000:
        return 1.00
    else:
        return 5.00


def calculate_round_trip_cost(entry_price: float, exit_price: float, quantity: int):
    """Delivery round-trip cost: brokerage + STT (both legs) + exchange +
    SEBI + stamp (buy leg) + GST + flat DP charge on the sell leg."""

    buy_value = entry_price * quantity
    sell_value = exit_price * quantity
    turnover = buy_value + sell_value

    brokerage_buy = min(
        NSE_EQUITY_DELIVERY_CHARGES["brokerage_cap"] or float("inf"),
        buy_value * NSE_EQUITY_DELIVERY_CHARGES["brokerage_rate"]
    ) if NSE_EQUITY_DELIVERY_CHARGES["brokerage_rate"] > 0 else 0.0

    brokerage_sell = min(
        NSE_EQUITY_DELIVERY_CHARGES["brokerage_cap"] or float("inf"),
        sell_value * NSE_EQUITY_DELIVERY_CHARGES["brokerage_rate"]
    ) if NSE_EQUITY_DELIVERY_CHARGES["brokerage_rate"] > 0 else 0.0

    brokerage = brokerage_buy + brokerage_sell

    stt = (buy_value + sell_value) * NSE_EQUITY_DELIVERY_CHARGES["stt"]

    exchange = turnover * NSE_EQUITY_DELIVERY_CHARGES["exchange"]
    sebi = turnover * NSE_EQUITY_DELIVERY_CHARGES["sebi"]
    stamp = buy_value * NSE_EQUITY_DELIVERY_CHARGES["stamp"]

    gst = (brokerage + exchange) * NSE_EQUITY_DELIVERY_CHARGES["gst"]

    dp_charge = NSE_EQUITY_DELIVERY_CHARGES["dp_charge_per_exit"]

    total = brokerage + stt + exchange + sebi + stamp + gst + dp_charge

    return {
        "buy_value": round(buy_value, 2),
        "sell_value": round(sell_value, 2),
        "turnover": round(turnover, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange": round(exchange, 2),
        "sebi": round(sebi, 2),
        "stamp": round(stamp, 2),
        "gst": round(gst, 2),
        "dp_charge": round(dp_charge, 2),
        "total": round(total, 2),
    }


def get_file_path(symbol):
    os.makedirs(DATA_FOLDER, exist_ok=True)
    return os.path.join(DATA_FOLDER, f"NSE_{symbol}.csv")


def fetch_back_testing_data(symbol, instrument_token, from_year=None, to_year=None, num_years=10):
    """
    Fetch historical daily OHLCV data. Two modes:
      - from_year & to_year → exact range
      - num_years           → last N years from today (default 10, since
        daily swing systems benefit from more regimes/cycles than an
        intraday system needs)
    """
    kite = get_kite()
    to_day = datetime.today()

    if from_year and to_year:
        start_date = datetime(from_year, 1, 1)
        end_date = datetime(to_year, 12, 31)
    elif num_years:
        end_date = to_day
        start_date = end_date - timedelta(days=365 * num_years)
    else:
        end_date = to_day
        start_date = end_date - timedelta(days=365 * 10)

    if end_date > to_day:
        end_date = to_day

    to_date = end_date
    ohlcv_data_list = []

    print(f"Fetching data for {symbol} | Range: {start_date.date()} → {end_date.date()}")

    try:
        while to_date > start_date:
            from_date = max(to_date - timedelta(days=DAYS_PER_CHUNK), start_date)

            print(f"  Chunk: {from_date.date()} → {to_date.date()}")
            time.sleep(1)

            ohlcv_data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=INTERVAL
            )

            if ohlcv_data:
                ohlcv_data_list.extend(ohlcv_data)
            else:
                print(f"  No data returned for this chunk, skipping...")

            to_date = from_date - timedelta(days=1)

        if not ohlcv_data_list:
            print(f"No data fetched for {symbol}.")
            return False

        df = pd.DataFrame(ohlcv_data_list)
        df.rename(columns={'date': 'trade_date'}, inplace=True)
        df.drop_duplicates(subset=['trade_date'], inplace=True)
        df.sort_values('trade_date', inplace=True)
        df.reset_index(drop=True, inplace=True)

        file_path = get_file_path(symbol)
        df.to_csv(file_path, index=False)

        print(f"Saved {len(df)} candles for {symbol} to {file_path}")
        return True

    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return False


def compute_quantity(entry_price, risk_per_share):
    """No intraday leverage for swing/delivery positions — capital is
    capped at TRADING_CAPITAL itself (cash/CNC), not a leveraged multiple."""
    buying_power = TRADING_CAPITAL

    risk_based_qty = R / risk_per_share
    capital_based_qty = buying_power / entry_price

    is_capital_constrained = capital_based_qty < risk_based_qty
    tradable_qty = min(risk_based_qty, capital_based_qty)

    if tradable_qty > 1:
        tradable_qty = round(tradable_qty)
    return tradable_qty, is_capital_constrained


# =========================================================
# ================= TRADE SIMULATION =========================
# =========================================================

def process_symbol(symbol, instrument_token):
    initialize_logger(
        TradeType.POSITIONAL,
        "w1",
        True
    )

    # =========================================================
    # CONFIG
    # =========================================================

    ENTRY_LOOKAHEAD_CANDLES = 2

    file_path = get_file_path(symbol)

    # =========================================================
    # FETCH DATA IF REQUIRED
    # =========================================================

    if (
            not os.path.isfile(file_path)
            or os.path.getsize(file_path) == 0
    ):
        if not fetch_back_testing_data(
                symbol,
                instrument_token,
                num_years=10
        ):
            return []

    results = []

    return results


def print_key_metrics_table(df, window=20):
    total_trades = len(df)
    wins = (df["R"] > 0).sum()
    losses = (df["R"] < 0).sum()
    breakevens = (df["R"] == 0).sum()
    win_rate = wins / total_trades if total_trades > 0 else 0
    avg_win = df[df["R"] > 0]["R"].mean() if wins > 0 else 0
    avg_loss = df[df["R"] < 0]["R"].mean() if losses > 0 else 0
    avg_win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
    expectancy_net = df["R"].mean()
    expectancy_gross = df["R_Gross"].mean() if "R_Gross" in df.columns else float("nan")
    best_trade_r = df["R"].max()
    worst_trade_r = df["R"].min()

    gross_profit = df[df["PnL"] > 0]["PnL"].sum()
    gross_loss = abs(df[df["PnL"] < 0]["PnL"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    max_dd_r = df["DD_R"].min()
    max_dd_amt = df["DD_PnL"].min()
    max_dd_pct = df["Drawdown_%"].min()
    total_r = df["R"].sum()
    recovery_factor = total_r / abs(max_dd_r) if max_dd_r != 0 else 0

    avg_mfe = df["MaxR_Execution"].mean()
    avg_mae = df["MAE_R"].mean()
    pct_mae_beyond_half_r = (df["MAE_R"] < -0.5).mean() * 100
    avg_dur_days = df["Duration_Days"].mean()

    total_gross_pnl = df["Gross_PnL"].sum() if "Gross_PnL" in df.columns else float("nan")
    total_cost = (total_gross_pnl - df["PnL"].sum()) if "Gross_PnL" in df.columns else float("nan")
    cost_drag_pct = (total_cost / total_gross_pnl * 100) if total_gross_pnl not in (0, float("nan")) else float("nan")
    pct_capital_constrained = (
            df["Leverage_Constrained"].mean() * 100) if "Leverage_Constrained" in df.columns else float("nan")

    total_r_gross = (total_gross_pnl / R) if R and total_gross_pnl == total_gross_pnl else float("nan")

    total_slippage_cost = df["SlippageCost_Actual"].sum() if "SlippageCost_Actual" in df.columns else float("nan")
    total_round_trip_cost = df["RoundTripCost_Actual"].sum() if "RoundTripCost_Actual" in df.columns else float("nan")
    participating_trades = (df["RoundTripCost_Actual"] > 0).sum() if "RoundTripCost_Actual" in df.columns else float(
        "nan")
    avg_cost_per_trade = (total_cost / participating_trades) if participating_trades else float("nan")

    start_date = df["Entry Time"].iloc[0]
    end_date = df["Entry Time"].iloc[-1]
    months_span = max((end_date - start_date).days / 30.44, 1e-6)
    trades_per_month = total_trades / months_span

    monthly_trade_counts = df.groupby(
        df["Entry Time"].dt.tz_localize(None).dt.to_period("M")
        if df["Entry Time"].dt.tz is not None
        else df["Entry Time"].dt.to_period("M")
    ).size()
    max_trades_month = int(monthly_trade_counts.max()) if len(monthly_trade_counts) else 0
    min_trades_month = int(monthly_trade_counts.min()) if len(monthly_trade_counts) else 0
    avg_trades_month_actual = monthly_trade_counts.mean() if len(monthly_trade_counts) else 0.0

    if len(df) >= window:
        rolling_exp = df["R"].rolling(window).mean().iloc[-1]
        rolling_exp_gross = df["R_Gross"].rolling(window).mean().iloc[-1] if "R_Gross" in df.columns else float("nan")
        rolling_wr = (df["R"] > 0).rolling(window).mean().iloc[-1]
    else:
        rolling_exp, rolling_exp_gross, rolling_wr = float("nan"), float("nan"), float("nan")

    rows = [
        ("Performance", "Capital(₹)", f"{TRADING_CAPITAL}"),
        ("Performance", "R(₹)", f"{R}"),
        ("Performance", "Total Trades", f"{total_trades}"),
        ("Performance", "Wins / Losses / BE", f"{wins} / {losses} / {breakevens}"),
        ("Performance", "Win Rate", f"{win_rate:.1%}"),
        ("Performance", "Avg Win (R)", f"{avg_win:.2f}"),
        ("Performance", "Avg Loss (R)", f"{avg_loss:.2f}"),
        ("Performance", "Win/Loss Ratio", f"{avg_win_loss_ratio:.2f}"),
        ("Performance", "Expectancy (R, Gross, pre-cost)",
         f"{expectancy_gross:.2f}" if expectancy_gross == expectancy_gross else "n/a"),
        ("Performance", "Expectancy (₹, Gross, pre-cost)",
         f"{round(expectancy_gross * R)}" if expectancy_gross == expectancy_gross else "n/a"),
        ("Performance", "Expectancy (R, Net, post-cost)", f"{expectancy_net:.2f}"),
        ("Performance", "Expectancy (₹, Net, post-cost)", f"{round(expectancy_net * R)}"),
        ("Performance", "Profit Factor", f"{profit_factor:.2f}"),
        ("Performance", "Best / Worst Trade (R)", f"{best_trade_r:.2f} / {worst_trade_r:.2f}"),
        ("Performance", "Total R (Gross, pre-cost)",
         f"{total_r_gross:.2f}" if total_r_gross == total_r_gross else "n/a"),
        ("Performance", "Total R (Net, post-cost)", f"{total_r:.2f}"),
        ("Performance", "Total PnL (₹, net)", f"₹{df['PnL'].sum():,.0f}"),
        ("Risk", "Max Drawdown (R)", f"{max_dd_r:.2f}"),
        ("Risk", "Max Drawdown (₹)", f"₹{max_dd_amt:,.0f}"),
        ("Risk", "Max Drawdown (%)", f"{max_dd_pct:.2f}%"),

        ("Risk", "Recovery Factor", f"{recovery_factor:.2f}"),

        ("Trade Quality", "Avg MFE (R)", f"+{avg_mfe:.2f}"),
        ("Trade Quality", "Avg MAE (R)", f"{avg_mae:.2f}"),
        ("Trade Quality", "% Trades MAE > 0.5R", f"{pct_mae_beyond_half_r:.2f}%"),
        ("Trade Quality", "Avg Duration (trading days)", f"{avg_dur_days:.2f}"),
        ("Costs", "Total Flat Brokerage/STT/DP (₹)",
         f"₹{total_round_trip_cost:,.0f}" if total_round_trip_cost == total_round_trip_cost else "n/a"),
        ("Costs", "Total Slippage Cost (₹)",
         f"₹{total_slippage_cost:,.0f}" if total_slippage_cost == total_slippage_cost else "n/a"),
        ("Costs", "Total Cost (₹)", f"₹{total_cost:,.0f}" if total_cost == total_cost else "n/a"),
        ("Costs", "Avg Cost / Trade (₹)",
         f"₹{avg_cost_per_trade:,.0f}" if avg_cost_per_trade == avg_cost_per_trade else "n/a"),
        ("Costs", "Cost Drag (% of Gross PnL)", f"{cost_drag_pct:.2f}%" if cost_drag_pct == cost_drag_pct else "n/a"),
        ("Risk", "% Trades Capital-Constrained",
         f"{pct_capital_constrained:.2f}%" if "Leverage_Constrained" in df.columns else "n/a"),
        ("Frequency", "Avg Trades / Month (span-based)", f"{trades_per_month:.2f}"),
        ("Frequency", "Avg Trades / Month (calendar)", f"{avg_trades_month_actual:.2f}"),
        ("Frequency", "Max Trades / Month", f"{max_trades_month}"),
        ("Frequency", "Min Trades / Month", f"{min_trades_month}"),
        ("Recent Edge", f"Rolling {window}-Trade Expectancy (Gross)",
         f"{rolling_exp_gross:.2f} R" if rolling_exp_gross == rolling_exp_gross else "n/a"),
        ("Recent Edge", f"Rolling {window}-Trade Expectancy (Net)",
         f"{rolling_exp:.2f} R" if rolling_exp == rolling_exp else "n/a"),
        ("Recent Edge", f"Rolling {window}-Trade Win Rate", f"{rolling_wr:.1%}" if rolling_wr == rolling_wr else "n/a"),
    ]

    table = pd.DataFrame(rows, columns=["Category", "Metric", "Value"]).drop(columns="Category")

    print("\n=======================================================")
    print("  KEY METRICS SUMMARY (SWING / D1)")
    print("=======================================================")
    print(table.to_string(index=False))

    os.makedirs(REPORT_FOLDER, exist_ok=True)
    table.to_csv(os.path.join(REPORT_FOLDER, "key_metrics_summary.csv"), index=False)

    monthly_counts_df = monthly_trade_counts.rename("Trades").reset_index()
    monthly_counts_df.columns = ["Month", "Trades"]
    monthly_counts_df["Month"] = monthly_counts_df["Month"].astype(str)
    monthly_counts_df.to_csv(os.path.join(REPORT_FOLDER, "monthly_trade_counts.csv"), index=False)

    if len(df) >= window:
        rolling_df = pd.DataFrame({
            "Trade_Index": df.index,
            "Entry_Time": df["Entry Time"].values,
            f"Rolling_{window}_Expectancy_R_Gross": df["R_Gross"].rolling(window).mean().round(3)
            if "R_Gross" in df.columns else float("nan"),
            f"Rolling_{window}_Expectancy_R_Net": df["R"].rolling(window).mean().round(3),
            f"Rolling_{window}_WinRate": (df["R"] > 0).rolling(window).mean().round(4),
        })
        rolling_df.to_csv(os.path.join(REPORT_FOLDER, "rolling_stats.csv"), index=False)


def backtest_historical_data_parallel(symbols_dict, max_workers=8):
    all_results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_symbol, sym, token): sym
            for sym, token in symbols_dict.items()
        }

        for future in as_completed(futures):
            sym = futures[future]
            try:
                result = future.result()
                if result:
                    all_results.append(pd.DataFrame(result))
            except Exception as e:
                print(f"Error processing {sym}: {e}")

    if not all_results:
        print("No trades found.")
        return

    df = pd.concat(all_results, ignore_index=True)

    df["Entry Time"] = pd.to_datetime(df["Entry Time"])
    df["Exit Time"] = pd.to_datetime(df["Exit Time"])

    df = df.sort_values("Entry Time").reset_index(drop=True)

    print_key_metrics_table(df)

    df.to_csv("positional_w1_backtest_results.csv", index=False)


# =========================================================

if __name__ == "__main__":
    initialize_logger(getattr(TradeType, "SWING", TradeType.INTRADAY), "d1", True)

    symbol_token_map = get_symbol_instrument_token(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

    backtest_historical_data_parallel(symbol_token_map)
