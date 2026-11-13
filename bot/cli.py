"""python -m bot backtest | trade | report"""
from __future__ import annotations

import argparse
import csv
from datetime import date

from . import config, journal


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="replay past data through the strategy")
    b.add_argument("--start")
    b.add_argument("--end")
    sub.add_parser("trade", help="run today's session (paper unless settings say live)")
    r = sub.add_parser("report", help="show a day's trade log")
    r.add_argument("--date")
    a = p.parse_args(argv)

    if a.cmd == "report":
        journal.report(date.fromisoformat(a.date) if a.date else None)
        return

    s = config.load()
    if a.cmd == "trade":
        from . import trader
        trader.run(s)
        return

    from . import backtest
    from .brokers import connect
    from .brokers.ibkr import trading_days

    start = config.as_date(a.start or s.backtest.get("start"))
    end = config.as_date(a.end or s.backtest.get("end"))
    broker = connect(s)
    print(f"Connected to {broker.account}. Pulling 1-minute bars {start} to {end} "
          f"for {', '.join(s.symbols)} (slow the first time, cached after).")
    days = {}
    try:
        for d in trading_days(start, end):
            day = {}
            for sym in s.symbols:
                bars = broker.day_bars(sym, d)
                if bars:
                    day[sym] = bars
            if day:
                days[d] = day
                print(f"  {d}: ok")
    finally:
        broker.disconnect()

    trades = backtest.run(days, s)
    eq = float(s.backtest.get("starting_equity", 25000))
    print()
    print(backtest.summarize(trades, eq))
    out = config.ROOT / "logs" / f"backtest_{start}_{end}.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "side", "qty", "entry_time", "entry", "exit_time", "exit",
                    "pnl", "exit_reason", "reason"])
        for t in trades:
            w.writerow([t.symbol, t.side, t.qty, t.entry_time, t.entry, t.exit_time, t.exit,
                        t.pnl, t.exit_reason, t.reason])
    print(f"Every trade: {out}")
