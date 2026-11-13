"""Opening-range breakout.

Record the high/low of the first `range_minutes` of the session. After that, the first
bar that CLOSES above the high goes long (below the low goes short, if allowed). Stop at
the other side of the range (or its midpoint), target at `target_r` times the risk.
At most one trade per symbol per day. The risk layer flattens anything open before
the close. The same object runs in backtest and live, so what you test is what trades.
"""
from __future__ import annotations

from datetime import date

from ..models import Bar, Signal, minutes_since_open


class OpeningRangeBreakout:
    name = "orb"

    def __init__(self, range_minutes=15, target_r=2.0, stop="range", allow_short=True):
        self.range_minutes = range_minutes
        self.target_r = target_r
        self.stop_mode = stop
        self.allow_short = allow_short
        self._state: dict[str, dict] = {}

    def _st(self, sym: str, day: date) -> dict:
        st = self._state.get(sym)
        if st is None or st["day"] != day:
            st = {"day": day, "hi": None, "lo": None, "done": False}
            self._state[sym] = st
        return st

    def on_bar(self, bar: Bar) -> Signal | None:
        st = self._st(bar.symbol, bar.ny.date())
        m = minutes_since_open(bar.start)
        if m < 0:
            return None
        if m < self.range_minutes:
            st["hi"] = bar.high if st["hi"] is None else max(st["hi"], bar.high)
            st["lo"] = bar.low if st["lo"] is None else min(st["lo"], bar.low)
            return None
        if st["done"] or st["hi"] is None:
            return None
        hi, lo = st["hi"], st["lo"]
        mid = (hi + lo) / 2
        if bar.close > hi:
            stop = lo if self.stop_mode == "range" else mid
            risk = bar.close - stop
            if risk <= 0:
                return None
            st["done"] = True
            return Signal(bar.symbol, "buy", bar.close, round(stop, 2),
                          round(bar.close + self.target_r * risk, 2),
                          f"close {bar.close:.2f} broke {self.range_minutes}m range high {hi:.2f}")
        if self.allow_short and bar.close < lo:
            stop = hi if self.stop_mode == "range" else mid
            risk = stop - bar.close
            if risk <= 0:
                return None
            st["done"] = True
            return Signal(bar.symbol, "sell", bar.close, round(stop, 2),
                          round(bar.close - self.target_r * risk, 2),
                          f"close {bar.close:.2f} broke {self.range_minutes}m range low {lo:.2f}")
        return None
