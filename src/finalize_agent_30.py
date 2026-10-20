"""Freeze 30 non-overlapping A-share events for paired remote backtests."""

import json

import pandas as pd

from assemble_agent_poc import DIR, ROOT, indexed


def read_json(name):
    return json.loads((DIR / name).read_text(encoding="utf-8"))


def main():
    source = pd.read_csv(ROOT / "data" / "events_2025_2026_ashares.csv")
    mapping = read_json("event_mapping.json") + read_json("extension_mapping.json")
    expected = [row["event_id"] for row in mapping]
    if len(expected) != 30 or len(set(expected)) != 30:
        raise ValueError("Expected 30 unique event IDs")
    scores = indexed(
        read_json("final_scores.json") + read_json("final_extension_scores.json"),
        expected, "final 30",
    )
    source_keys = {
        (row.trade_code, int(row.end_date), row.trade_date): row
        for row in source.itertuples(index=False)
    }
    rows = []
    used_keys = set()
    for entry in mapping:
        key = (entry["trade_code"], entry["end_date"], entry["trade_date"])
        if key in used_keys or key not in source_keys:
            raise ValueError(f"Duplicate or missing source event: {entry['event_id']}")
        used_keys.add(key)
        row = source.loc[
            (source.trade_code == key[0]) &
            (source.end_date == key[1]) &
            (source.trade_date == key[2])
        ].iloc[0].to_dict()
        score = scores[entry["event_id"]]
        row.update(event_id=entry["event_id"], score_5d=score["score_5d"],
                   score_20d=score["score_20d"], confidence=score["confidence"])
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values(["trade_date", "trade_code"])
    frame.to_csv(ROOT / "data" / "agent_30_scored.csv", index=False)
    frame[source.columns].to_csv(ROOT / "data" / "agent_30_events.csv", index=False)
    selected = frame[(frame.score_20d >= 0.4) & (frame.score_5d > -0.2)]
    print(f"Frozen 30 distinct A-share events; {len(selected)} pass Agent gate")


if __name__ == "__main__":
    main()
