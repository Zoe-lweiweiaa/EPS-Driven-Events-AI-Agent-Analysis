"""Frozen EPS-event baseline; only derived signals are staged remotely."""

from mindgo_api import *
import csv
import io


SIGNAL_FILE = "mcp/AI主观量化/events_2025_2026_ashares.csv"
CALENDAR_FILE = "mcp/AI主观量化/trade_days_2024_2026.csv"
MAX_POSITIONS = 20
POSITION_WEIGHT = 0.05
HOLDING_DAYS = 20


def init(context):
    set_benchmark("000985.CSI")
    g.events = {}
    for row in csv.DictReader(io.StringIO(read_file(SIGNAL_FILE).decode("utf-8"))):
        g.events.setdefault(row["trade_date"], []).append(row)
    g.trade_index = {}
    for index, row in enumerate(
        csv.DictReader(io.StringIO(read_file(CALENDAR_FILE).decode("utf-8")))
    ):
        g.trade_index[row["trade_date"]] = index
    g.entry_index = {}
    g.last_subscribed = set()
    subscribe("000985.CSI")
    print("EPS baseline loaded", sum(len(rows) for rows in g.events.values()), "events")


def before_trading(context):
    today = context.portfolio.datetime.date().isoformat()
    symbols = set(row["trade_code"] for row in g.events.get(today, []))
    symbols.update(context.portfolio.positions.keys())
    newly_needed = symbols - g.last_subscribed
    if newly_needed:
        subscribe(sorted(newly_needed))
    no_longer_needed = g.last_subscribed - symbols
    if no_longer_needed:
        unsubscribe(sorted(no_longer_needed))
    g.last_subscribed = symbols


def open_auction(context, bar_dict):
    today = context.portfolio.datetime.date().isoformat()
    day_index = g.trade_index.get(today)
    if day_index is None:
        return
    held = set(context.portfolio.positions.keys())
    for symbol in list(g.entry_index):
        if symbol not in held:
            del g.entry_index[symbol]
    for symbol in sorted(held):
        entry_index = g.entry_index.get(symbol)
        if entry_index is not None and day_index - entry_index >= HOLDING_DAYS:
            order_target_percent(symbol, 0)
    today_events = sorted(
        g.events.get(today, []),
        key=lambda row: (-float(row["forecast_score"]), row["trade_code"]),
    )
    slots = max(0, MAX_POSITIONS - len(held))
    for row in today_events:
        if slots == 0:
            break
        symbol = row["trade_code"]
        if symbol in held:
            continue
        try:
            bar = bar_dict[symbol]
            info = get_security_info(symbol)
            age = (context.portfolio.datetime.date() - info.start_date.date()).days
        except (KeyError, AttributeError, ValueError):
            print("SKIP_MISSING_MARKET", today, symbol)
            continue
        if age < 120 or bar.is_st or bar.is_paused:
            continue
        if bar.open <= 0 or bar.high_limit <= 0 or bar.open >= bar.high_limit:
            continue
        order_id = order_target_percent(symbol, POSITION_WEIGHT)
        if order_id is not None:
            g.entry_index[symbol] = day_index
            slots -= 1
            print("BUY", today, symbol, order_id)


def handle_bar(context, bar_dict):
    pass
