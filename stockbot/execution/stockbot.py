"""
stockbot.py - VWAP reversion + swing trading bot on Alpaca paper trading.

Strategy:
  - Intraday: buy when price 0.2%+ below VWAP, RSI<40, volume spike
  - Exit intraday: price returns to VWAP or 0.5% stop loss
  - Overnight: hold if position profitable at 3:50pm ET (swing mode)
  - Swing exit: cut if down 2% from entry, take profit at +3%
  - Claude Opus reasons about each signal before submitting

Tickers: 50 liquid large-caps across sectors
Deploy Contract: boot ping, heartbeat every 5min, silent-death alert, UptimeRobot health endpoint

Run:
    python stockbot/execution/stockbot.py
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from shared.watchtower import heartbeat, notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / ".tmp" / "stockbot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except ImportError:
    print("Missing alpaca-py. Run: pip install alpaca-py pytz")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Missing anthropic. Run: pip install anthropic")
    sys.exit(1)

ET = ZoneInfo("America/New_York")

TICKERS = [
    # Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "AVGO", "QCOM",
    "TXN", "MU", "AMAT", "LRCX", "INTC",
    # Finance
    "JPM", "BAC", "GS", "MS", "WFC", "V", "MA", "PYPL", "AXP", "BLK",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Consumer
    "WMT", "HD", "COST", "NKE", "MCD", "SBUX", "TGT",
    # ETFs
    "SPY", "QQQ", "IWM", "XLF", "XLK", "XLV", "XLE",
]

VWAP_THRESHOLD = 0.002       # 0.2% below VWAP to enter
RSI_OVERSOLD = 40
VOLUME_MULTIPLIER = 1.5
STOP_LOSS_PCT = 0.005        # 0.5% intraday stop
SWING_STOP_PCT = 0.02        # 2% max loss from entry (swing)
SWING_PROFIT_PCT = 0.03      # 3% take profit (swing)
SWING_HOLD_MIN_PROFIT = 0.003  # hold overnight if up >= 0.3% at close
MAX_POSITION_PCT = 0.10      # 10% of portfolio per position (smaller since more tickers)
MAX_POSITIONS = 5
HEARTBEAT_INTERVAL = 300
LOOP_INTERVAL = 60
MARKET_OPEN = (9, 31)
SOFT_CLOSE = (15, 50)        # evaluate swing holds at this time
ALERT_WINDOW_MINUTES = 90

# Backtest: 312 raw signals/day on 50 tickers (2025-04-18).
# Adjusted for 5-position cap + Claude filtering: ~20 real fills/day expected.
EXPECTED_DAILY_TRADES = 20

TENANT_NAME = "stockbot"
SILENT_DEATH_RULE = f"0 fills in last {ALERT_WINDOW_MINUTES} market-minutes during market hours"

claude_client = anthropic.Anthropic()


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


def vwap(bars) -> float:
    cum_vol = cum_pv = 0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3
        cum_pv += typical * b.volume
        cum_vol += b.volume
    return cum_pv / cum_vol if cum_vol else bars[-1].close


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return MARKET_OPEN <= (now.hour, now.minute) <= SOFT_CLOSE


def is_soft_close() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return (now.hour, now.minute) >= SOFT_CLOSE


def claude_approve_trade(ticker: str, signal: dict, open_positions: dict) -> tuple[bool, str]:
    """Ask Claude Opus whether to take this trade. Returns (approved, reason)."""
    prompt = (
        f"You are evaluating a paper trade signal. Be brief and decisive.\n\n"
        f"Signal: BUY {ticker}\n"
        f"Current price: ${signal['price']:.2f}\n"
        f"VWAP: ${signal['vwap']:.2f} (price is {signal['pct_below']*100:.2f}% below VWAP)\n"
        f"RSI(14): {signal['rsi']:.1f}\n"
        f"Volume ratio vs 20-bar avg: {signal['vol_ratio']:.1f}x\n"
        f"Open positions ({len(open_positions)}/{MAX_POSITIONS}): {list(open_positions.keys()) or 'none'}\n\n"
        f"Should I take this trade? Reply with YES or NO followed by one sentence reason.\n"
        f"Consider: sector concentration, whether this ticker is already held, "
        f"and whether the signal looks genuine vs noise."
    )
    try:
        resp = claude_client.messages.create(
            model="claude-opus-4-7",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        approved = text.upper().startswith("YES")
        return approved, text
    except anthropic.RateLimitError:
        log.warning(f"Claude 429 on {ticker} signal — skipping, not retrying")
        return False, "Claude rate limited — signal skipped"
    except Exception as e:
        log.error(f"Claude error on {ticker}: {e}")
        return False, f"Claude error: {e}"


class StockBot:
    def __init__(self):
        api_key = os.environ["ALPACA_API_KEY"]
        api_secret = os.environ["ALPACA_API_SECRET"]
        self.trade = TradingClient(api_key, api_secret, paper=True)
        self.data = StockHistoricalDataClient(api_key, api_secret)
        self.tracked = {}     # ticker -> {entry_price, qty, stop, swing_mode}
        self.last_fill_time = time.time()
        self.fills_today = 0
        self.last_heartbeat = 0
        self.last_hourly_update = 0
        self.session_start = time.time()

    def get_portfolio_value(self) -> float:
        return float(self.trade.get_account().portfolio_value)

    def get_bars(self, ticker: str, limit: int = 30):
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Minute,
            limit=limit,
            feed="iex",
        )
        return self.data.get_stock_bars(req).data.get(ticker, [])

    def get_open_positions(self) -> dict:
        try:
            return {p.symbol: p for p in self.trade.get_all_positions()}
        except Exception:
            return {}

    def post_hourly_update(self):
        try:
            acct = self.trade.get_account()
            portfolio = float(acct.portfolio_value)
            start = 100_000.0  # Alpaca paper default
            pnl_today = float(acct.equity) - float(acct.last_equity)
            pnl_pct = pnl_today / float(acct.last_equity) * 100 if float(acct.last_equity) else 0

            positions = self.get_open_positions()
            pos_lines = []
            for sym, p in list(positions.items())[:5]:
                upl = float(p.unrealized_pl)
                uplpct = float(p.unrealized_plpc) * 100
                arrow = "UP" if upl >= 0 else "DN"
                pos_lines.append(f"`{sym}` {arrow} ${upl:+.2f} ({uplpct:+.2f}%)")

            uptime_hrs = int((time.time() - self.session_start) / 3600)
            color = 0x00cc44 if pnl_today >= 0 else 0xff4444
            now = datetime.now(ET)

            notifier.send("trade_alerts", embeds=[{
                "title": f"Stockbot Hourly Update",
                "description": f"51 tickers | VWAP Reversion + Swing | Claude Opus reasoning",
                "color": color,
                "fields": [
                    {"name": "Portfolio", "value": f"**${portfolio:,.0f}**\nToday: {pnl_pct:+.2f}% (${pnl_today:+,.0f})", "inline": True},
                    {"name": "Trades Today", "value": f"**{self.fills_today}** fills\nExpected: ~{EXPECTED_DAILY_TRADES}/day", "inline": True},
                    {"name": "Uptime", "value": f"{uptime_hrs}h | {len(positions)} open positions", "inline": True},
                    {"name": "Open Positions", "value": "\n".join(pos_lines) if pos_lines else "None", "inline": False},
                ],
                "footer": {"text": f"Next update in ~1h | {now.strftime('%Y-%m-%d %H:%M ET')}"},
            }])
            log.info(f"Hourly update posted | P&L: ${pnl_today:+,.0f} ({pnl_pct:+.2f}%) | Fills: {self.fills_today}")
        except Exception as e:
            log.error(f"Hourly update failed: {e}")

    def maybe_heartbeat(self):
        now = time.time()
        if now - self.last_heartbeat < HEARTBEAT_INTERVAL:
            return
        in_market = is_market_hours()
        metrics = {
            "fills_today": self.fills_today,
            "expected_daily_trades": EXPECTED_DAILY_TRADES,
            "open_positions": len(self.get_open_positions()),
            "market_hours": in_market,
        }
        heartbeat.beat(TENANT_NAME, status="ok", metrics=metrics)
        self.last_heartbeat = now

        if in_market:
            silence_mins = (now - self.last_fill_time) / 60
            if silence_mins > ALERT_WINDOW_MINUTES:
                heartbeat.beat(TENANT_NAME, status="silent_death", metrics=metrics)
                notifier.operational_failure_alert(
                    TENANT_NAME,
                    f"0 fills in last {int(silence_mins)} market-minutes. Strategy may be broken.",
                    metrics,
                )

    def check_entry(self, ticker: str, portfolio_value: float, open_positions: dict) -> bool:
        if ticker in open_positions or len(open_positions) >= MAX_POSITIONS:
            return False

        bars = self.get_bars(ticker, limit=30)
        if len(bars) < 20:
            return False

        closes = [b.close for b in bars]
        current = bars[-1]
        current_vwap = vwap(bars)
        current_rsi = rsi(closes)
        vol_avg = sum(b.volume for b in bars[-20:]) / 20
        vol_ratio = current.volume / vol_avg if vol_avg > 0 else 0
        pct_below = (current_vwap - current.close) / current_vwap

        if not (pct_below >= VWAP_THRESHOLD and current_rsi < RSI_OVERSOLD and vol_ratio >= VOLUME_MULTIPLIER):
            return False

        signal = {"price": current.close, "vwap": current_vwap, "pct_below": pct_below,
                  "rsi": current_rsi, "vol_ratio": vol_ratio}

        approved, reason = claude_approve_trade(ticker, signal, open_positions)
        log.info(f"Claude on {ticker}: {reason}")

        if not approved:
            return False

        max_dollars = portfolio_value * MAX_POSITION_PCT
        qty = int(max_dollars / current.close)
        if qty < 1:
            return False

        try:
            self.trade.submit_order(MarketOrderRequest(
                symbol=ticker, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            ))
            self.tracked[ticker] = {
                "entry_price": current.close,
                "qty": qty,
                "stop": current.close * (1 - STOP_LOSS_PCT),
                "swing_mode": False,
            }
            self.fills_today += 1
            self.last_fill_time = time.time()
            log.info(f"BUY {ticker} x{qty} @ {current.close:.2f} | VWAP={current_vwap:.2f} | RSI={current_rsi:.1f}")
            notifier.send("trade_alerts", embeds=[{
                "title": f"STOCKBOT BUY: {ticker}",
                "description": (
                    f"**Qty:** {qty} @ ${current.close:.2f}\n"
                    f"**VWAP:** ${current_vwap:.2f} ({pct_below*100:.2f}% below)\n"
                    f"**RSI:** {current_rsi:.1f} | **Vol:** {vol_ratio:.1f}x\n"
                    f"**Claude:** {reason}"
                ),
                "color": 0x00cc44,
            }])
            return True
        except Exception as e:
            log.error(f"Order failed {ticker}: {e}")
            return False

    def check_exits(self, open_positions: dict):
        for ticker, pos in list(open_positions.items()):
            bars = self.get_bars(ticker, limit=30)
            if not bars:
                continue
            current = bars[-1].close
            current_vwap = vwap(bars)
            tracked = self.tracked.get(ticker, {})
            entry = tracked.get("entry_price", current)
            swing_mode = tracked.get("swing_mode", False)

            pct_from_entry = (current - entry) / entry
            exit_reason = None

            # Universal: swing stop loss (2% down from entry)
            if pct_from_entry <= -SWING_STOP_PCT:
                exit_reason = f"Swing stop hit ({pct_from_entry*100:.2f}% from entry)"
            # Universal: swing take profit (3% up from entry)
            elif pct_from_entry >= SWING_PROFIT_PCT:
                exit_reason = f"Take profit hit ({pct_from_entry*100:.2f}% from entry)"
            # Intraday only: VWAP reversion
            elif not swing_mode and current >= current_vwap:
                exit_reason = f"VWAP reached (${current:.2f} >= VWAP ${current_vwap:.2f})"
            # Intraday only: tight stop
            elif not swing_mode:
                stop = tracked.get("stop", entry * (1 - STOP_LOSS_PCT))
                if current <= stop:
                    exit_reason = f"Intraday stop (${current:.2f} <= ${stop:.2f})"

            if exit_reason:
                try:
                    self.trade.close_position(ticker)
                    self.fills_today += 1
                    self.last_fill_time = time.time()
                    log.info(f"SELL {ticker}: {exit_reason}")
                    notifier.send("trade_alerts", embeds=[{
                        "title": f"STOCKBOT SELL: {ticker}",
                        "description": f"{exit_reason}\nP&L: {pct_from_entry*100:+.2f}%",
                        "color": 0xff6600 if pct_from_entry < 0 else 0x00cc44,
                    }])
                    self.tracked.pop(ticker, None)
                except Exception as e:
                    log.error(f"Exit failed {ticker}: {e}")

    def evaluate_swing_holds(self, open_positions: dict):
        """At soft close (3:50pm), decide whether to hold overnight or flatten."""
        log.info("Soft close: evaluating swing holds...")
        for ticker, pos in list(open_positions.items()):
            tracked = self.tracked.get(ticker, {})
            entry = tracked.get("entry_price", float(pos.avg_entry_price))
            current = float(pos.current_price)
            pct_from_entry = (current - entry) / entry

            if pct_from_entry >= SWING_HOLD_MIN_PROFIT:
                # Hold overnight — upgrade to swing mode with wider stop
                if ticker in self.tracked:
                    self.tracked[ticker]["swing_mode"] = True
                    self.tracked[ticker]["stop"] = current * (1 - SWING_STOP_PCT)
                log.info(f"HOLD {ticker} overnight: up {pct_from_entry*100:.2f}% from entry")
                notifier.send("trade_alerts", embeds=[{
                    "title": f"STOCKBOT SWING HOLD: {ticker}",
                    "description": f"Holding overnight. Up {pct_from_entry*100:.2f}% from entry.",
                    "color": 0x8800ff,
                }])
            else:
                # Flatten — not worth the overnight risk
                try:
                    self.trade.close_position(ticker)
                    log.info(f"FLATTEN {ticker}: {pct_from_entry*100:.2f}% at close — not worth holding")
                    self.tracked.pop(ticker, None)
                except Exception as e:
                    log.error(f"Flatten failed {ticker}: {e}")

    def run(self):
        heartbeat.register(
            TENANT_NAME,
            expected_interval_secs=HEARTBEAT_INTERVAL,
            silent_death_rule=SILENT_DEATH_RULE,
        )
        log.info(f"Stockbot started. {len(TICKERS)} tickers. Claude Opus reasoning enabled.")

        evaluated_swing_today = False
        last_date = None

        while True:
            now_et = datetime.now(ET)
            today = now_et.date()

            if today != last_date:
                self.fills_today = 0
                self.last_fill_time = time.time()
                evaluated_swing_today = False
                last_date = today
                log.info(f"New trading day: {today}")

            self.maybe_heartbeat()

            # Hourly Discord summary
            if time.time() - self.last_hourly_update >= 3600:
                self.post_hourly_update()
                self.last_hourly_update = time.time()

            if not is_market_hours():
                if is_soft_close() and not evaluated_swing_today:
                    open_positions = self.get_open_positions()
                    if open_positions:
                        self.evaluate_swing_holds(open_positions)
                    evaluated_swing_today = True
                time.sleep(LOOP_INTERVAL)
                continue

            try:
                portfolio_value = self.get_portfolio_value()
                open_positions = self.get_open_positions()

                self.check_exits(open_positions)
                open_positions = self.get_open_positions()

                for ticker in TICKERS:
                    self.check_entry(ticker, portfolio_value, open_positions)
                    open_positions = self.get_open_positions()

            except Exception as e:
                log.error(f"Loop error: {e}", exc_info=True)

            time.sleep(LOOP_INTERVAL)


def main():
    (PROJECT_ROOT / ".tmp").mkdir(exist_ok=True)
    bot = StockBot()
    bot.run()


if __name__ == "__main__":
    main()
