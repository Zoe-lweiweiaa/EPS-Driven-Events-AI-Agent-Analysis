"""Fail-closed validation and scored-signal export for the 12-event PoC."""

import json
from pathlib import Path

import pandas as pd

from assemble_agent_poc import indexed


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "tmp" / "agent_poc"


def main():
    events = pd.read_csv(ROOT / "data" / "events_2025_2026_ashares.csv")
    mapping = json.loads((DIR / "event_mapping.json").read_text(encoding="utf-8"))
    expected = [row["event_id"] for row in mapping]
    scores = indexed(
        json.loads((DIR / "final_scores.json").read_text(encoding="utf-8")),
        expected, "final",
    )
    if len(mapping) != 12:
        raise ValueError("PoC mapping count changed")
    rows = []
    for entry in mapping:
        matching = events.loc[
            (events.trade_code == entry["trade_code"]) &
            (events.trade_date == entry["trade_date"]) &
            (events.end_date == entry["end_date"])
        ]
        if len(matching) != 1:
            raise ValueError(f"Signal source changed for {entry['event_id']}")
        source = matching.iloc[0]
        score = scores[entry["event_id"]]
        row = source.to_dict()
        row.update(event_id=entry["event_id"], score_5d=score["score_5d"],
                   score_20d=score["score_20d"], confidence=score["confidence"])
        rows.append(row)
    output = pd.DataFrame(rows)
    output.to_csv(ROOT / "data" / "agent_poc_scored.csv", index=False)
    passed = output[(output.score_20d >= 0.4) & (output.score_5d > -0.2)]
    print(f"12 complete scored events; {len(passed)} pass frozen thresholds")


if __name__ == "__main__":
    main()
