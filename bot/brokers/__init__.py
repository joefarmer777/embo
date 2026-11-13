def connect(settings):
    from .ibkr import IBKR
    c = settings.ibkr
    return IBKR(c["host"], c["port"], c["client_id"], paper=settings.is_paper)
