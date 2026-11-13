from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)


@dataclass
class Bar:
    symbol: str
    start: datetime  # tz-aware, bar open time
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def ny(self) -> datetime:
        return self.start.astimezone(NY)


@dataclass
class Signal:
    symbol: str
    side: str      # "buy" or "sell"
    entry_ref: float
    stop: float
    target: float
    reason: str


def minutes_since_open(t: datetime) -> float:
    t = t.astimezone(NY)
    return (t.hour * 60 + t.minute) - (OPEN.hour * 60 + OPEN.minute) + t.second / 60


def minutes_to_close(t: datetime) -> float:
    t = t.astimezone(NY)
    return (CLOSE.hour * 60 + CLOSE.minute) - (t.hour * 60 + t.minute) - t.second / 60
