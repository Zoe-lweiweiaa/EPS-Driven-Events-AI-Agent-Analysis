"""Generate auditable EPS crossing events for the 2026-06-01..10-16 backtest.

The CSV contains signal candidates, not a five-stock portfolio. It uses the
next trading day's open after each EPS snapshot and applies no signal cooldown.
Run normally only after data/epsstat_live_raw_2026.tsv covers 2026-10-15.
``--allow-partial`` writes a separately named diagnostic CSV from the saved
2026-09-15 snapshot; it never creates the full-coverage marker.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HISTORICAL = DATA / "eps60_raw_2024_2026.tsv"
RECENT = DATA / "epsstat_live_raw_2026.tsv"
CALENDAR = DATA / "trade_days_2024_2026_oct.csv"
OUTPUT = DATA / "eps_event_recent.csv"
COVERAGE = DATA / "eps_event_recent.coverage.txt"
START = "2026-06-01"
END = "2026-10-16"
REQUIRED_SNAPSHOT = 20261015
NAMES = [
    "id", "trade_code", "end_date", "est_report_y", "eps_add", "eps_reduce",
    "eps_maintain", "eps_first", "eps_num", "eps_orgnum", "eps_researchnum",
    "update_time",
]
DTYPES = {
    "id": "int64", "trade_code": "string", "end_date": "int32",
    "est_report_y": "int16", "eps_add": "int32", "eps_reduce": "int32",
    "eps_orgnum": "int32",
}


def read_snapshots(path):
    return pd.read_csv(
        path, sep="\t", header=None, names=NAMES, usecols=list(DTYPES),
        dtype=DTYPES, encoding="utf-8-sig", na_values=["NULL"],
    )


def load_source(allow_partial):
    if not HISTORICAL.exists():
        raise FileNotFoundError(f"Saved EPS snapshots are missing: {HISTORICAL}")
    historical = read_snapshots(HISTORICAL)
    if historical.empty or int(historical.end_date.max()) < 20260915:
        raise ValueError("Saved EPS snapshots must cover 2026-09-15")
    frames = [historical]
    if RECENT.exists() and RECENT.stat().st_size:
        recent = read_snapshots(RECENT)
        if recent.empty or int(recent.end_date.min()) != 20260916:
            raise ValueError("Recent export must begin on 2026-09-16")
        frames.append(recent)
    latest = max(int(frame.end_date.max()) for frame in frames)
    complete = latest >= REQUIRED_SNAPSHOT
    if complete:
        required_dates = set(int(day.strftime("%Y%m%d")) for day in
                             pd.date_range("2026-09-16", "2026-10-15"))
        observed_dates = set(int(day) for day in frames[-1].end_date.unique())
        missing_dates = sorted(required_dates - observed_dates)
        if missing_dates:
            raise ValueError(
                "Recent daily snapshots have missing dates: " +
                ", ".join(map(str, missing_dates))
            )
    if not complete and not allow_partial:
        raise FileNotFoundError(
            f"EPS snapshots end at {latest}; export 2026-09-16 through "
            f"2026-10-15 to {RECENT}, or run --allow-partial for a diagnostic"
        )
    raw = pd.concat(frames, ignore_index=True)
    raw = raw[raw.trade_code.str.fullmatch(
        r"(?:6[0-9]{5}\.SH|[03][0-9]{5}\.SZ)", na=False
    )].copy()
    if raw.empty or raw.isna().any().any():
        raise ValueError("Missing required values in the EPS snapshot export")
    key = ["trade_code", "end_date", "est_report_y"]
    if raw.duplicated(key).any():
        raise ValueError("Duplicate stock/date/forecast-year snapshots")
    raw["year_offset"] = raw.est_report_y - raw.end_date // 10000
    if not raw.year_offset.isin([0, 1]).all():
        raise ValueError("Snapshots must contain only FY0 and FY1")
    return raw, latest, complete


def build_events(raw):
    raw.sort_values(["trade_code", "est_report_y", "end_date"], inplace=True)
    prior_add = raw.groupby(["trade_code", "est_report_y"], sort=False).eps_add.shift()
    raw["delta_add"] = (raw.eps_add - prior_add).fillna(0).astype("int32")
    raw["revision_score"] = (
        (raw.eps_add - raw.eps_reduce) /
        np.maximum(raw.eps_add + raw.eps_reduce, 3)
    )
    keys = ["trade_code", "end_date"]
    paired = raw.set_index(keys + ["year_offset"])[
        ["revision_score", "eps_add", "eps_reduce", "eps_orgnum"]
    ].unstack("year_offset")
    paired.columns = [f"{name}_fy{year}" for name, year in paired.columns]
    by_day = raw.groupby(keys, sort=False)
    paired["delta_add_total"] = by_day.delta_add.sum()
    paired["source_max_id"] = by_day.id.max()
    paired = paired.reset_index().sort_values(keys)
    fy0, fy1 = paired.revision_score_fy0, paired.revision_score_fy1
    paired["forecast_score"] = np.where(
        fy0.isna(), fy1, np.where(fy1.isna(), fy0, 0.6 * fy0 + 0.4 * fy1)
    )
    paired["previous_score"] = paired.groupby("trade_code").forecast_score.shift()
    candidates = paired[
        (paired.forecast_score >= 0.5) &
        (paired.previous_score.isna() | (paired.previous_score < 0.5)) &
        ((paired.eps_orgnum_fy0.fillna(0) >= 3) |
         (paired.eps_orgnum_fy1.fillna(0) >= 3)) &
        (paired.delta_add_total >= 1)
    ].copy()
    calendar = pd.read_csv(CALENDAR, parse_dates=["trade_date"])
    dates = calendar.trade_date.to_numpy()
    if not calendar.trade_date.is_monotonic_increasing or calendar.trade_date.duplicated().any():
        raise ValueError("Trade calendar must be sorted and unique")
    snapshot_dates = pd.to_datetime(candidates.end_date.astype(str), format="%Y%m%d")
    indices = np.searchsorted(dates, snapshot_dates.to_numpy(), side="right")
    if (indices >= len(calendar)).any():
        raise ValueError("Trade calendar must extend beyond every candidate snapshot")
    candidates["trade_date"] = calendar.trade_date.iloc[indices].to_numpy()
    candidates["trade_index"] = indices
    candidates = candidates[candidates.trade_date.between(START, END)].copy()
    candidates.sort_values(
        ["trade_code", "trade_date", "forecast_score", "end_date"],
        ascending=[True, True, False, False], inplace=True,
    )
    candidates.drop_duplicates(["trade_code", "trade_date"], keep="first", inplace=True)
    candidates.sort_values(
        ["trade_date", "forecast_score", "trade_code"],
        ascending=[True, False, True], inplace=True,
    )
    candidates.rename(columns={
        "revision_score_fy0": "fy0_score",
        "revision_score_fy1": "fy1_score",
        "eps_orgnum_fy0": "fy0_orgnum",
        "eps_orgnum_fy1": "fy1_orgnum",
    }, inplace=True)
    columns = [
        "trade_code", "end_date", "trade_date", "trade_index",
        "forecast_score", "previous_score", "fy0_score", "fy1_score",
        "eps_add_fy0", "eps_reduce_fy0", "eps_add_fy1", "eps_reduce_fy1",
        "fy0_orgnum", "fy1_orgnum", "delta_add_total", "source_max_id",
    ]
    return candidates[columns]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    raw, latest, complete = load_source(args.allow_partial)
    print(f"Loaded {len(raw):,} A-share EPS rows through {latest}")
    events = build_events(raw)
    if complete:
        target = OUTPUT
    else:
        target = DATA / f"eps_event_recent_partial_to_{latest}.csv"
    events.to_csv(target, index=False)
    if complete:
        COVERAGE.write_text(str(latest), encoding="utf-8")
    print({
        "output": str(target), "complete": complete,
        "events": len(events), "stocks": events.trade_code.nunique(),
        "first_trade_date": str(events.trade_date.min()) if len(events) else None,
        "last_trade_date": str(events.trade_date.max()) if len(events) else None,
    })


if __name__ == "__main__":
    main()
