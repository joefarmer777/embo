"""Interactive Brokers connection, market data and orders (via ib_async).

IBKR has no API keys. IB Gateway runs on this computer, you log in there, and the bot
connects to it locally. In paper mode the bot refuses to run unless the logged-in
account id starts with "DU" (IBKR's paper prefix); in live mode it refuses a DU account.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from ib_async import IB, LimitOrder, MarketOrder, Stock, StopOrder

from ..config import ROOT
from ..models import NY, Bar

CACHE = ROOT / "data"


class IBKR:
    def __init__(self, host: str, port: int, client_id: int, paper: bool):
        self.ib = IB()
        self.paper = paper
        try:
            self.ib.connect(host, port, clientId=client_id, timeout=15)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Could not connect to IB Gateway at {host}:{port}. Is Gateway open and logged in, "
                f"with the API port set to {port}? ({e})") from e
        accts = self.ib.managedAccounts()
        if not accts:
            raise RuntimeError("Gateway reported no accounts.")
        self.account = accts[0]
        is_paper_acct = self.account.upper().startswith("DU")
        if paper and not is_paper_acct:
            self.ib.disconnect()
            raise RuntimeError(f"mode is paper but Gateway is logged into {self.account}, "
                               "which is not a paper (DU) account. Refusing.")
        if not paper and is_paper_acct:
            self.ib.disconnect()
            raise RuntimeError("mode is live but Gateway is logged into a paper account. Refusing.")
        self._contracts: dict[str, Stock] = {}
        self._pnl = None

    # ---- contracts / data -------------------------------------------------
    def contract(self, sym: str) -> Stock:
        if sym not in self._contracts:
            c = Stock(sym, "SMART", "USD")
            q = self.ib.qualifyContracts(c)
            if not q:
                raise RuntimeError(f"IBKR does not recognize symbol {sym}")
            self._contracts[sym] = q[0]
        return self._contracts[sym]

    def _to_bars(self, sym: str, raw) -> list[Bar]:
        out = []
        for b in raw:
            t = b.date
            if not isinstance(t, datetime):
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            out.append(Bar(sym, t, float(b.open), float(b.high), float(b.low), float(b.close),
                           float(b.volume)))
        return out

    def day_bars(self, sym: str, d: date) -> list[Bar]:
        """1-minute regular-session bars for one past day, cached in data/."""
        path = CACHE / sym / f"{d.isoformat()}.csv"
        if path.exists():
            return _read_csv(sym, path)
        end = datetime.combine(d, time(16, 0), tzinfo=NY).astimezone(timezone.utc)
        raw = self.ib.reqHistoricalData(self.contract(sym), endDateTime=end, durationStr="1 D",
                                        barSizeSetting="1 min", whatToShow="TRADES",
                                        useRTH=True, formatDate=2, timeout=120)
        bars = [b for b in self._to_bars(sym, raw) if b.ny.date() == d]
        if bars and datetime.now(NY) > datetime.combine(d, time(16, 5), tzinfo=NY):
            _write_csv(path, bars)
        self.ib.sleep(2)  # stay under IBKR's historical-data pacing limits
        return bars

    def recent_bars(self, sym: str, duration: str = "1800 S") -> list[Bar]:
        """Recent 1-minute bars (the last one may still be forming)."""
        raw = self.ib.reqHistoricalData(self.contract(sym), endDateTime="", durationStr=duration,
                                        barSizeSetting="1 min", whatToShow="TRADES",
                                        useRTH=True, formatDate=2, timeout=30)
        return self._to_bars(sym, raw)

    # ---- account / orders -------------------------------------------------
    def day_pnl(self) -> float:
        if self._pnl is None:
            self._pnl = self.ib.reqPnL(self.account)
            self.ib.sleep(2)
        v = self._pnl.dailyPnL
        return 0.0 if v is None or v != v else float(v)  # v != v catches NaN

    def position(self, sym: str) -> float:
        return sum(p.position for p in self.ib.positions(self.account) if p.contract.symbol == sym)

    def place_bracket(self, sym: str, side: str, qty: int, stop: float, target: float):
        """Market entry with an attached stop-loss and take-profit (one cancels the other)."""
        c = self.contract(sym)
        exit_side = "SELL" if side == "buy" else "BUY"
        parent = MarketOrder(side.upper(), qty, account=self.account, transmit=False, tif="DAY")
        parent.orderId = self.ib.client.getReqId()
        tp = LimitOrder(exit_side, qty, round(target, 2), account=self.account, tif="DAY",
                        parentId=parent.orderId, transmit=False)
        sl = StopOrder(exit_side, qty, round(stop, 2), account=self.account, tif="DAY",
                       parentId=parent.orderId, transmit=True)
        trades = [self.ib.placeOrder(c, o) for o in (parent, tp, sl)]
        self.ib.sleep(1)
        return trades

    def flatten_all(self) -> list[str]:
        """Cancel every open order and close every position at market."""
        self.ib.reqGlobalCancel()
        self.ib.sleep(1)
        closed = []
        for p in self.ib.positions(self.account):
            if p.position == 0 or p.contract.secType != "STK":
                continue
            side = "SELL" if p.position > 0 else "BUY"
            c = self.contract(p.contract.symbol)
            self.ib.placeOrder(c, MarketOrder(side, abs(p.position), account=self.account))
            closed.append(f"{p.contract.symbol}:{p.position}")
        self.ib.sleep(1)
        return closed

    def sleep(self, s: float):
        self.ib.sleep(s)

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()


def _write_csv(path: Path, bars: list[Bar]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.start.isoformat(), b.open, b.high, b.low, b.close, b.volume])


def _read_csv(sym: str, path: Path) -> list[Bar]:
    with open(path, newline="") as f:
        return [Bar(sym, datetime.fromisoformat(r["start"]), float(r["open"]), float(r["high"]),
                    float(r["low"]), float(r["close"]), float(r["volume"]))
                for r in csv.DictReader(f)]


def trading_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days
