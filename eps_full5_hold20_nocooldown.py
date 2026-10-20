"""EPS baseline: up to five stocks, cash-funded equalization, no signal cooldown.

Backtest window: 2026-06-01 through 2026-10-16, DAILY, STOCK.
Signals must be generated from snapshots through 2026-10-15 before use.
No stock is sold before it has completed 20 trading sessions. New signals
wait for available cash and a free slot. Any held-stock top-up keeps the
original entry clock; an empty eligible stock set necessarily leaves cash.
"""

from mindgo_api import *
import csv
import io


SIGNAL_FILE = "mcp/AI主观量化/eps_event_recent.csv"
COVERAGE_FILE = "mcp/AI主观量化/eps_event_recent.coverage.txt"
CALENDAR_FILE = "mcp/AI主观量化/trade_days_2024_2026_oct.csv"
BACKTEST_START = "2026-06-01"
BACKTEST_END = "2026-10-16"
MAX_POSITIONS = 5
HOLDING_DAYS = 20
TARGET_GROSS = 0.998  # Leave room for fees and whole-lot rounding.


def init(context):
    set_benchmark("000985.CSI")
    coverage = int(read_file(COVERAGE_FILE).decode("utf-8-sig").strip())
    if coverage < 20261015:
        raise ValueError("EPS snapshots must cover at least 2026-10-15")
    g.trade_index = {}
    for index, row in enumerate(csv.DictReader(io.StringIO(
        read_file(CALENDAR_FILE).decode("utf-8-sig")
    ))):
        g.trade_index[row["trade_date"]] = index
    if BACKTEST_START not in g.trade_index or BACKTEST_END not in g.trade_index:
        raise ValueError("Trade calendar does not cover the full backtest")
    g.events = {}
    for row in csv.DictReader(io.StringIO(read_file(SIGNAL_FILE).decode("utf-8-sig"))):
        trade_date = row["trade_date"]
        if trade_date not in g.trade_index:
            raise ValueError("Signal trade date is absent from the calendar: " + trade_date)
        if int(row["end_date"]) >= int(trade_date.replace("-", "")):
            raise ValueError("Signal uses a same-day or future EPS snapshot")
        g.events.setdefault(trade_date, []).append(row)
    g.entry_index = {}  # Set on the first BUY fill; top-ups do not reset it.
    g.pending = {}  # Unfilled signals wait for a cash-funded entry.
    g.last_subscribed = set()
    subscribe("000985.CSI")
    print("EPS full-five loaded", sum(len(rows) for rows in g.events.values()),
          "events; source coverage", coverage)


def before_trading(context):
    today = context.portfolio.datetime.date().isoformat()
    needed = set(row["trade_code"] for row in g.events.get(today, []))
    needed.update(g.pending)
    needed.update(context.portfolio.positions.keys())
    added = needed - g.last_subscribed
    if added:
        subscribe(sorted(added))
    removed = g.last_subscribed - needed
    if removed:
        unsubscribe(sorted(removed))
    g.last_subscribed = needed


def on_trade(context, trade):
    if trade.side == SIDE.BUY and trade.order_book_id not in g.entry_index:
        today = context.portfolio.datetime.date().isoformat()
        g.entry_index[trade.order_book_id] = g.trade_index[today]
    if trade.side == SIDE.BUY:
        g.pending.pop(trade.order_book_id, None)


def open_auction(context, bar_dict):
    today = context.portfolio.datetime.date().isoformat()
    if today < BACKTEST_START or today > BACKTEST_END:
        return
    day_index = g.trade_index.get(today)
    if day_index is None:
        return
    held_before = set(context.portfolio.positions.keys())
    for symbol in held_before:
        g.pending.pop(symbol, None)
    for row in g.events.get(today, []):
        symbol = row["trade_code"]
        if symbol not in held_before:
            # A later crossing replaces an earlier queued crossing for the
            # same stock. Signals received while holding are not replayed.
            g.pending[symbol] = row
    for symbol in list(g.entry_index):
        if symbol not in held_before:
            del g.entry_index[symbol]
    for symbol in held_before:
        if symbol not in g.entry_index:
            # Conservative if a position is unexpectedly missing its fill record.
            g.entry_index[symbol] = day_index
            print("MISSING_ENTRY_DATE", today, symbol)

    due = set()
    for symbol in sorted(held_before):
        if day_index - g.entry_index[symbol] >= HOLDING_DAYS:
            due.add(symbol)
            order_id = order_target_percent(symbol, 0)
            print("EXIT_20D", today, symbol, order_id)

    held = set(context.portfolio.positions.keys())
    for symbol in held_before - held:
        g.entry_index.pop(symbol, None)
    slots = max(0, MAX_POSITIONS - len(held))
    new_symbols = []
    ranked = sorted(
        g.pending.values(),
        key=lambda row: (-float(row["forecast_score"]), row["trade_code"]),
    )
    for row in ranked:
        if len(new_symbols) >= slots:
            break
        symbol = row["trade_code"]
        if symbol in held or symbol in due or symbol in new_symbols:
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
        new_symbols.append(symbol)

    if not held and not new_symbols:
        print("CASH_NO_ELIGIBLE_EPS_SIGNAL", today, "pending", len(g.pending))
        return

    # Never reduce an unexpired holding to finance a new signal. Split only
    # the cash now available among the new EPS names.
    submitted = 0
    if new_symbols and context.portfolio.available_cash > 0:
        budget_each = (context.portfolio.available_cash * TARGET_GROSS /
                       len(new_symbols))
        for symbol in new_symbols:
            wait_days = day_index - g.trade_index[g.pending[symbol]["trade_date"]]
            order_id = order_value(symbol, budget_each)
            print("BUY_EPS", today, symbol, budget_each, "wait_days",
                  wait_days, order_id)
            submitted += order_id is not None
    elif new_symbols:
        print("WAIT_FOR_CASH", today, len(g.pending))
    if submitted:
        # The auction orders may fill after this callback. Spend any residual
        # cash on a later session, after the fills and cash are observable.
        return

    actual = set(context.portfolio.positions.keys()) - due
    if actual:
        # On membership changes, spend residual cash on the smallest held
        # positions first. This gets as close to equal weight as possible
        # without selling an unexpired lot.
        total = context.portfolio.portfolio_value
        invested = sum(context.portfolio.positions[s].market_value for s in actual)
        budget = min(context.portfolio.available_cash,
                     max(0.0, TARGET_GROSS * total - invested))
        if budget > 0:
            values = {s: context.portfolio.positions[s].market_value
                      for s in actual}
            low = min(values.values())
            high = max(values.values()) + budget
            for _ in range(30):
                mid = (low + high) / 2.0
                required = sum(max(0.0, mid - value)
                               for value in values.values())
                if required > budget:
                    high = mid
                else:
                    low = mid
            for symbol in sorted(actual, key=lambda s: (values[s], s)):
                target_value = max(values[symbol], low)
                top_up = target_value - values[symbol]
                if top_up > 0.001 * total:
                    order_value(symbol, top_up)


def handle_bar(context, bar_dict):
    pass
