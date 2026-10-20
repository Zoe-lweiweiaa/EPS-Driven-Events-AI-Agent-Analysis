"""Analyze a read-only export of consensus EPS snapshots from ashare_prffrcastdt."""

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "data" / "epsdt_raw_2024_2026.tsv"
OUTPUT = ROOT / "epsdt_interval_analysis_20261016.json"
COLS = ["id", "trade_code", "end_date", "est_report_y", "est_eps", "update_time"]


def describe(series):
    series = pd.Series(series).dropna()
    if series.empty:
        return {"n": 0}
    return {
        "n": int(len(series)),
        "mean": round(float(series.mean()), 3),
        "median": round(float(series.median()), 3),
        "p25": round(float(series.quantile(.25)), 3),
        "p75": round(float(series.quantile(.75)), 3),
        "p90": round(float(series.quantile(.9)), 3),
        "p95": round(float(series.quantile(.95)), 3),
        "max": round(float(series.max()), 3),
    }


def main():
    if not INPUT.exists() or INPUT.stat().st_size == 0:
        raise FileNotFoundError(f"Live export missing or empty: {INPUT}")
    frame = pd.read_csv(
        INPUT, sep="\t", header=None, names=COLS, encoding="utf-8-sig",
        dtype={"id": "int64", "trade_code": "category", "end_date": "int32",
               "est_report_y": "int16", "est_eps": "string", "update_time": "Int64"},
        na_values=["NULL"],
    )
    frame = frame[frame.trade_code.astype(str).str.match(
        r"^(?:6[0-9]{5}\.SH|[03][0-9]{5}\.SZ)$"
    )].copy()
    assert frame.trade_code.notna().all() and frame.end_date.notna().all()
    assert not frame.duplicated(["trade_code", "end_date", "est_report_y"]).any()
    frame.sort_values(["trade_code", "est_report_y", "end_date"], inplace=True)
    group_cols = ["trade_code", "est_report_y"]
    group = frame.groupby(group_cols, observed=True, sort=False)
    frame["previous_eps"] = group.est_eps.shift()
    frame["previous_date"] = group.end_date.shift()
    dates = pd.to_datetime(frame.end_date.astype(str), format="%Y%m%d")
    prior_dates = pd.to_datetime(frame.previous_date, format="%Y%m%d")
    snapshot_gap = (dates - prior_dates).dt.days
    changed = frame.est_eps.notna() & frame.previous_eps.notna() & (
        frame.est_eps != frame.previous_eps
    )
    frame["change_date"] = dates.where(changed)
    change_rows = frame.loc[changed, ["trade_code", "est_report_y", "end_date", "est_eps"]].copy()
    change_rows["date"] = dates.loc[changed].to_numpy()
    change_rows["previous_change_date"] = change_rows.groupby(
        group_cols, observed=True
    ).date.shift()
    change_rows["gap_days"] = (
        change_rows.date - change_rows.previous_change_date
    ).dt.days
    # Also measure every observed EPS change relative to its immediately preceding
    # snapshot; this is bounded by snapshot frequency, not by previous change time.
    change_rows["gap_to_previous_snapshot_days"] = snapshot_gap.loc[changed].to_numpy()
    per_stock_mean = change_rows.groupby("trade_code", observed=True).gap_days.mean()
    result = {
        "source": str(INPUT),
        "rows": int(len(frame)),
        "stocks": int(frame.trade_code.nunique()),
        "date_min": str(dates.min().date()),
        "date_max": str(dates.max().date()),
        "missing_est_eps_rows": int(frame.est_eps.isna().sum()),
        "snapshot_pairs": describe(snapshot_gap),
        "eps_value_changes": int(changed.sum()),
        "fraction_adjacent_snapshots_with_eps_value_change": round(
            float(changed.sum() / snapshot_gap.notna().sum()), 6
        ),
        "gap_between_consecutive_consensus_eps_changes_calendar_days": describe(
            change_rows.gap_days
        ),
        "per_stock_mean_change_gap_calendar_days": describe(per_stock_mean),
        "stocks_with_two_or_more_changes": int(per_stock_mean.notna().sum()),
        "gap_from_change_to_previous_snapshot_days": describe(
            change_rows.gap_to_previous_snapshot_days
        ),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
