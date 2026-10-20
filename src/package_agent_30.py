"""Snapshot only derived, auditable 30-event Agent artifacts into the project."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tmp" / "agent_poc"
TARGET = ROOT / "artifacts" / "agent_30"


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    names = [
        "numeric_inputs.json", "numeric_extension_inputs.json",
        "decision_inputs.json", "decision_extension_inputs.json",
        "numeric_scores.json", "numeric_extension_scores.json",
        "chart_scores.json", "chart_extension_scores.json",
        "final_scores.json", "final_extension_scores.json",
        "input_manifest.json", "extension_input_manifest.json",
        "event_mapping.json", "extension_mapping.json",
    ] + [f"EV{i:03d}.png" for i in range(1, 31)]
    manifest = {}
    for name in names:
        content = (SOURCE / name).read_bytes()
        (TARGET / name).write_bytes(content)
        manifest[name] = hashlib.sha256(content).hexdigest()
    for source_name, target_name in (
        ("agent_30_scored.csv", "scored_signals.csv"),
        ("agent_30_events.csv", "unfiltered_signals.csv"),
    ):
        content = (ROOT / "data" / source_name).read_bytes()
        (TARGET / target_name).write_bytes(content)
        manifest[target_name] = hashlib.sha256(content).hexdigest()
    (TARGET / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Packaged {len(manifest)} derived artifacts in {TARGET}")


if __name__ == "__main__":
    main()
