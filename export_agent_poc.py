"""Export a small as-of OHLCV sample for blinded Codex agent evaluation."""

from mindgo_api import *
import csv
import io


def export():
    events = list(csv.DictReader(io.StringIO(
        read_file("mcp/AI主观量化/events_2025_2026.csv").decode("utf-8")
    )))
    indices = [round(i * (len(events) - 1) / 11) for i in range(12)]
    rows = []
    selected = []
    for ordinal, index in enumerate(indices, 1):
        event = events[index]
        symbol = event["trade_code"]
        cutoff = event["end_date"]
        frame = get_price(
            symbol, end_date=cutoff, bar_count=60, fre_step="1d",
            fields=["open", "high", "low", "close", "volume", "turnover"],
            fq="pre", skip_paused=True,
        )
        if frame is None or len(frame) < 40:
            continue
        event_id = "EV%03d" % ordinal
        selected.append((event_id, symbol, cutoff, event["trade_date"]))
        for bar_number, (_, bar) in enumerate(frame.iterrows(), 1):
            rows.append((
                event_id, bar_number, float(bar["open"]), float(bar["high"]),
                float(bar["low"]), float(bar["close"]), float(bar["volume"]),
                float(bar["turnover"]),
            ))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["event_id", "bar", "open", "high", "low", "close", "volume", "turnover"])
    writer.writerows(rows)
    write_file("mcp/AI主观量化/agent_poc_market.csv", output.getvalue())
    print("selected", selected, "bars", len(rows))


export()
