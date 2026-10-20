"""Validate independent role outputs and create blinded decision inputs."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "tmp" / "agent_poc"


def load(name):
    return json.loads((DIR / name).read_text(encoding="utf-8"))


def indexed(rows, expected_ids, label):
    result = {row["event_id"]: row for row in rows}
    if len(result) != len(rows) or set(result) != set(expected_ids):
        raise ValueError(f"{label}: duplicate or missing event IDs")
    for row in rows:
        for horizon in ("score_5d", "score_20d"):
            value = row[horizon]
            if not isinstance(value, (int, float)) or not -1 <= value <= 1:
                raise ValueError(f"{label}: invalid {horizon} for {row['event_id']}")
        if not 0 <= row["confidence"] <= 1:
            raise ValueError(f"{label}: invalid confidence for {row['event_id']}")
        if not row["evidence"] and not row["abstain_reason"]:
            raise ValueError(f"{label}: no evidence or abstention for {row['event_id']}")
    return result


def main():
    eps = load("decision_inputs.json")
    expected = [row["event_id"] for row in eps]
    numeric = indexed(load("numeric_scores.json"), expected, "numeric")
    chart = indexed(load("chart_scores.json"), expected, "chart")
    numeric_inputs = {row["event_id"]: row for row in load("numeric_inputs.json")}
    frozen = []
    manifest = []
    for event in eps:
        event_id = event["event_id"]
        frozen.append({"event": event, "numeric_agent": numeric[event_id],
                       "chart_agent": chart[event_id]})
        numeric_bytes = json.dumps(numeric_inputs[event_id], sort_keys=True).encode("utf-8")
        chart_bytes = (DIR / f"{event_id}.png").read_bytes()
        manifest.append({
            "event_id": event_id,
            "numeric_input_sha256": hashlib.sha256(numeric_bytes).hexdigest(),
            "chart_sha256": hashlib.sha256(chart_bytes).hexdigest(),
        })
    (DIR / "final_agent_inputs.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DIR / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Validated and assembled {len(frozen)} blinded events")


if __name__ == "__main__":
    main()
