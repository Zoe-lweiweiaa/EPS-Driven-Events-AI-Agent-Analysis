-- Read-only export. Run with mysql --batch --raw --quick --skip-column-names.
-- 2024-12 provides a warm-up snapshot for 2025 event detection.
SELECT
    id,
    trade_code,
    end_date,
    est_report_y,
    eps_add,
    eps_reduce,
    eps_maintain,
    eps_first,
    eps_num,
    eps_orgnum,
    eps_researchnum,
    update_time
FROM gangtise.ashare_prffrcaststat
WHERE cycle_period = 60
  AND cycle_typ = CONVERT(0xE697A5 USING utf8mb4)
  AND (trade_code LIKE '6%.SH'
       OR trade_code LIKE '0%.SZ'
       OR trade_code LIKE '3%.SZ')
  AND end_date BETWEEN 20241201 AND 20260915
  AND CAST(est_report_y AS UNSIGNED) IN (
      end_date DIV 10000,
      end_date DIV 10000 + 1
  );

