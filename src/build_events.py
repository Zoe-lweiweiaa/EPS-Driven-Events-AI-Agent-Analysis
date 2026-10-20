"""Build frozen EPS-revision events from a MySQL TSV export.

The calendar is supplied by SuperMind. This is a local preprocessing script:
it never sends raw analyst rows to the remote platform.
"""

import duckdb
import pandas as pd


def build_events(
    raw_path,
    calendar_path,
    output_path,
    database_path=":memory:",
    first_trade_date="2025-01-01",
    last_trade_date="2026-09-15",
    cooldown_days=10,
):
    if cooldown_days < 0:
        raise ValueError("cooldown_days must be nonnegative")
    con = duckdb.connect(database_path)
    con.execute("SET threads = 4")
    con.execute(
        """
        CREATE TABLE snapshots AS
        SELECT * FROM read_csv(
            ?, delim='\t', header=false, nullstr='NULL',
            columns={
                'id': 'BIGINT',
                'trade_code': 'VARCHAR',
                'end_date': 'INTEGER',
                'est_report_y': 'INTEGER',
                'eps_add': 'INTEGER',
                'eps_reduce': 'INTEGER',
                'eps_maintain': 'INTEGER',
                'eps_first': 'INTEGER',
                'eps_num': 'INTEGER',
                'eps_orgnum': 'INTEGER',
                'eps_researchnum': 'INTEGER',
                'update_time': 'BIGINT'
            }
        )
        WHERE trade_code LIKE '6%.SH'
           OR trade_code LIKE '0%.SZ'
           OR trade_code LIKE '3%.SZ'
        """,
        [raw_path],
    )
    source_rows, incomplete_rows = con.execute(
        """
        SELECT COUNT(*), COUNT(*) FILTER (
            WHERE trade_code IS NULL OR end_date IS NULL
               OR est_report_y IS NULL OR eps_add IS NULL
               OR eps_reduce IS NULL OR eps_orgnum IS NULL
        ) FROM snapshots
        """
    ).fetchone()
    if source_rows == 0 or incomplete_rows:
        raise ValueError(
            f"Invalid export: rows={source_rows}, incomplete={incomplete_rows}"
        )
    duplicate_rows = con.execute(
        """
        SELECT COUNT(*) - COUNT(DISTINCT
            trade_code || ':' || CAST(end_date AS VARCHAR) || ':' ||
            CAST(est_report_y AS VARCHAR))
        FROM snapshots
        """
    ).fetchone()[0]
    if duplicate_rows:
        raise ValueError(f"Duplicate stock/date/forecast-year rows: {duplicate_rows}")

    con.execute(
        """
        CREATE TABLE year_scores AS
        WITH lagged AS (
            SELECT *,
                LAG(eps_add) OVER (
                    PARTITION BY trade_code, est_report_y ORDER BY end_date
                ) AS previous_add
            FROM snapshots
        )
        SELECT
            id, trade_code, end_date, est_report_y,
            eps_add, eps_reduce, eps_orgnum,
            CAST(eps_add - eps_reduce AS DOUBLE) /
                GREATEST(eps_add + eps_reduce, 3) AS revision_score,
            CASE WHEN previous_add IS NULL THEN 0
                 ELSE eps_add - previous_add END AS delta_add
        FROM lagged
        """
    )
    con.execute(
        """
        CREATE TABLE stock_days AS
        WITH paired AS (
            SELECT trade_code, end_date,
                MAX(CASE WHEN est_report_y = FLOOR(end_date / 10000)
                    THEN revision_score END) AS fy0_score,
                MAX(CASE WHEN est_report_y = FLOOR(end_date / 10000) + 1
                    THEN revision_score END) AS fy1_score,
                MAX(CASE WHEN est_report_y = FLOOR(end_date / 10000)
                    THEN eps_orgnum END) AS fy0_orgnum,
                MAX(CASE WHEN est_report_y = FLOOR(end_date / 10000) + 1
                    THEN eps_orgnum END) AS fy1_orgnum,
                SUM(delta_add) AS delta_add_total,
                MAX(id) AS source_max_id
            FROM year_scores
            GROUP BY trade_code, end_date
        ), scored AS (
            SELECT *,
                CASE WHEN fy0_score IS NULL THEN fy1_score
                     WHEN fy1_score IS NULL THEN fy0_score
                     ELSE 0.6 * fy0_score + 0.4 * fy1_score
                END AS forecast_score
            FROM paired
        )
        SELECT *,
            LAG(forecast_score) OVER (
                PARTITION BY trade_code ORDER BY end_date
            ) AS previous_score
        FROM scored
        """
    )
    con.execute(
        """
        CREATE TABLE calendar AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               ROW_NUMBER() OVER (ORDER BY trade_date) - 1 AS trade_index
        FROM read_csv(?, header=true)
        """,
        [calendar_path],
    )
    con.execute(
        """
        CREATE TABLE date_map AS
        SELECT s.end_date, MIN(c.trade_date) AS trade_date
        FROM (SELECT DISTINCT end_date FROM stock_days) s
        JOIN calendar c ON c.trade_date >
            STRPTIME(CAST(s.end_date AS VARCHAR), '%Y%m%d')
        GROUP BY s.end_date
        """
    )
    candidates = con.execute(
        """
        SELECT c.trade_code, c.end_date, m.trade_date, t.trade_index,
               c.forecast_score, c.fy0_score, c.fy1_score,
               c.fy0_orgnum, c.fy1_orgnum, c.delta_add_total,
               c.source_max_id
        FROM stock_days c
        JOIN date_map m USING (end_date)
        JOIN calendar t ON t.trade_date = m.trade_date
        WHERE c.forecast_score >= 0.5
          AND (c.previous_score IS NULL OR c.previous_score < 0.5)
          AND (COALESCE(c.fy0_orgnum, 0) >= 3
               OR COALESCE(c.fy1_orgnum, 0) >= 3)
          AND c.delta_add_total >= 1
          AND m.trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY c.trade_code, t.trade_index,
                 c.forecast_score DESC, c.end_date DESC
        """,
        [first_trade_date, last_trade_date],
    ).fetchall()
    kept = []
    last_index = {}
    same_trade_day = set()
    for row in candidates:
        trade_code, _, trade_date, trade_index = row[:4]
        key = (trade_code, trade_date)
        if key in same_trade_day:
            continue
        same_trade_day.add(key)
        previous_index = last_index.get(trade_code)
        if previous_index is not None and trade_index - previous_index < cooldown_days:
            continue
        kept.append(row)
        last_index[trade_code] = trade_index

    columns = [
        "trade_code", "end_date", "trade_date", "trade_index",
        "forecast_score", "fy0_score", "fy1_score", "fy0_orgnum",
        "fy1_orgnum", "delta_add_total", "source_max_id",
    ]
    frame = pd.DataFrame.from_records(kept, columns=columns)
    frame = frame.sort_values(
        ["trade_date", "forecast_score", "trade_code"],
        ascending=[True, False, True],
    )
    frame.to_csv(output_path, index=False)
    summary = {
        "source_rows": source_rows,
        "stock_days": con.execute("SELECT COUNT(*) FROM stock_days").fetchone()[0],
        "pre_cooldown_events": len(candidates),
        "cooldown_days": cooldown_days,
        "events": len(frame),
        "first_trade_date": str(frame.trade_date.min()) if len(frame) else None,
        "last_trade_date": str(frame.trade_date.max()) if len(frame) else None,
    }
    print(summary)
    con.close()
    return summary
