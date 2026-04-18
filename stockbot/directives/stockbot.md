# Stockbot Directive

## Goal
Intraday VWAP-reversion strategy on Alpaca paper trading.
5 tickers: SPY, QQQ, AAPL, MSFT, NVDA.
No overnight holds — flatten all positions by 3:50pm ET.

## Strategy: VWAP Reversion (1-min bars)

**Entry (long):**
- Price < VWAP by >= 0.2%
- RSI(14) < 40 (oversold)
- Volume on current bar > 1.5x 20-bar average volume

**Entry (short):** Not used in v1 — long-only to keep it simple.

**Exit:**
- Price returns to VWAP (take profit)
- Stop loss: 0.5% below entry
- Hard exit: 3:50pm ET regardless

**Position sizing:**
- Max 20% of portfolio per position
- Max 3 simultaneous positions

## Expected signal frequency
- Based on historical backtesting: 3-8 trades/day across 5 tickers
- Alert if 0 fills in any 90-minute market window (not submissions — fills)

## Deploy Contract requirements
1. Boot ping to Discord on startup
2. Heartbeat every 5 minutes via shared/watchtower
3. Silent-death rule: "0 fills in last 90 market minutes during market hours"
4. UptimeRobot pings health endpoint

## Market hours
- Market open: 9:30 ET
- Market close: 4:00 ET
- Bot active: 9:31 ET to 3:50 ET (don't trade open/close chaos)
- Heartbeat pauses outside market hours (but still beats liveness)

## Files
- `execution/stockbot.py` — main bot loop
- `execution/stockbot_backtest.py` — historical signal frequency check
- `execution/stockbot_deploy.py` — deploy to Hostinger VPS

## Alpaca paper trading
- Base URL: https://paper-api.alpaca.markets
- Keys: ALPACA_API_KEY + ALPACA_API_SECRET in .env
- Free paper trading, no fees
