"""Prepare minimal derived CSVs for the SuperMind project directory."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "remote_sanitized"
BASE_COLUMNS = ["trade_code", "end_date", "trade_date", "forecast_score"]
SCORE_COLUMNS = BASE_COLUMNS + ["event_id", "score_5d", "score_20d", "confidence"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inputs = {
        "events_sample.csv": (ROOT / "tmp" / "events_sample.csv", BASE_COLUMNS),
        "events_2025_2026.csv": (ROOT / "data" / "events_2025_2026.csv", BASE_COLUMNS),
        "events_2025_2026_ashares.csv": (
            ROOT / "data" / "events_2025_2026_ashares.csv", BASE_COLUMNS),
        "agent_poc_scored.csv": (ROOT / "data" / "agent_poc_scored.csv", SCORE_COLUMNS),
        "agent_30_scored.csv": (ROOT / "data" / "agent_30_scored.csv", SCORE_COLUMNS),
        "agent_30_events.csv": (ROOT / "data" / "agent_30_events.csv", BASE_COLUMNS),
    }
    for name, (source, columns) in inputs.items():
        frame = pd.read_csv(source)
        if frame[columns].isna().any().any():
            raise ValueError(f"Missing remote field in {name}")
        frame[columns].to_csv(OUT / name, index=False)
    print(f"Prepared {len(inputs)} minimal remote files in {OUT}")


if __name__ == "__main__":
    main()
