"""Daily trade log: one JSON line per event in logs/YYYY-MM-DD.jsonl, plus a report."""
from __future__ import annotations

import json
from datetime import date, datetime

from .config import ROOT

LOGS = ROOT / "logs"


def log(event: str, **fields):
    LOGS.mkdir(exist_ok=True)
    now = datetime.now().astimezone()
    rec = {"ts": now.isoformat(timespec="seconds"), "event": event, **fields}
    with open(LOGS / f"{now.date().isoformat()}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"{rec['ts'][11:19]} {event} " + " ".join(f"{k}={v}" for k, v in fields.items()), flush=True)


def report(day: date | None = None):
    day = day or date.today()
    p = LOGS / f"{day.isoformat()}.jsonl"
    if not p.exists():
        print(f"No log for {day}.")
        return
    events = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"Trade log for {day}")
    for e in events:
        if e["event"] in ("entry_submitted", "exit", "fill", "blocked", "halted", "flatten", "error"):
            extra = {k: v for k, v in e.items() if k not in ("ts", "event")}
            print(f"  {e['ts'][11:19]}  {e['event']:<16} {extra}")
    pnl = [e for e in events if e["event"] == "day_end"]
    if pnl:
        print(f"Day P&L: {pnl[-1].get('day_pnl')}")
