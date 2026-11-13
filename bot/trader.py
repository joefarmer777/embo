"""Live loop. Paper by default. Runs one session, then exits after the close.

Every minute (a few seconds after the bar closes) it pulls the latest 1-minute bars,
feeds newly completed bars to the strategy, checks the daily loss limit, and places a
bracket order (market entry + stop + target) when the strategy fires and risk allows.
It flattens everything before the close, on the loss limit, and on Ctrl+C.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import journal
from .brokers import connect
from .models import NY, OPEN, CLOSE
from .risk import RiskManager
from .strategies import build


def run(settings):
    broker = connect(settings)
    journal.log("start", mode=settings.mode, account=broker.account, symbols=",".join(settings.symbols))

    def on_fill(trade, fill):
        e = fill.execution
        journal.log("fill", symbol=trade.contract.symbol, side=e.side, qty=e.shares, price=e.price)

    broker.ib.execDetailsEvent += on_fill

    strat = build(settings.strategy)
    risk = RiskManager(settings.risk)
    last_seen: dict[str, datetime] = {}
    flattened = False
    today = datetime.now(NY).date()
    risk.new_day(today)
    journal.log("new_day", date=today.isoformat())
    if datetime.now(NY).weekday() >= 5:
        journal.log("closed", note="weekend, nothing to do")
        broker.disconnect()
        return

    open_dt = datetime.combine(today, OPEN, tzinfo=NY)
    close_dt = datetime.combine(today, CLOSE, tzinfo=NY)
    try:
        while True:
            now = datetime.now(NY)
            if now >= close_dt + timedelta(minutes=2):
                break
            if now < open_dt:
                broker.sleep(min(30, (open_dt - now).total_seconds() + 1))
                continue
            # wait until 3s after the next minute boundary
            nxt = now.replace(second=3, microsecond=0)
            if nxt <= now:
                nxt += timedelta(minutes=1)
            broker.sleep((nxt - now).total_seconds())
            now = datetime.now(NY)

            if not flattened and risk.should_flatten(now):
                closed = broker.flatten_all()
                journal.log("flatten", why="end of day", closed=",".join(closed) or "none")
                flattened = True
            if flattened:
                continue

            pnl = broker.day_pnl()
            if risk.check_loss(pnl):
                closed = broker.flatten_all()
                journal.log("halted", why="daily loss limit", day_pnl=round(pnl, 2),
                            closed=",".join(closed) or "none")
            if risk.halted:
                continue

            for sym in settings.symbols:
                try:
                    bars = broker.recent_bars(sym, "1 D" if sym not in last_seen else "1800 S")
                except Exception as e:  # noqa: BLE001
                    journal.log("error", symbol=sym, error=str(e))
                    continue
                done = [b for b in bars if b.ny.date() == today and b.start + timedelta(minutes=1) <= now
                        and (sym not in last_seen or b.start > last_seen[sym])]
                for b in done:
                    last_seen[sym] = b.start
                    sig = strat.on_bar(b)
                    if not sig:
                        continue
                    if broker.position(sym) != 0:
                        journal.log("blocked", symbol=sym, why="already in a position", signal=sig.reason)
                        continue
                    if b is not done[-1]:
                        journal.log("blocked", symbol=sym, why="stale signal (bot started late)",
                                    signal=sig.reason)
                        continue
                    qty, why = risk.size(sig, now)
                    if not qty:
                        journal.log("blocked", symbol=sym, why=why, signal=sig.reason)
                        continue
                    broker.place_bracket(sym, sig.side, qty, sig.stop, sig.target)
                    risk.record_entry()
                    journal.log("entry_submitted", symbol=sym, side=sig.side, qty=qty,
                                ref_price=sig.entry_ref, stop=sig.stop, target=sig.target,
                                reason=sig.reason)
    except KeyboardInterrupt:
        closed = broker.flatten_all()
        journal.log("flatten", why="stopped by you (Ctrl+C)", closed=",".join(closed) or "none")
    finally:
        try:
            journal.log("day_end", day_pnl=round(broker.day_pnl(), 2))
        except Exception:  # noqa: BLE001
            pass
        broker.disconnect()
