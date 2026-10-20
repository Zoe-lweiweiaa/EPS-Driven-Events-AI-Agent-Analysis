-- Read-only export from the first date after the saved 2026-09-15 snapshot.
-- The table has only a PRIMARY(id) index. The saved source's maximum id is
-- 175220633; ids increased with end_date throughout the saved September rows.
-- This range avoids a full scan of the 42 GB table. Recheck this assumption
-- if the source is rebuilt with different ids.
-- Run with mysql --batch --raw --quick --skip-column-names.
SELECT
    id, trade_code, end_date, est_report_y,
    eps_add, eps_reduce, eps_maintain, eps_first,
    eps_num, eps_orgnum, eps_researchnum, update_time
FROM gangtise.ashare_prffrcaststat
WHERE id > 175220633
  AND cycle_period = 60
  AND cycle_typ = CONVERT(0xE697A5 USING utf8mb4)
  AND (trade_code LIKE '6%.SH'
       OR trade_code LIKE '0%.SZ'
       OR trade_code LIKE '3%.SZ')
  AND end_date BETWEEN 20260916 AND 20261016
  AND CAST(est_report_y AS UNSIGNED) IN (
      end_date DIV 10000,
      end_date DIV 10000 + 1
  );
