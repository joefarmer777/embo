"""Backtester: replays 1-minute bars through the same strategy and risk limits.

Fills: entry at the NEXT bar's open plus slippage. Stop and target are checked on every
later bar; if both are touched in the same bar the stop is assumed (conservative).
Targets are limit orders, so they fill at the target price with no slippage. Stops and
end-of-day exits are market orders and pay slippage.
Anything open at the flatten time exits at that bar's close. Commission both ways.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from .risk import RiskManager, commission, slip
from .strategies import build


@dataclass
class Trade:
    symbol: str
    side: str
    qty: int
    entry_time: str
    entry: float
    exit_time: str = ""
    exit: float = 0.0
    reason: str = ""
    exit_reason: str = ""
    pnl: float = 0.0
    gross: float = 0.0       # before commission and slippage
    fees: float = 0.0
    slippage: float = 0.0
    entry_raw: float = 0.0


def run(days: dict, settings) -> list[Trade]:
    """days: {date: {symbol: [Bar, ...]}}"""
    costs = settings.costs
    trades: list[Trade] = []
    for d in sorted(days):
        strat = build(settings.strategy)
        risk = RiskManager(settings.risk)
        risk.new_day(d)
        by_time: dict = defaultdict(list)
        for sym, bars in days[d].items():
            for i, b in enumerate(bars):
                by_time[b.start].append((sym, i, b))
        series = days[d]
        pending: dict[str, tuple] = {}   # symbol -> (signal, qty) waiting for next bar open
        open_pos: dict[str, tuple] = {}  # symbol -> (Trade, stop, target)
        realized = 0.0
        flattened = False

        def close(sym, price, t, why, limit=False):
            nonlocal realized
            tr, _, _ = open_pos.pop(sym)
            exit_side = "sell" if tr.side == "buy" else "buy"
            px = price if limit else slip(price, exit_side, costs)
            sign = 1 if tr.side == "buy" else -1
            net_px = (px - tr.entry) * tr.qty * sign
            tr.gross = round((price - tr.entry_raw) * tr.qty * sign, 2)
            tr.fees = round(commission(tr.qty, costs) * 2, 2)
            tr.slippage = round(tr.gross - net_px, 2)
            tr.exit, tr.exit_time, tr.exit_reason = round(px, 4), t.isoformat(), why
            tr.pnl = round(net_px - tr.fees, 2)
            realized += tr.pnl
            trades.append(tr)

        for t in sorted(by_time):
            for sym, i, b in by_time[t]:
                # fill pending entry at this bar's open
                if sym in pending and not flattened:
                    sig, qty = pending.pop(sym)
                    px = slip(b.open, sig.side, costs)
                    open_pos[sym] = (Trade(sym, sig.side, qty, t.isoformat(), round(px, 4),
                                           reason=sig.reason, entry_raw=b.open), sig.stop, sig.target)
                    risk.record_entry()
                # manage open position
                if sym in open_pos:
                    tr, stop, target = open_pos[sym]
                    if tr.side == "buy":
                        if b.low <= stop:
                            close(sym, min(stop, b.open), t, "stop")
                        elif b.high >= target:
                            close(sym, max(target, b.open), t, "target", limit=True)
                    else:
                        if b.high >= stop:
                            close(sym, max(stop, b.open), t, "stop")
                        elif b.low <= target:
                            close(sym, min(target, b.open), t, "target", limit=True)
            bar_end = t + timedelta(minutes=1)  # 1-minute bars: decisions happen at bar close
            # daily loss limit on realized + open P&L at bar close
            open_pnl = 0.0
            for sym, (tr, _, _) in open_pos.items():
                last = next((b for s, _, b in by_time[t] if s == sym), None)
                if last:
                    open_pnl += ((last.close - tr.entry) if tr.side == "buy" else (tr.entry - last.close)) * tr.qty
            hit = risk.check_loss(realized + open_pnl)
            if (hit or risk.should_flatten(bar_end)) and not flattened:
                for sym in list(open_pos):
                    last = next((b for s, _, b in by_time[t] if s == sym), None)
                    if last:
                        close(sym, last.close, t, "loss limit" if hit else "end of day")
                pending.clear()
                flattened = risk.should_flatten(bar_end)
                if hit:
                    continue
            if flattened or risk.halted:
                continue
            # new signals on bar close
            for sym, i, b in by_time[t]:
                sig = strat.on_bar(b)
                if sig and sym not in open_pos and sym not in pending:
                    qty, why = risk.size(sig, bar_end)
                    if qty:
                        pending[sym] = (sig, qty)
        # safety: anything still open at end of data
        for sym in list(open_pos):
            last = series[sym][-1]
            close(sym, last.close, last.start, "end of data")
    return trades


def summarize(trades: list[Trade], starting_equity: float) -> str:
    if not trades:
        return "No trades in this period."
    wins = [t for t in trades if t.pnl > 0]
    equity, peak, max_dd = starting_equity, starting_equity, 0.0
    for t in sorted(trades, key=lambda x: x.exit_time):
        equity += t.pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    total = sum(t.pnl for t in trades)
    avg_w = sum(t.pnl for t in wins) / len(wins) if wins else 0
    losses = [t for t in trades if t.pnl <= 0]
    avg_l = sum(t.pnl for t in losses) / len(losses) if losses else 0
    days = len({t.entry_time[:10] for t in trades})
    ordered = sorted(trades, key=lambda x: x.entry_time)
    half = len(ordered) // 2
    h1, h2 = sum(t.pnl for t in ordered[:half]), sum(t.pnl for t in ordered[half:])
    gross = sum(t.gross for t in trades)
    fees = sum(t.fees for t in trades)
    slp = sum(t.slippage for t in trades)
    exits = {}
    for t in trades:
        exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
    return "\n".join([
        f"Trades: {len(trades)} over {days} trading days",
        f"Win rate: {len(wins) / len(trades):.0%}  (avg win ${avg_w:,.2f}, avg loss ${avg_l:,.2f})",
        "Exits: " + ", ".join(f"{k} {v / len(trades):.0%}" for k, v in sorted(exits.items(), key=lambda kv: -kv[1])),
        f"P&L before costs: ${gross:,.2f}   commissions: -${fees:,.2f}   slippage: -${slp:,.2f}",
        f"Net P&L after fees and slippage: ${total:,.2f}  ({total / starting_equity:.1%} of ${starting_equity:,.0f})",
        f"First half of trades: ${h1:,.2f}   second half: ${h2:,.2f}",
        f"Max drawdown: ${max_dd:,.2f}  ({max_dd / starting_equity:.1%})",
    ])
