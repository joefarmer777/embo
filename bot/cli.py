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
    sw = sub.add_parser("sweep", help="compare strategy variants on the same data")
    sw.add_argument("--start")
    sw.add_argument("--end")
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

    start = config.as_date(a.start or s.backtest.get("start"))
    end = config.as_date(a.end or s.backtest.get("end"))
    days = load_days(s, start, end)

    if a.cmd == "sweep":
        sweep(s, days)
        return

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


def load_days(s, start, end):
    """{date: {symbol: bars}} from the data/ cache, connecting to IBKR only for missing days."""
    from .brokers.ibkr import CACHE, _read_csv, trading_days

    wanted = trading_days(start, end)
    missing = [d for d in wanted for sym in s.symbols
               if not (CACHE / sym / f"{d.isoformat()}.csv").exists()]
    broker = None
    if missing:
        from .brokers import connect
        broker = connect(s)
        print(f"Connected to {broker.account}. Pulling 1-minute bars {start} to {end} "
              f"for {', '.join(s.symbols)} (slow the first time, cached after).")
    days = {}
    try:
        for d in wanted:
            day = {}
            for sym in s.symbols:
                path = CACHE / sym / f"{d.isoformat()}.csv"
                bars = _read_csv(sym, path) if path.exists() else (broker.day_bars(sym, d) if broker else [])
                if bars:
                    day[sym] = bars
            if day:
                days[d] = day
                if broker:
                    print(f"  {d}: ok")
    finally:
        if broker:
            broker.disconnect()
    return days


def sweep(s, days):
    """Run every combination of range length, long/short, and profit target on the same data."""
    import copy

    from . import backtest
    from .config import Settings

    eq = float(s.backtest.get("starting_equity", 25000))
    rows = []
    for rng in (15, 30):
        for longs_only in (False, True):
            for tr in (2.0, 1.5, 1.0, 0.5, 0.25):
                raw = copy.deepcopy(s.raw)
                raw["strategy"].update(range_minutes=rng, allow_short=not longs_only, target_r=tr)
                trades = backtest.run(days, Settings(raw))
                n = len(trades)
                wins = sum(1 for t in trades if t.pnl > 0)
                net = sum(t.pnl for t in trades)
                e = peak = eq
                dd = 0.0
                for t in sorted(trades, key=lambda x: x.exit_time):
                    e += t.pnl
                    peak = max(peak, e)
                    dd = max(dd, peak - e)
                hit = sum(1 for t in trades if t.exit_reason == "target")
                rows.append((rng, "longs" if longs_only else "both", tr, n,
                             wins / n if n else 0, hit / n if n else 0, net, dd))
    rows.sort(key=lambda r: r[6], reverse=True)
    print(f"{len(days)} trading days, best net P&L first\n")
    print(f"{'range':>5} {'sides':>6} {'target':>6} {'trades':>6} {'win%':>5} {'hit tgt':>7} "
          f"{'net P&L':>10} {'max DD':>9}")
    for r in rows:
        print(f"{r[0]:>4}m {r[1]:>6} {r[2]:>5}R {r[3]:>6} {r[4]:>5.0%} {r[5]:>7.0%} "
              f"{r[6]:>10,.0f} {r[7]:>9,.0f}")
    print("\nTo use one, set range_minutes, allow_short and target_r in config/settings.yaml.")
