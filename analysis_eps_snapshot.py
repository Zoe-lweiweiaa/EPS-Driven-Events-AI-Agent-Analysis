"""Read-only diagnostics for the saved 60-day EPS snapshot export.

The export stops at 2026-09-15 and is not the underlying analyst forecast table.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
NAMES = [
    "id", "trade_code", "end_date", "est_report_y", "eps_add",
    "eps_reduce", "eps_maintain", "eps_first", "eps_num",
    "eps_orgnum", "eps_researchnum", "update_time",
]
DTYPES = {
    "id": "int64", "trade_code": "category", "end_date": "int32",
    "est_report_y": "int16", "eps_add": "int32", "eps_reduce": "int32",
    "eps_orgnum": "int32", "update_time": "int64",
}


def describe(values):
    values = pd.Series(values).dropna()
    if values.empty:
        return {"n": 0}
    return {
        "n": int(len(values)),
        "mean": round(float(values.mean()), 3),
        "median": round(float(values.median()), 3),
        "p25": round(float(values.quantile(.25)), 3),
        "p75": round(float(values.quantile(.75)), 3),
        "p90": round(float(values.quantile(.9)), 3),
        "p95": round(float(values.quantile(.95)), 3),
        "max": round(float(values.max()), 3),
    }


def main():
    raw = pd.read_csv(
        DATA / "eps60_raw_2024_2026.tsv", sep="\t", header=None,
        names=NAMES, usecols=list(DTYPES), dtype=DTYPES, na_values=["NULL"],
    )
    raw = raw[raw.trade_code.astype(str).str.match(
        r"^(?:6[0-9]{5}\.SH|[03][0-9]{5}\.SZ)$"
    )].copy()
    assert not raw.isna().any().any()
    assert not raw.duplicated(["trade_code", "end_date", "est_report_y"]).any()
    raw.sort_values(["trade_code", "est_report_y", "end_date"], inplace=True)
    group = raw.groupby(["trade_code", "est_report_y"], observed=True, sort=False)
    raw["prev_date"] = group["end_date"].shift()
    raw["prev_add"] = group["eps_add"].shift()
    raw["prev_reduce"] = group["eps_reduce"].shift()
    date = pd.to_datetime(raw.end_date.astype(str), format="%Y%m%d")
    prev_date = pd.to_datetime(raw.prev_date, format="%Y%m%d")
    gap = (date - prev_date).dt.days
    changed = ((raw.eps_add != raw.prev_add) | (raw.eps_reduce != raw.prev_reduce)) & raw.prev_date.notna()
    # Consecutive observed changes rather than consecutive daily snapshots.
    raw["changed_date"] = date.where(changed)
    previous_changed_date = group["changed_date"].ffill().groupby(
        [raw.trade_code, raw.est_report_y], observed=True
    ).shift()
    change_gap = (date - previous_changed_date).dt.days.where(changed)
    raw["delta_add"] = (raw.eps_add - raw.prev_add).fillna(0).astype("int32")
    raw["revision_score"] = (
        (raw.eps_add - raw.eps_reduce) /
        np.maximum(raw.eps_add + raw.eps_reduce, 3)
    )
    raw["year_offset"] = (raw.est_report_y - raw.end_date // 10000).astype("int8")
    assert raw.year_offset.isin([0, 1]).all()
    update_date = pd.to_datetime((raw.update_time // 1000000).astype(str), format="%Y%m%d")
    update_lag = (update_date - date).dt.days

    key = ["trade_code", "end_date"]
    paired = raw.set_index(key + ["year_offset"])[
        ["revision_score", "eps_orgnum"]
    ].unstack("year_offset")
    paired.columns = [f"{value}_fy{year}" for value, year in paired.columns]
    paired["delta_add_total"] = raw.groupby(key, observed=True).delta_add.sum()
    paired = paired.reset_index().sort_values(key)
    s0 = paired.get("revision_score_fy0")
    s1 = paired.get("revision_score_fy1")
    paired["forecast_score"] = np.where(
        s0.isna(), s1, np.where(s1.isna(), s0, .6 * s0 + .4 * s1)
    )
    paired["previous_score"] = paired.groupby("trade_code", observed=True).forecast_score.shift()
    score = paired.forecast_score >= .5 - 1e-12
    crossing = score & (paired.previous_score.isna() | (paired.previous_score < .5 - 1e-12))
    org = (paired.eps_orgnum_fy0.fillna(0) >= 3) | (paired.eps_orgnum_fy1.fillna(0) >= 3)
    added = paired.delta_add_total >= 1
    candidates = paired[crossing & org & added].copy()
    cal = pd.read_csv(DATA / "trade_days_2024_2026.csv", parse_dates=["trade_date"])
    cal["trade_index"] = np.arange(len(cal))
    cdates = pd.to_datetime(candidates.end_date.astype(str), format="%Y%m%d")
    idx = np.searchsorted(cal.trade_date.to_numpy(), cdates.to_numpy(), side="right")
    candidates["trade_index"] = idx
    candidates["trade_date"] = cal.trade_date.iloc[idx].to_numpy()
    candidates = candidates[
        (candidates.trade_date >= "2025-01-01") &
        (candidates.trade_date <= "2026-09-15")
    ].sort_values(["trade_code", "trade_index", "forecast_score", "end_date"],
                  ascending=[True, True, False, False])
    kept = []
    last = {}
    same_day = set()
    for row in candidates.itertuples():
        same_key = (row.trade_code, row.trade_index)
        if same_key in same_day:
            continue
        same_day.add(same_key)
        if row.trade_code in last and row.trade_index - last[row.trade_code] < 10:
            continue
        last[row.trade_code] = row.trade_index
        kept.append(row.Index)
    events = candidates.loc[kept].copy()
    no_cooldown_unique = candidates.drop_duplicates(
        ["trade_code", "trade_date"], keep="first"
    )
    # Shares of snapshots, then of stocks by month: not a return/profit probability.
    monthly = events.groupby(events.trade_date.dt.to_period("M")).size()
    event_gaps = events.sort_values(["trade_code", "trade_index"]).groupby(
        "trade_code", observed=True
    ).trade_index.diff()
    summary = {
        "source": str(DATA / "eps60_raw_2024_2026.tsv"),
        "date_min": str(date.min().date()),
        "date_max": str(date.max().date()),
        "rows": int(len(raw)),
        "stocks": int(raw.trade_code.nunique()),
        "stock_days": int(len(paired)),
        "stock_forecast_year_pairs": int(group.ngroups),
        "consecutive_snapshot_gap_calendar_days": describe(gap),
        "fraction_consecutive_snapshots_with_changed_counts": round(float(changed.sum() / gap.notna().sum()), 6),
        "change_observation_gap_calendar_days": describe(change_gap),
        "per_stock_mean_change_gap_calendar_days": describe(change_gap.groupby(
            raw.trade_code, observed=True
        ).mean()),
        "update_time_minus_end_date_days": describe(update_lag),
        "fraction_update_time_after_end_date_30_days": round(float((update_lag > 30).mean()), 6),
        "event_gap_trading_days": describe(event_gaps),
        "eps_add": describe(raw.eps_add),
        "eps_reduce": describe(raw.eps_reduce),
        "eps_orgnum": describe(raw.eps_orgnum),
        "fraction_rows_add_gt_0": round(float((raw.eps_add > 0).mean()), 6),
        "fraction_rows_reduce_gt_0": round(float((raw.eps_reduce > 0).mean()), 6),
        "fraction_rows_add_gt_reduce": round(float((raw.eps_add > raw.eps_reduce).mean()), 6),
        "fraction_stock_days_score_ge_05": round(float(score.mean()), 6),
        "filter_counts": {
            "score_ge_05": int(score.sum()),
            "crossing": int(crossing.sum()),
            "crossing_and_org": int((crossing & org).sum()),
            "crossing_and_org_and_added": int((crossing & org & added).sum()),
            "candidates_in_trade_window": int(len(candidates)),
            "after_cooldown": int(len(events)),
        },
        "event_stocks": int(events.trade_code.nunique()),
        "june_to_september_candidates_no_cooldown": int(
            no_cooldown_unique.trade_date.between("2026-06-01", "2026-09-15").sum()
        ),
        "june_to_september_events_after_cooldown": int(
            events.trade_date.between("2026-06-01", "2026-09-15").sum()
        ),
        "event_days": int(events.trade_date.nunique()),
        "event_monthly": {str(k): int(v) for k, v in monthly.items()},
        "events_per_trading_day": describe(events.groupby("trade_date").size().reindex(
            cal.loc[cal.trade_date.between("2025-01-01", "2026-09-15"), "trade_date"],
            fill_value=0
        )),
    }
    expected = pd.read_csv(DATA / "events_2025_2026_ashares.csv")
    summary["reference_event_count"] = int(len(expected))
    summary["matches_reference_count"] = len(events) == len(expected)
    unique_snapshot_dates = pd.Series(paired.end_date.unique())
    unique_next_idx = np.searchsorted(
        cal.trade_date.to_numpy(),
        pd.to_datetime(unique_snapshot_dates.astype(str), format="%Y%m%d").to_numpy(),
        side="right",
    )
    next_trade_date = pd.Series(
        cal.trade_date.iloc[unique_next_idx].to_numpy(), index=unique_snapshot_dates.to_numpy()
    )
    summary["stock_days_mapped_into_trade_window"] = int(
        next_trade_date.reindex(paired.end_date).between("2025-01-01", "2026-09-15").sum()
    )
    summary["market_days_with_event"] = int((monthly.sum() > 0) * events.trade_date.nunique())
    summary["market_trading_days"] = int(cal.trade_date.between("2025-01-01", "2026-09-15").sum())
    summary["event_forecast_score"] = describe(events.forecast_score)
    summary["event_delta_add_total"] = describe(events.delta_add_total)
    summary["threshold_sensitivity"] = {}
    for threshold in (.4, .5, .6, .7):
        at_threshold = paired.forecast_score >= threshold - 1e-12
        fresh = paired.previous_score.isna() | (paired.previous_score < threshold - 1e-12)
        trial = paired[at_threshold & fresh & org & added].copy()
        trial_idx = np.searchsorted(
            cal.trade_date.to_numpy(),
            pd.to_datetime(trial.end_date.astype(str), format="%Y%m%d").to_numpy(),
            side="right",
        )
        trial["trade_index"] = trial_idx
        trial["trade_date"] = cal.trade_date.iloc[trial_idx].to_numpy()
        trial = trial[trial.trade_date.between("2025-01-01", "2026-09-15")]
        trial = trial.sort_values(
            ["trade_code", "trade_index", "forecast_score", "end_date"],
            ascending=[True, True, False, False],
        )
        prior = {}
        seen = set()
        accepted = 0
        for item in trial.itertuples():
            today = (item.trade_code, item.trade_index)
            if today in seen:
                continue
            seen.add(today)
            if item.trade_code in prior and item.trade_index - prior[item.trade_code] < 10:
                continue
            prior[item.trade_code] = item.trade_index
            accepted += 1
        summary["threshold_sensitivity"][str(threshold)] = {
            "before_cooldown": int(len(trial)), "after_cooldown": accepted
        }
    trades = pd.read_csv(
        ROOT / "eps_event_baseline_回测结果_20260927_224653" / "交易记录.csv"
    )
    trades["date"] = pd.to_datetime(trades["交易时间"]).dt.normalize()
    trades["signed_quantity"] = np.where(
        trades["买卖方向"] == "BUY", trades["成交数量"], -trades["成交数量"]
    )
    positions = trades.pivot_table(
        index="date", columns="合约/证券代码", values="signed_quantity",
        aggfunc="sum", fill_value=0,
    ).reindex(
        cal.loc[cal.trade_date.between("2025-01-01", "2026-09-15"), "trade_date"],
        fill_value=0,
    ).cumsum()
    held = (positions > 0).sum(axis=1)
    summary["backtest_buy_trades"] = int((trades["买卖方向"] == "BUY").sum())
    summary["backtest_sell_trades"] = int((trades["买卖方向"] == "SELL").sum())
    summary["backtest_held_names"] = describe(held)
    summary["backtest_days_held_below_3"] = int((held < 3).sum())
    summary["backtest_days_held_below_5"] = int((held < 5).sum())
    summary["backtest_days_held_20"] = int((held == 20).sum())
    out = ROOT / "eps_snapshot_analysis_20261016.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
