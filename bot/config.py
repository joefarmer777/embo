"""Loads config/settings.yaml (and .env for overrides)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # optional
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    raw: dict = field(default_factory=dict)

    @property
    def mode(self) -> str:
        return str(self.raw.get("mode", "paper")).lower()

    @property
    def is_paper(self) -> bool:
        return self.mode != "live"

    @property
    def symbols(self) -> list[str]:
        return [s.upper() for s in self.raw.get("symbols", [])]

    @property
    def strategy(self) -> dict:
        return self.raw.get("strategy", {})

    @property
    def risk(self) -> dict:
        return self.raw.get("risk", {})

    @property
    def costs(self) -> dict:
        return self.raw.get("costs", {})

    @property
    def backtest(self) -> dict:
        return self.raw.get("backtest", {})

    @property
    def ibkr(self) -> dict:
        d = dict(self.raw.get("ibkr", {}))
        d["host"] = os.getenv("IBKR_HOST", d.get("host", "127.0.0.1"))
        d["port"] = int(os.getenv("IBKR_PORT", d.get("port", 4002 if self.is_paper else 4001)))
        d["client_id"] = int(os.getenv("IBKR_CLIENT_ID", d.get("client_id", 17)))
        return d


def load(path: str | Path | None = None) -> Settings:
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    path = Path(path) if path else ROOT / "config" / "settings.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    s = Settings(raw)
    if s.mode not in ("paper", "live"):
        raise ValueError(f"mode must be 'paper' or 'live', got {s.mode!r}")
    if s.mode == "live" and raw.get("live_confirm") is not True:
        raise ValueError("mode is live but live_confirm is not true. Refusing to start.")
    if raw.get("broker", "ibkr") != "ibkr":
        raise ValueError("only broker: ibkr is supported")
    return s


def as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))
