from datetime import date, datetime, timedelta

import pytest

from bot.backtest import run, summarize
from bot.config import Settings
from bot.models import NY, Bar
from bot.risk import RiskManager
from bot.strategies.orb import OpeningRangeBreakout

D = date(2026, 11, 10)


def bars(sym, prices, start="09:30"):
    """prices: list of (o,h,l,c) one per minute."""
    h, m = map(int, start.split(":"))
    t0 = datetime(D.year, D.month, D.day, h, m, tzinfo=NY)
    return [Bar(sym, t0 + timedelta(minutes=i), o, hi, lo, c, 1000) for i, (o, hi, lo, c) in enumerate(prices)]


def flat(n, p=100.0):
    return [(p, p + 0.5, p - 0.5, p)] * n


def settings(**risk):
    r = {"max_position_usd": 25000, "risk_per_trade_usd": 250, "daily_loss_limit_usd": 500,
         "max_trades_per_day": 6, "no_entry_last_minutes": 15, "flatten_minutes_before_close": 5}
    r.update(risk)
    return Settings({"mode": "paper", "symbols": ["SPY"],
                     "strategy": {"name": "orb", "range_minutes": 15, "target_r": 2.0},
                     "risk": r, "costs": {"commission_per_share": 0.005, "min_commission": 1.0,
                                          "slippage_bps": 0}})


def test_orb_long_signal_after_range():
    s = OpeningRangeBreakout()
    bs = bars("SPY", flat(15) + [(100, 101.2, 100, 101)])
    sigs = [s.on_bar(b) for b in bs]
    assert all(x is None for x in sigs[:15])
    sig = sigs[15]
    assert sig.side == "buy" and sig.stop == 99.5 and sig.target == pytest.approx(104.0)


def test_orb_one_trade_per_day():
    s = OpeningRangeBreakout()
    bs = bars("SPY", flat(15) + [(100, 101.2, 100, 101)] * 3)
    assert sum(1 for b in bs if s.on_bar(b)) == 1


def test_risk_sizing_caps():
    from bot.models import Signal
    rm = RiskManager({"max_position_usd": 25000, "risk_per_trade_usd": 250})
    t = datetime(2026, 11, 10, 10, 0, tzinfo=NY)
    qty, _ = rm.size(Signal("SPY", "buy", 100, 99.5, 101, ""), t)
    assert qty == 250  # 25000/100 caps it below 250/0.5 = 500
    late = datetime(2026, 11, 10, 15, 50, tzinfo=NY)
    assert rm.size(Signal("SPY", "buy", 100, 99.5, 101, ""), late)[0] == 0


def test_backtest_target_hit():
    seq = flat(15) + [(100, 101.2, 100, 101)] + [(101, 101.5, 100.8, 101.2)] + [(101.2, 105, 101.1, 104.5)] + flat(360, 104)
    trades = run({D: {"SPY": bars("SPY", seq)}}, settings())
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "target" and t.pnl > 0
    assert "Trades: 1" in summarize(trades, 25000)


def test_backtest_stop_hit():
    seq = flat(15) + [(100, 101.2, 100, 101)] + [(101, 101, 99, 99.2)] + flat(360, 99)
    trades = run({D: {"SPY": bars("SPY", seq)}}, settings())
    assert trades[0].exit_reason == "stop" and trades[0].pnl < 0


def test_backtest_flattens_before_close():
    seq = flat(15) + [(100, 101.2, 100, 101)] + flat(374, 101)
    trades = run({D: {"SPY": bars("SPY", seq)}}, settings())
    assert trades[0].exit_reason == "end of day"
    assert datetime.fromisoformat(trades[0].exit_time).astimezone(NY).hour == 15


def test_live_requires_confirm(tmp_path):
    from bot import config
    p = tmp_path / "s.yaml"
    p.write_text("mode: live\nbroker: ibkr\n")
    with pytest.raises(ValueError):
        config.load(p)


def test_target_fill_has_no_slippage():
    s = settings()
    s.raw["costs"]["slippage_bps"] = 10
    seq = flat(15) + [(100, 101.2, 100, 101)] + [(101, 101.5, 100.8, 101.2)] + [(101.2, 105, 101.1, 104.5)] + flat(360, 104)
    t = run({D: {"SPY": bars("SPY", seq)}}, s)[0]
    assert t.exit_reason == "target" and t.exit == pytest.approx(104.0)
    assert t.pnl == pytest.approx(t.gross - t.fees - t.slippage, abs=0.02)
