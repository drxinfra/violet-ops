-- Ten slowest statements since the last reset
SELECT
    s.queryid,
    d.datname,
    round(s.mean_exec_time::numeric, 1) AS mean_ms,
    s.calls,
    left(s.query, 80) AS query
FROM pg_stat_statements s
JOIN pg_database d ON d.oid = s.dbid
WHERE s.calls > 10
  AND d.datname = :'db'
ORDER BY s.mean_exec_time DESC
LIMIT 10;
