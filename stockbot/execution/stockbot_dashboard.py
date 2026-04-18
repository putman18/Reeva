"""
stockbot_dashboard.py - Read-only dashboard for stockbot.

Shows: open positions, today's P&L, P&L vs SPY, recent trade history.
Auto-refreshes every 30 seconds.

Run:
    python stockbot/execution/stockbot_dashboard.py
    Then open: http://localhost:8766
"""

import os
import sys
import json
import time
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("Missing fastapi/uvicorn. Run: pip install fastapi uvicorn")
    sys.exit(1)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except ImportError:
    print("Missing alpaca-py. Run: pip install alpaca-py pytz")
    sys.exit(1)

ET = ZoneInfo("America/New_York")
PORT = 8766

api_key = os.environ["ALPACA_API_KEY"]
api_secret = os.environ["ALPACA_API_SECRET"]
trade_client = TradingClient(api_key, api_secret, paper=True)
data_client = StockHistoricalDataClient(api_key, api_secret)

app = FastAPI()


def get_account():
    acct = trade_client.get_account()
    return {
        "portfolio_value": float(acct.portfolio_value),
        "cash": float(acct.cash),
        "equity": float(acct.equity),
        "last_equity": float(acct.last_equity),
        "pnl_today": float(acct.equity) - float(acct.last_equity),
        "pnl_today_pct": ((float(acct.equity) - float(acct.last_equity)) / float(acct.last_equity) * 100)
                         if float(acct.last_equity) else 0,
    }


def get_positions():
    try:
        positions = []
        for p in trade_client.get_all_positions():
            positions.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "entry": float(p.avg_entry_price),
                "current": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,
            })
        return sorted(positions, key=lambda x: x["unrealized_plpc"], reverse=True)
    except Exception:
        return []


def get_spy_performance():
    """Get SPY's return today for comparison."""
    try:
        req = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            limit=2,
            feed="iex",
        )
        bars = data_client.get_stock_bars(req).data.get("SPY", [])
        if len(bars) >= 2:
            prev_close = bars[-2].close
            curr = bars[-1].close
            return (curr - prev_close) / prev_close * 100
        return 0.0
    except Exception:
        return 0.0


def get_recent_trades(limit: int = 20):
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=limit)
        orders = trade_client.get_orders(req)
        trades = []
        for o in orders:
            if o.filled_at:
                trades.append({
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "qty": float(o.filled_qty or 0),
                    "price": float(o.filled_avg_price or 0),
                    "filled_at": o.filled_at.astimezone(ET).strftime("%m/%d %H:%M"),
                })
        return trades
    except Exception:
        return []


def color(val: float) -> str:
    return "#00cc44" if val >= 0 else "#ff4444"


@app.get("/", response_class=HTMLResponse)
def dashboard():
    acct = get_account()
    positions = get_positions()
    trades = get_recent_trades()
    spy_pct = get_spy_performance()
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    pos_rows = ""
    for p in positions:
        pl_color = color(p["unrealized_plpc"])
        pos_rows += f"""
        <tr>
            <td><strong>{p['symbol']}</strong></td>
            <td>{p['qty']:.0f}</td>
            <td>${p['entry']:.2f}</td>
            <td>${p['current']:.2f}</td>
            <td>${p['market_value']:,.0f}</td>
            <td style="color:{pl_color}">${p['unrealized_pl']:+,.2f}</td>
            <td style="color:{pl_color}">{p['unrealized_plpc']:+.2f}%</td>
        </tr>"""

    if not pos_rows:
        pos_rows = '<tr><td colspan="7" style="color:#666;text-align:center">No open positions</td></tr>'

    trade_rows = ""
    for t in trades:
        side_color = "#00cc44" if t["side"] == "buy" else "#ff6600"
        trade_rows += f"""
        <tr>
            <td>{t['filled_at']}</td>
            <td><strong>{t['symbol']}</strong></td>
            <td style="color:{side_color}">{t['side'].upper()}</td>
            <td>{t['qty']:.0f}</td>
            <td>${t['price']:.2f}</td>
        </tr>"""

    if not trade_rows:
        trade_rows = '<tr><td colspan="5" style="color:#666;text-align:center">No trades today</td></tr>'

    pnl_color = color(acct["pnl_today"])
    spy_color = color(spy_pct)
    alpha = acct["pnl_today_pct"] - spy_pct
    alpha_color = color(alpha)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Stockbot Dashboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ background:#0d0d0d; color:#e0e0e0; font-family:monospace; padding:20px; margin:0; }}
        h1 {{ color:#ffffff; font-size:1.4em; margin-bottom:4px; }}
        .sub {{ color:#666; font-size:0.85em; margin-bottom:24px; }}
        .cards {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
        .card {{ background:#1a1a1a; border:1px solid #2a2a2a; border-radius:8px; padding:16px 24px; min-width:160px; }}
        .card .label {{ color:#666; font-size:0.75em; text-transform:uppercase; letter-spacing:1px; }}
        .card .value {{ font-size:1.6em; font-weight:bold; margin-top:4px; }}
        table {{ width:100%; border-collapse:collapse; background:#1a1a1a; border-radius:8px; overflow:hidden; margin-bottom:24px; }}
        th {{ background:#222; color:#888; font-size:0.75em; text-transform:uppercase; letter-spacing:1px; padding:10px 14px; text-align:left; }}
        td {{ padding:10px 14px; border-top:1px solid #222; font-size:0.9em; }}
        tr:hover {{ background:#1f1f1f; }}
        h2 {{ color:#aaa; font-size:1em; text-transform:uppercase; letter-spacing:2px; margin-bottom:8px; }}
    </style>
</head>
<body>
    <h1>Stockbot Dashboard</h1>
    <div class="sub">Paper trading &nbsp;|&nbsp; Updated: {now} &nbsp;|&nbsp; Auto-refresh: 30s</div>

    <div class="cards">
        <div class="card">
            <div class="label">Portfolio</div>
            <div class="value">${acct['portfolio_value']:,.0f}</div>
        </div>
        <div class="card">
            <div class="label">Today P&L</div>
            <div class="value" style="color:{pnl_color}">${acct['pnl_today']:+,.0f} ({acct['pnl_today_pct']:+.2f}%)</div>
        </div>
        <div class="card">
            <div class="label">SPY Today</div>
            <div class="value" style="color:{spy_color}">{spy_pct:+.2f}%</div>
        </div>
        <div class="card">
            <div class="label">Alpha vs SPY</div>
            <div class="value" style="color:{alpha_color}">{alpha:+.2f}%</div>
        </div>
        <div class="card">
            <div class="label">Open Positions</div>
            <div class="value">{len(positions)}</div>
        </div>
        <div class="card">
            <div class="label">Cash</div>
            <div class="value">${acct['cash']:,.0f}</div>
        </div>
    </div>

    <h2>Open Positions</h2>
    <table>
        <thead><tr>
            <th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th>
            <th>Mkt Value</th><th>P&L $</th><th>P&L %</th>
        </tr></thead>
        <tbody>{pos_rows}</tbody>
    </table>

    <h2>Recent Trades</h2>
    <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th></tr></thead>
        <tbody>{trade_rows}</tbody>
    </table>
</body>
</html>"""
    return html


@app.get("/api/status")
def api_status():
    return {
        "account": get_account(),
        "positions": get_positions(),
        "spy_pct": get_spy_performance(),
        "checked_at": int(time.time()),
    }


if __name__ == "__main__":
    print(f"Dashboard running at http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
