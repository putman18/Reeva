"""
stockbot_backtest.py - Signal frequency check on 1yr of historical data.

Deploy Contract requirement: must run BEFORE paper-trade deploy.
Outputs expected trades/week constant to paste into stockbot.py.

Run:
    python stockbot/execution/stockbot_backtest.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except ImportError:
    print("Missing alpaca-py. Run: pip install alpaca-py")
    sys.exit(1)

ET = ZoneInfo("America/New_York")

TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "AVGO", "QCOM",
    "TXN", "MU", "AMAT", "LRCX", "INTC",
    "JPM", "BAC", "GS", "MS", "WFC", "V", "MA", "PYPL", "AXP", "BLK",
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT",
    "XOM", "CVX", "COP", "SLB",
    "WMT", "HD", "COST", "NKE", "MCD", "SBUX", "TGT",
    "SPY", "QQQ", "IWM", "XLF", "XLK", "XLV", "XLE",
]
VWAP_THRESHOLD = 0.002
RSI_OVERSOLD = 40
VOLUME_MULTIPLIER = 1.5


def rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def vwap_from_bars(bars) -> float:
    cum_vol = 0
    cum_pv = 0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3
        cum_pv += typical * b.volume
        cum_vol += b.volume
    if cum_vol == 0:
        return bars[-1].close
    return cum_pv / cum_vol


def count_signals(bars_by_ticker: dict) -> dict:
    """Count how many entry signals each ticker would have generated."""
    results = {}
    for ticker, bars in bars_by_ticker.items():
        signals = 0
        # Group bars by day
        days = {}
        for b in bars:
            day = b.timestamp.astimezone(ET).date()
            days.setdefault(day, []).append(b)

        for day, day_bars in sorted(days.items()):
            # Walk through each bar using a rolling 30-bar window
            for i in range(30, len(day_bars)):
                window = day_bars[max(0, i - 29):i + 1]
                current = window[-1]

                # Skip bars outside 9:31 - 15:50 ET
                bar_time = current.timestamp.astimezone(ET)
                if bar_time.hour < 9 or (bar_time.hour == 9 and bar_time.minute < 31):
                    continue
                if bar_time.hour > 15 or (bar_time.hour == 15 and bar_time.minute > 50):
                    continue

                closes = [b.close for b in window]
                current_vwap = vwap_from_bars(window)
                current_rsi = rsi(closes)

                vol_avg = sum(b.volume for b in window[-20:]) / 20
                vol_ratio = current.volume / vol_avg if vol_avg > 0 else 0
                pct_below_vwap = (current_vwap - current.close) / current_vwap

                if (
                    pct_below_vwap >= VWAP_THRESHOLD
                    and current_rsi < RSI_OVERSOLD
                    and vol_ratio >= VOLUME_MULTIPLIER
                ):
                    signals += 1

        results[ticker] = signals

    return results


def main():
    api_key = os.environ["ALPACA_API_KEY"]
    api_secret = os.environ["ALPACA_API_SECRET"]
    client = StockHistoricalDataClient(api_key, api_secret)

    end = datetime.now(ET).replace(hour=16, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=365)

    print(f"Fetching 1yr of 1-min bars for {TICKERS}...")
    print(f"Range: {start.date()} to {end.date()}")
    print("(This may take 30-60 seconds)\n")

    req = StockBarsRequest(
        symbol_or_symbols=TICKERS,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed="iex",
    )
    resp = client.get_stock_bars(req)

    bars_by_ticker = {}
    for ticker in TICKERS:
        bars_by_ticker[ticker] = resp.data.get(ticker, [])
        print(f"  {ticker}: {len(bars_by_ticker[ticker])} bars loaded")

    print("\nCounting entry signals...")
    results = count_signals(bars_by_ticker)

    total_signals = sum(results.values())
    trading_days = 252
    trading_weeks = trading_days / 5

    print("\n" + "=" * 50)
    print("BACKTEST SIGNAL FREQUENCY RESULTS")
    print("=" * 50)
    for ticker, count in results.items():
        per_week = count / trading_weeks
        print(f"  {ticker}: {count} signals over 1yr ({per_week:.1f}/week)")
    print(f"\n  TOTAL: {total_signals} signals ({total_signals/trading_weeks:.1f}/week, {total_signals/trading_days:.1f}/day)")
    print("=" * 50)

    per_day = total_signals / trading_days
    print(f"\nRECORD THIS IN stockbot.py:")
    print(f"  EXPECTED_DAILY_TRADES = {int(round(per_day))}")
    print(f"\n(Deploy Contract: signal frequency check PASSED if >= 2 trades/day)")
    if per_day < 2:
        print(f"\nWARNING: Only {per_day:.1f} signals/day. Strategy too restrictive — loosen thresholds before deploying.")
        print("Consider: lower VWAP_THRESHOLD to 0.15%, raise RSI_OVERSOLD to 45, lower VOLUME_MULTIPLIER to 1.2x")
    else:
        print(f"\nSignal frequency OK: {per_day:.1f} trades/day expected. Ready to paper trade.")


if __name__ == "__main__":
    main()
