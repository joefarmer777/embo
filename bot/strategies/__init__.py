from .orb import OpeningRangeBreakout


def build(cfg: dict):
    name = cfg.get("name", "orb")
    if name == "orb":
        return OpeningRangeBreakout(
            range_minutes=int(cfg.get("range_minutes", 15)),
            target_r=float(cfg.get("target_r", 2.0)),
            stop=cfg.get("stop", "range"),
            allow_short=bool(cfg.get("allow_short", True)),
        )
    raise ValueError(f"unknown strategy {name!r}")
