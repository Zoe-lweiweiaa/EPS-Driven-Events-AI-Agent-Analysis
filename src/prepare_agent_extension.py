"""Freeze anonymous inputs for 18 additional, distinct A-share events."""

import json

import pandas as pd

from prepare_agent_poc import ROOT, OUT, compact, make_chart


def main():
    market = pd.read_csv(ROOT / "data" / "agent_extension_market.csv")
    events = pd.read_csv(ROOT / "data" / "events_2025_2026_ashares.csv")
    prior = pd.read_csv(ROOT / "data" / "events_2025_2026.csv")
    prior_indices = [round(i * (len(prior) - 1) / 11) for i in range(12)]
    used = {(prior.iloc[i].trade_code, prior.iloc[i].end_date) for i in prior_indices}
    indices = []
    for i in range(18):
        index = round((i + 0.5) * (len(events) - 1) / 18)
        while (events.iloc[index].trade_code, events.iloc[index].end_date) in used:
            index += 1
        used.add((events.iloc[index].trade_code, events.iloc[index].end_date))
        indices.append(index)
    numeric = []
    decision = []
    mapping = []
    for n, source_index in enumerate(indices, 13):
        event_id = f"EV{n:03d}"
        frame = market[market.event_id == event_id].sort_values("bar").reset_index(drop=True)
        if len(frame) != 60:
            raise ValueError(f"Expected 60 bars for {event_id}, found {len(frame)}")
        row = events.iloc[source_index]
        close = frame.close
        last20 = close.tail(20)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        numeric.append({
            "event_id": event_id,
            "returns": {f"return_{days}d": compact(close.iloc[-1] / close.iloc[-days-1] - 1)
                        for days in (5, 20, 40)},
            "close_over_ma5": compact(close.iloc[-1] / close.tail(5).mean() - 1),
            "close_over_ma20": compact(close.iloc[-1] / last20.mean() - 1),
            "volume_over_20d_median": compact(frame.volume.iloc[-1] / frame.volume.tail(20).median()),
            "20d_max_drawdown": compact((last20 / last20.cummax() - 1).min()),
            "20d_daily_volatility": compact(close.pct_change().tail(20).std()),
            "macd_dif_pct": compact(dif.iloc[-1] / close.iloc[-1]),
            "macd_hist_pct": compact(2 * (dif.iloc[-1] - dea.iloc[-1]) / close.iloc[-1]),
            "last_10_bars": [
                {"bar": int(r.bar), "open": compact(r.open / close.iloc[0] * 100),
                 "high": compact(r.high / close.iloc[0] * 100),
                 "low": compact(r.low / close.iloc[0] * 100),
                 "close": compact(r.close / close.iloc[0] * 100),
                 "volume_ratio": compact(r.volume / frame.volume.tail(20).median())}
                for r in frame.tail(10).itertuples()
            ],
        })
        decision.append({
            "event_id": event_id, "forecast_score": compact(row.forecast_score),
            "fy0_score": None if pd.isna(row.fy0_score) else compact(row.fy0_score),
            "fy1_score": None if pd.isna(row.fy1_score) else compact(row.fy1_score),
            "fy0_orgnum": None if pd.isna(row.fy0_orgnum) else int(row.fy0_orgnum),
            "fy1_orgnum": None if pd.isna(row.fy1_orgnum) else int(row.fy1_orgnum),
            "delta_add_total": int(row.delta_add_total),
        })
        mapping.append({"event_id": event_id, "trade_code": row.trade_code,
                        "end_date": int(row.end_date), "trade_date": row.trade_date})
        make_chart(frame, OUT / f"{event_id}.png")
    for name, data in (("numeric_extension_inputs.json", numeric),
                       ("decision_extension_inputs.json", decision),
                       ("extension_mapping.json", mapping)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(numeric)} additional anonymous events")


if __name__ == "__main__":
    main()
