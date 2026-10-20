"""Validate extension roles and create 18 blinded decision inputs."""

import hashlib
import json

from assemble_agent_poc import DIR, indexed, load


def main():
    eps = load("decision_extension_inputs.json")
    expected = [row["event_id"] for row in eps]
    numeric = indexed(load("numeric_extension_scores.json"), expected, "numeric extension")
    chart = indexed(load("chart_extension_scores.json"), expected, "chart extension")
    numeric_inputs = {row["event_id"]: row for row in load("numeric_extension_inputs.json")}
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
    (DIR / "final_extension_agent_inputs.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DIR / "extension_input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Validated and assembled {len(frozen)} blinded extension events")


if __name__ == "__main__":
    main()
