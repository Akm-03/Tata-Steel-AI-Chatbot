-- ================================================================
-- TATA STEEL — DB FIX SCRIPT
-- Run this ONCE in pgAdmin Query Tool on tata_steel_ops database
-- Fixes: null cols, parameter_unit, schema cleanup
-- ================================================================

-- ── 1. Fix parameter_unit in fact_deviation (was NULL) ──────────
UPDATE gmaw.fact_deviation
SET parameter_unit = CASE parameter
    WHEN 'weld_cur'  THEN 'A'
    WHEN 'weld_volt' THEN 'V'
    WHEN 'weld_gas'  THEN 'L/min'
    WHEN 'hs_temp'   THEN '°C'
    WHEN 'amb_temp'  THEN '°C'
    ELSE 'unknown'
END;

-- Verify:
-- SELECT parameter, parameter_unit, COUNT(*) FROM gmaw.fact_deviation GROUP BY 1,2;

-- ── 2. Drop always-NULL / junk cols from fact_periodic_gmaw ─────
ALTER TABLE gmaw.fact_periodic_gmaw
    DROP COLUMN IF EXISTS motor_cur,
    DROP COLUMN IF EXISTS motor_volt,
    DROP COLUMN IF EXISTS weight,
    DROP COLUMN IF EXISTS dis,
    DROP COLUMN IF EXISTS health_status_lpg_flow_meter,
    DROP COLUMN IF EXISTS health_status_o2_flow_meter1,
    DROP COLUMN IF EXISTS health_status_o2_flow_meter2,
    DROP COLUMN IF EXISTS cut_mm_mtr,
    DROP COLUMN IF EXISTS type,
    DROP COLUMN IF EXISTS created_at;

-- ── 3. Drop always-NULL cols from fact_summarize_clad ───────────
ALTER TABLE clad.fact_summarize_clad
    DROP COLUMN IF EXISTS on_cur,
    DROP COLUMN IF EXISTS off_cur,
    DROP COLUMN IF EXISTS on_volt,
    DROP COLUMN IF EXISTS off_volt,
    DROP COLUMN IF EXISTS on_weight,
    DROP COLUMN IF EXISTS off_weight;

-- ── 4. Drop junk from fact_periodic_gascutting ──────────────────
ALTER TABLE gascutting.fact_periodic_gascutting
    DROP COLUMN IF EXISTS high_weld_cur_threshold,
    DROP COLUMN IF EXISTS low_weld_cur_threshold,
    DROP COLUMN IF EXISTS type,
    DROP COLUMN IF EXISTS created_at;

-- ── 5. Add threshold context as a reference table ───────────────
-- (Threshold values are constant: 270/220 A, 30/20 V, 30/20 L/min)
-- The chatbot system prompt will carry these — no need to store per-row

-- ── 6. Verify final column counts ───────────────────────────────
SELECT table_schema, table_name,
       COUNT(*) AS column_count
FROM information_schema.columns
WHERE table_schema IN ('gmaw','gascutting','clad','reference')
GROUP BY 1, 2
ORDER BY 1, 2;

-- ── 7. Verify parameter_unit fix ────────────────────────────────
SELECT parameter, parameter_unit, COUNT(*) AS events
FROM gmaw.fact_deviation
GROUP BY 1, 2
ORDER BY 3 DESC;

-- ── 8. Spot check: real data queries ────────────────────────────
-- GMAW sensor averages (active welding only):
SELECT machine_name, shift_name,
       ROUND(AVG(weld_cur)::NUMERIC, 2) AS avg_weld_cur_A,
       ROUND(AVG(weld_volt)::NUMERIC, 2) AS avg_weld_volt_V,
       COUNT(*) AS readings
FROM gmaw.fact_periodic_gmaw
WHERE is_welding = TRUE
GROUP BY machine_name, shift_name
ORDER BY machine_name, shift_name;

-- CLAD valid sessions (loss_weight only 3.3% nonzero — expected, note this):
SELECT machine_name, shift_name,
       COUNT(*) FILTER (WHERE NOT is_instantaneous) AS valid_sessions,
       ROUND(AVG(avg_weld_cur) FILTER (WHERE NOT is_instantaneous)::NUMERIC, 2) AS avg_cur_A,
       ROUND(AVG(avg_weld_volt) FILTER (WHERE NOT is_instantaneous)::NUMERIC, 2) AS avg_volt_V,
       SUM(loss_weight) FILTER (WHERE NOT is_instantaneous AND loss_weight > 0) AS total_loss_weight_g
FROM clad.fact_summarize_clad
GROUP BY 1, 2;

-- GASCUTTING productivity:
SELECT shift_name,
       COUNT(*) AS cuts,
       ROUND(AVG(mm_per_min)::NUMERIC,1) AS avg_speed_mm_per_min,
       ROUND(SUM(net_lpg_consumption)::NUMERIC,2) AS total_lpg_litres,
       ROUND(SUM(total_o2_consumption)::NUMERIC,2) AS total_o2_litres,
       ROUND(AVG(thickness)::NUMERIC,2) AS avg_thickness_mm
FROM gascutting.fact_summarize_gascutting
WHERE timer_overflow = FALSE AND travel_outlier = FALSE
GROUP BY 1;