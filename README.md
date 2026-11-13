# embo

A day-trading bot for Interactive Brokers. Paper trading by default. You run it, you turn it on, and you own every trade it makes.

**Strategy:** opening-range breakout. It records the high and low of the first 15 minutes, then takes the first 1-minute close outside that range (long above, short below). The stop goes at the other side of the range and the target at 2x the risk. At most one trade per symbol per day.

**Risk limits** (`config/settings.yaml`): a max position value, a fixed dollar risk per trade, a daily loss limit that flattens and stops trading for the day, a max trades per day cap, no new entries in the last 15 minutes, and everything flattened 5 minutes before the close.

## Setup (Windows, PowerShell)

1. Install IB Gateway, log in with **IB API** + **Paper Trading**. Under Configure > Settings > API > Settings: port 4002, Read-Only API unchecked, localhost only checked.
2. In the IBKR Client Portal, turn on market data sharing with the paper account (Settings > Paper Trading Account), or the bot gets no prices.
3. Install the bot:

```powershell
git clone https://github.com/joefarmer777/embo
cd embo
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Use

```powershell
python -m bot backtest                                  # dates from settings.yaml
python -m bot backtest --start 2026-10-01 --end 2026-11-12
python -m bot trade                                     # start before 8:30 AM Central
python -m bot report                                    # today's trades and why
```

The first backtest is slow because IBKR paces historical data requests. Bars are cached in `data/`, so later runs are fast. Every backtest trade is written to `logs/backtest_*.csv`, and every live event to `logs/YYYY-MM-DD.jsonl`.

`trade` runs one session and exits after the close. Ctrl+C cancels open orders and closes positions before quitting. Gateway must stay open and logged in the whole time.

## Safety

- `mode: paper` is the default. Live trading needs both `mode: live` and `live_confirm: true`.
- In paper mode the bot refuses to run unless the Gateway account starts with `DU` (paper). In live mode it refuses a paper account.
- There are no API keys. Nothing secret lives in this repo.

Most retail day-trading strategies lose money after fees and slippage. Trust the backtest, then weeks of paper results, before anything else.
