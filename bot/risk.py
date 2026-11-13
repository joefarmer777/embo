"""Risk limits shared by backtest and live trading."""
from __future__ import annotations

import math
from datetime import date, datetime

from .models import Signal, minutes_since_open, minutes_to_close


class RiskManager:
    def __init__(self, cfg: dict):
        self.max_position_usd = float(cfg.get("max_position_usd", 25000))
        self.risk_per_trade_usd = float(cfg.get("risk_per_trade_usd", 250))
        self.daily_loss_limit_usd = float(cfg.get("daily_loss_limit_usd", 500))
        self.max_trades_per_day = int(cfg.get("max_trades_per_day", 6))
        self.no_entry_last = float(cfg.get("no_entry_last_minutes", 15))
        self.flatten_before = float(cfg.get("flatten_minutes_before_close", 5))
        self.day: date | None = None
        self.trades_today = 0
        self.halted = False

    def new_day(self, d: date):
        if d != self.day:
            self.day, self.trades_today, self.halted = d, 0, False

    def check_loss(self, day_pnl: float) -> bool:
        """Returns True if the daily loss limit is now hit (halts for the day)."""
        if not self.halted and day_pnl <= -self.daily_loss_limit_usd:
            self.halted = True
            return True
        return False

    def should_flatten(self, t: datetime) -> bool:
        return minutes_to_close(t) <= self.flatten_before

    def size(self, sig: Signal, t: datetime) -> tuple[int, str]:
        """Shares to trade, or (0, reason it was blocked)."""
        if self.halted:
            return 0, "daily loss limit hit"
        if self.trades_today >= self.max_trades_per_day:
            return 0, "max trades per day"
        if minutes_since_open(t) < 0 or minutes_to_close(t) <= self.no_entry_last:
            return 0, "outside entry window"
        per_share_risk = abs(sig.entry_ref - sig.stop)
        if per_share_risk <= 0 or sig.entry_ref <= 0:
            return 0, "bad stop"
        qty = min(math.floor(self.risk_per_trade_usd / per_share_risk),
                  math.floor(self.max_position_usd / sig.entry_ref))
        if qty < 1:
            return 0, "position too small"
        return qty, ""

    def record_entry(self):
        self.trades_today += 1


def commission(shares: float, cfg: dict) -> float:
    return max(float(cfg.get("min_commission", 1.0)),
               abs(shares) * float(cfg.get("commission_per_share", 0.005)))


def slip(price: float, side: str, cfg: dict) -> float:
    """Price after slippage. side is the direction of THIS fill (buy pays up)."""
    s = price * float(cfg.get("slippage_bps", 2)) / 10000
    return price + s if side == "buy" else price - s
