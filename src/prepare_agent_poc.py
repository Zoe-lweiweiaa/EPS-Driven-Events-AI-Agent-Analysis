"""Freeze anonymous price inputs and charts for a small three-agent audit."""

import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "agent_poc"


def compact(value):
    return round(float(value), 4)


def make_chart(frame, path):
    width, height = 1060, 700
    im = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(im)
    left, right = 65, width - 30
    panels = [(38, 400), (425, 555), (580, 670)]
    bars = len(frame)
    x_step = (right - left) / max(bars - 1, 1)
    norm = 100 / frame.close.iloc[0]
    prices = frame[["open", "high", "low", "close"]] * norm
    lo = prices.low.min() * 0.98
    hi = prices.high.max() * 1.02
    volume = frame.volume / frame.volume.tail(20).median()
    ema12 = frame.close.ewm(span=12, adjust=False).mean()
    ema26 = frame.close.ewm(span=26, adjust=False).mean()
    dif = (ema12 - ema26) / frame.close.iloc[-1] * 100
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = 2 * (dif - dea)
    macd_max = max(abs(hist).max(), abs(dif).max(), abs(dea).max(), 0.01) * 1.15
    draw.text((left, 10), "ANONYMOUS AS-OF OHLCV: bars 1-60, price indexed to 100", fill="black")
    for top, bottom in panels:
        draw.rectangle((left, top, right, bottom), outline="#bbbbbb")
    for i in range(bars):
        x = left + i * x_step
        up = prices.close.iloc[i] >= prices.open.iloc[i]
        color = "#c0392b" if up else "#168a55"
        y = lambda p: panels[0][1] - (p - lo) / (hi - lo) * (panels[0][1] - panels[0][0])
        draw.line((x, y(prices.high.iloc[i]), x, y(prices.low.iloc[i])), fill=color, width=1)
        draw.rectangle((x - 3, min(y(prices.open.iloc[i]), y(prices.close.iloc[i])),
                        x + 3, max(y(prices.open.iloc[i]), y(prices.close.iloc[i])) + 1), fill=color)
        vol_y = panels[1][1] - min(volume.iloc[i] / 5, 1) * (panels[1][1] - panels[1][0])
        draw.rectangle((x - 3, vol_y, x + 3, panels[1][1]), fill=color)
        zero_y = (panels[2][0] + panels[2][1]) / 2
        h_y = zero_y - hist.iloc[i] / macd_max * 42
        draw.line((x, zero_y, x, h_y), fill=color, width=3)
    for series, color in ((dif, "#1261a0"), (dea, "#f39c12")):
        points = [(left + i * x_step, (panels[2][0] + panels[2][1]) / 2 -
                   series.iloc[i] / macd_max * 42) for i in range(bars)]
        draw.line(points, fill=color, width=2)
    draw.text((5, 40), "PRICE", fill="black")
    draw.text((5, 425), "VOL", fill="black")
    draw.text((5, 580), "MACD", fill="black")
    for n in (1, 20, 40, 60):
        x = left + (n - 1) * x_step
        draw.text((x - 7, 402), str(n), fill="black")
    im.save(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    market = pd.read_csv(ROOT / "data" / "agent_poc_market.csv")
    events = pd.read_csv(ROOT / "data" / "events_2025_2026.csv")
    indices = [round(i * (len(events) - 1) / 11) for i in range(12)]
    numeric = []
    decision = []
    mapping = []
    for n, source_index in enumerate(indices, 1):
        event_id = f"EV{n:03d}"
        frame = market[market.event_id == event_id].sort_values("bar").reset_index(drop=True)
        if len(frame) != 60:
            raise ValueError(f"Expected 60 bars for {event_id}, found {len(frame)}")
        row = events.iloc[source_index]
        close = frame.close
        returns = {f"return_{days}d": compact(close.iloc[-1] / close.iloc[-days-1] - 1)
                   for days in (5, 20, 40)}
        last20 = close.tail(20)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        item = {
            "event_id": event_id,
            "returns": returns,
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
        }
        numeric.append(item)
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
    (OUT / "numeric_inputs.json").write_text(json.dumps(numeric, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "decision_inputs.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "event_mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(numeric)} anonymous events in {OUT}")


if __name__ == "__main__":
    main()
