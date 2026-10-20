"""Build the June-October EPS event file without the 10-day signal cooldown.

Requires the local read-only MySQL export through 2026-10-15. Run only after
data/epsstat_live_raw_2026.tsv has been exported from the user's MySQL host.
"""

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HISTORICAL = DATA / "eps60_raw_2024_2026.tsv"
RECENT = DATA / "epsstat_live_raw_2026.tsv"
CALENDAR = DATA / "trade_days_2024_2026_oct.csv"
OUTPUT = DATA / "events_2026_06_10_ashares_nocooldown.csv"
COVERAGE = DATA / "events_2026_06_10_ashares_nocooldown.coverage.txt"
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


def read_snapshot(path):
    return pd.read_csv(
        path, sep="\t", header=None, names=NAMES, usecols=list(DTYPES),
        dtype=DTYPES, encoding="utf-8-sig", na_values=["NULL"],
    )


def main():
    if not RECENT.exists() or RECENT.stat().st_size == 0:
        raise FileNotFoundError(f"Current MySQL export is required: {RECENT}")
    old = read_snapshot(HISTORICAL)
    recent = read_snapshot(RECENT)
    latest = int(recent.end_date.max())
    if latest < 20261015:
        raise ValueError(f"MySQL export ends at {latest}; need 20261015")
    if int(recent.end_date.min()) > 20260916 or recent.end_date.nunique() < 14:
        raise ValueError("Recent MySQL export does not cover the September-October window")
    raw = pd.concat([old, recent], ignore_index=True)
    raw = raw[raw.trade_code.str.match(
        r"^(?:6[0-9]{5}\.SH|[03][0-9]{5}\.SZ)$"
    )].copy()
    if raw.isna().any().any():
        raise ValueError("EPS snapshot export contains NULL required fields")
    if raw.duplicated(["trade_code", "end_date", "est_report_y"]).any():
        raise ValueError("Duplicate stock/date/forecast-year rows")
    raw.sort_values(["trade_code", "est_report_y", "end_date"], inplace=True)
    previous_add = raw.groupby(
        ["trade_code", "est_report_y"], sort=False
    ).eps_add.shift()
    raw["delta_add"] = (raw.eps_add - previous_add).fillna(0).astype("int32")
    raw["revision_score"] = (
        (raw.eps_add - raw.eps_reduce) /
        np.maximum(raw.eps_add + raw.eps_reduce, 3)
    )
    raw["year_offset"] = (raw.est_report_y - raw.end_date // 10000).astype("int8")
    if not raw.year_offset.isin([0, 1]).all():
        raise ValueError("Only FY0/FY1 snapshots are supported")
    keys = ["trade_code", "end_date"]
    paired = raw.set_index(keys + ["year_offset"])[
        ["revision_score", "eps_orgnum"]
    ].unstack("year_offset")
    paired.columns = [f"{name}_fy{year}" for name, year in paired.columns]
    by_day = raw.groupby(keys, sort=False)
    paired["delta_add_total"] = by_day.delta_add.sum()
    paired["source_max_id"] = by_day.id.max()
    paired = paired.reset_index().sort_values(keys)
    fy0 = paired.revision_score_fy0
    fy1 = paired.revision_score_fy1
    paired["forecast_score"] = np.where(
        fy0.isna(), fy1, np.where(fy1.isna(), fy0, .6 * fy0 + .4 * fy1)
    )
    previous_score = paired.groupby("trade_code").forecast_score.shift()
    candidate = paired[
        (paired.forecast_score >= .5 - 1e-12) &
        (previous_score.isna() | (previous_score < .5 - 1e-12)) &
        ((paired.eps_orgnum_fy0.fillna(0) >= 3) |
         (paired.eps_orgnum_fy1.fillna(0) >= 3)) &
        (paired.delta_add_total >= 1)
    ].copy()
    cal = pd.read_csv(CALENDAR, parse_dates=["trade_date"])
    cal["trade_index"] = np.arange(len(cal))
    signal_date = pd.to_datetime(candidate.end_date.astype(str), format="%Y%m%d")
    idx = np.searchsorted(cal.trade_date.to_numpy(), signal_date.to_numpy(), side="right")
    if (idx >= len(cal)).any():
        raise ValueError("Trade calendar does not extend past the latest signal date")
    candidate["trade_date"] = cal.trade_date.iloc[idx].to_numpy()
    candidate["trade_index"] = idx
    candidate = candidate[candidate.trade_date.between("2026-06-01", "2026-10-16")]
    candidate.sort_values(
        ["trade_code", "trade_date", "forecast_score", "end_date"],
        ascending=[True, True, False, False], inplace=True,
    )
    candidate.drop_duplicates(["trade_code", "trade_date"], keep="first", inplace=True)
    candidate.sort_values(
        ["trade_date", "forecast_score", "trade_code"],
        ascending=[True, False, True], inplace=True,
    )
    candidate.rename(columns={
        "revision_score_fy0": "fy0_score",
        "revision_score_fy1": "fy1_score",
        "eps_orgnum_fy0": "fy0_orgnum",
        "eps_orgnum_fy1": "fy1_orgnum",
    }, inplace=True)
    cols = [
        "trade_code", "end_date", "trade_date", "trade_index", "forecast_score",
        "fy0_score", "fy1_score", "fy0_orgnum", "fy1_orgnum",
        "delta_add_total", "source_max_id",
    ]
    candidate[cols].to_csv(OUTPUT, index=False)
    COVERAGE.write_text(str(latest), encoding="utf-8")
    print({
        "raw_rows": len(raw), "latest_end_date": latest,
        "events": len(candidate), "event_days": candidate.trade_date.nunique(),
        "output": str(OUTPUT),
    })


if __name__ == "__main__":
    main()
