-- =============================================================
-- TATA STEEL ENTERPRISE CHATBOT — POSTGRESQL SCHEMA
-- Equivalent to snowflake_ddl.sql but for PostgreSQL
-- Database : tata_steel_ops
-- Schemas  : reference | gmaw | gascutting | clad
-- =============================================================

-- Run this entire file once in psql or pgAdmin before loading CSVs.

-- ── 0. CREATE DATABASE (run as superuser outside this script) ─
-- createdb tata_steel_ops
-- or in psql: CREATE DATABASE tata_steel_ops;
-- Then connect: \c tata_steel_ops

-- ── CREATE SCHEMAS ────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS gmaw;
CREATE SCHEMA IF NOT EXISTS gascutting;
CREATE SCHEMA IF NOT EXISTS clad;


-- =============================================================
-- SCHEMA: reference
-- =============================================================

-- ── 1. dim_machine_type ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS reference.dim_machine_type (
    mtid                SMALLINT        PRIMARY KEY,
    machine_type_name   VARCHAR(20)     NOT NULL,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ
);
COMMENT ON TABLE reference.dim_machine_type IS
    '3 machine types: GMAW(1), CLAD(2), GASCUTTING(3). '
    'Chatbot: always resolve machine type before answering parameter queries.';

-- Seed — 3 rows, no CSV needed
INSERT INTO reference.dim_machine_type VALUES
    (1, 'GMAW',       TRUE, '2024-03-14 16:59:26+05:30', '2024-03-14 16:59:26+05:30'),
    (2, 'CLAD',       TRUE, '2024-03-14 16:59:36+05:30', '2024-03-14 16:59:36+05:30'),
    (3, 'GASCUTTING', TRUE, '2024-03-14 16:59:54+05:30', '2024-03-14 16:59:54+05:30')
ON CONFLICT (mtid) DO NOTHING;


-- ── 2. dim_machines ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reference.dim_machines (
    mid                         SMALLINT        PRIMARY KEY,
    name                        VARCHAR(50)     NOT NULL,
    hardware_id                 VARCHAR(20)     NOT NULL UNIQUE,
    des                         VARCHAR(100),
    mtid                        SMALLINT        NOT NULL REFERENCES reference.dim_machine_type(mtid),
    machine_type_name           VARCHAR(20)     NOT NULL,
    is_gmaw                     BOOLEAN         NOT NULL DEFAULT FALSE,
    is_clad                     BOOLEAN         NOT NULL DEFAULT FALSE,
    is_gascutting               BOOLEAN         NOT NULL DEFAULT FALSE,
    msid                        INTEGER,
    hid                         INTEGER,
    orgid                       INTEGER,
    mcsid                       INTEGER,
    mcid                        INTEGER,
    rpm_multiplication_factor   FLOAT,
    notify                      BOOLEAN,
    deleted                     BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ,
    updated_at                  TIMESTAMPTZ
);
COMMENT ON TABLE reference.dim_machines IS
    '17 machines: GMAW×14, CLAD×2 (Rectifier1/2), GASCUTTING×1. '
    'is_gmaw/is_clad/is_gascutting flags used by chatbot guardrails.';


-- ── 3. dim_users ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reference.dim_users (
    uid                 INTEGER         PRIMARY KEY,
    name                VARCHAR(100)    NOT NULL,
    email               VARCHAR(150),
    is_tata_email       BOOLEAN,
    phno                BIGINT,
    roleid              SMALLINT,
    role_name           VARCHAR(30),
    hid                 INTEGER,
    orgid               INTEGER,
    certificate_id      VARCHAR(50),
    identification_no   VARCHAR(50),
    operator_rfid       VARCHAR(50),
    username            VARCHAR(100),
    deleted             BOOLEAN         NOT NULL DEFAULT FALSE,
    active_status       BOOLEAN         NOT NULL DEFAULT FALSE,
    is_test_account     BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ
);
COMMENT ON TABLE reference.dim_users IS
    'SECURITY: password/tokens already dropped in cleaning. '
    'Chatbot: filter deleted=FALSE AND is_test_account=FALSE always.';

-- Safe view for chatbot (hides email/phone)
CREATE OR REPLACE VIEW reference.v_users_safe AS
    SELECT uid, name, roleid, role_name, orgid, hid,
           operator_rfid, username, active_status
    FROM reference.dim_users
    WHERE deleted = FALSE AND is_test_account = FALSE;


-- =============================================================
-- SCHEMA: gmaw
-- =============================================================

-- ── 4. fact_deviation ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gmaw.fact_deviation (
    hardware_id         VARCHAR(20),
    mid                 SMALLINT        REFERENCES reference.dim_machines(mid),
    machine_name        VARCHAR(50),
    machine_type        VARCHAR(20),
    oid                 VARCHAR(20),
    shid                VARCHAR(20),
    start_tm            TIMESTAMPTZ,
    end_tm              TIMESTAMPTZ,
    span_seconds        FLOAT,
    span_raw            FLOAT,
    type                VARCHAR(10),
    parameter           VARCHAR(30),
    deviation_label     VARCHAR(60),
    parameter_unit      VARCHAR(10),
    is_gmaw             BOOLEAN,
    is_clad             BOOLEAN
);
COMMENT ON TABLE gmaw.fact_deviation IS
    'Out-of-threshold events for GMAW and CLAD. '
    'parameter_unit: weld_cur=A, weld_volt=V, weld_gas=L/min, hs_temp=°C, amb_temp=°C. '
    'span_seconds = duration of deviation event in seconds.';

CREATE INDEX IF NOT EXISTS idx_dev_machine_type ON gmaw.fact_deviation(machine_type);
CREATE INDEX IF NOT EXISTS idx_dev_start_tm     ON gmaw.fact_deviation(start_tm);
CREATE INDEX IF NOT EXISTS idx_dev_label        ON gmaw.fact_deviation(deviation_label);

-- Filtered views
CREATE OR REPLACE VIEW gmaw.fact_deviation_gmaw AS
    SELECT * FROM gmaw.fact_deviation WHERE machine_type = 'GMAW';
CREATE OR REPLACE VIEW clad.fact_deviation_clad AS
    SELECT * FROM gmaw.fact_deviation WHERE machine_type = 'CLAD';


-- ── 5. fact_periodic_gmaw ────────────────────────────────────
CREATE TABLE IF NOT EXISTS gmaw.fact_periodic_gmaw (
    pdid                        VARCHAR(50),
    business_date               DATE,
    shift_name                  VARCHAR(10),
    machine_type                VARCHAR(20)     DEFAULT 'GMAW',
    machine_name                VARCHAR(50),
    hardware_id                 VARCHAR(20),
    job_name                    VARCHAR(100),
    tm                          TIMESTAMPTZ,

    -- Weld parameters
    weld_cur                    FLOAT,          -- Amperes (A). 0=idle. Normal 80-270A
    weld_volt                   FLOAT,          -- Volts (V). Normal 20-30V
    weld_gas                    FLOAT,          -- L/min shielding gas. Normal 20-30
    hs_temp                     FLOAT,          -- °C heatsink temperature
    amb_temp                    FLOAT,          -- °C ambient temperature
    rpm                         FLOAT,          -- RPM wire feed speed

    -- State flags
    is_idle                     BOOLEAN,
    is_welding                  BOOLEAN,
    mstatus                     VARCHAR(20),

    -- Deviation flags
    current_deviation_flag      VARCHAR(15),    -- none|single|sustained
    voltage_deviation_flag      VARCHAR(15),
    gas_deviation_flag          VARCHAR(15),

    -- Network & operator
    network                     FLOAT,          -- dBm WiFi signal
    oid                         VARCHAR(20),

    -- Thresholds
    high_weld_cur_threshold     FLOAT,          -- A
    low_weld_cur_threshold      FLOAT,          -- A
    high_weld_volt_threshold    FLOAT,          -- V
    low_weld_volt_threshold     FLOAT,          -- V
    high_weld_gas_threshold     FLOAT,          -- L/min
    low_weld_gas_threshold      FLOAT,          -- L/min

    thickness                   FLOAT,          -- mm
    cut_mm_mtr                  FLOAT,
    type                        VARCHAR(20)
);
COMMENT ON TABLE gmaw.fact_periodic_gmaw IS
    'Real-time GMAW sensor readings. '
    'ALWAYS filter is_welding=TRUE for weld parameter averages — is_idle rows have weld_cur=0. '
    'weld_cur unit=A, weld_volt=V, weld_gas=L/min, hs_temp/amb_temp=°C, rpm=RPM, network=dBm.';

CREATE INDEX IF NOT EXISTS idx_pgmaw_date     ON gmaw.fact_periodic_gmaw(business_date);
CREATE INDEX IF NOT EXISTS idx_pgmaw_machine  ON gmaw.fact_periodic_gmaw(machine_name);
CREATE INDEX IF NOT EXISTS idx_pgmaw_welding  ON gmaw.fact_periodic_gmaw(is_welding);
CREATE INDEX IF NOT EXISTS idx_pgmaw_shift    ON gmaw.fact_periodic_gmaw(shift_name);


-- ── 6. fact_machine_derived_gmaw ─────────────────────────────
CREATE TABLE IF NOT EXISTS gmaw.fact_machine_derived_gmaw (
    business_date               DATE,
    shift_name                  VARCHAR(10),
    machine_type                VARCHAR(20)     DEFAULT 'GMAW',
    machine_name                VARCHAR(50),
    oid                         VARCHAR(20),
    period_start_time           VARCHAR(30),
    period_end_time             VARCHAR(30),

    -- Time (all MINUTES)
    active                      FLOAT,          -- minutes actual arc-on
    idle                        FLOAT,          -- minutes powered, not welding
    inrepair                    FLOAT,          -- minutes scheduled maintenance
    breakdown                   FLOAT,          -- minutes unplanned downtime
    target_arc_time             FLOAT,          -- minutes planned arc time

    -- Weight (GRAMS)
    deposit                     FLOAT,          -- grams actual deposit
    target_deposit              FLOAT,          -- grams planned deposit

    -- Unknown cols pending domain expert clarification
    unknown_a                   FLOAT,
    unknown_b                   FLOAT,
    unknown_c                   FLOAT,

    -- Computed KPIs
    mid                         SMALLINT        REFERENCES reference.dim_machines(mid),
    machine_type_verified       VARCHAR(20),
    total_accounted_minutes     FLOAT,
    time_allocation_valid       BOOLEAN,
    arc_efficiency_pct          FLOAT,          -- % = (active/target_arc_time)*100
    deposit_efficiency_pct      FLOAT           -- % = (deposit/target_deposit)*100
);
COMMENT ON TABLE gmaw.fact_machine_derived_gmaw IS
    'Per-shift GMAW aggregates. arc_efficiency_pct unit=%. '
    'active/idle/inrepair/breakdown in MINUTES. deposit/target_deposit in GRAMS.';


-- =============================================================
-- SCHEMA: gascutting
-- =============================================================

-- ── 7. fact_periodic_gascutting ──────────────────────────────
CREATE TABLE IF NOT EXISTS gascutting.fact_periodic_gascutting (
    pdid                            VARCHAR(50),
    business_date                   DATE,
    shift_name                      VARCHAR(10),
    machine_type                    VARCHAR(20)     DEFAULT 'GASCUTTING',
    machine_name                    VARCHAR(50),
    hardware_id                     VARCHAR(20),
    job_name                        VARCHAR(100),
    tm                              TIMESTAMPTZ,
    mstatus                         VARCHAR(20),

    -- Gas parameters
    lpg_flow                        FLOAT,          -- L/min fuel gas
    o2_flow_meter1                  FLOAT,          -- L/min oxygen meter1
    o2_flow_meter2                  FLOAT,          -- L/min oxygen meter2
    total_lpg_consumption           FLOAT,          -- litres cumulative
    total_o2_consumption_meter1     FLOAT,          -- litres cumulative
    total_o2_consumption_meter2     FLOAT,          -- litres cumulative

    -- Torch position (split from "X,Y" source string)
    travel_in_mm                    FLOAT,          -- mm torch travel
    position_x                      FLOAT,          -- mm X coordinate
    position_y                      FLOAT,          -- mm Y coordinate

    -- Flags
    is_cutting                      BOOLEAN,
    lpg_below_detection             BOOLEAN,        -- TRUE: 0 ≠ zero consumption

    -- Sensor health
    health_status_lpg_flow_meter    VARCHAR(20),
    health_status_o2_flow_meter1    VARCHAR(20),
    health_status_o2_flow_meter2    VARCHAR(20),

    thickness                       FLOAT,          -- mm plate thickness
    cut_mm_mtr                      FLOAT,
    high_weld_cur_threshold         FLOAT,
    low_weld_cur_threshold          FLOAT
);
COMMENT ON TABLE gascutting.fact_periodic_gascutting IS
    'Real-time GasCutting1 sensor readings. '
    'position_x/y in mm (split from comma-string in source). '
    'lpg_flow=L/min, o2_flow=L/min, travel_in_mm=mm. '
    'lpg_below_detection=TRUE means meter resolution limit, not zero gas used.';

CREATE INDEX IF NOT EXISTS idx_pgc_date    ON gascutting.fact_periodic_gascutting(business_date);
CREATE INDEX IF NOT EXISTS idx_pgc_machine ON gascutting.fact_periodic_gascutting(machine_name);


-- ── 8. fact_summarize_gascutting ─────────────────────────────
CREATE TABLE IF NOT EXISTS gascutting.fact_summarize_gascutting (
    business_date               DATE,
    shift_name                  VARCHAR(10),
    machine_type                VARCHAR(20)     DEFAULT 'GASCUTTING',
    machine_name                VARCHAR(50),
    on_time                     TIMESTAMPTZ,
    off_time                    TIMESTAMPTZ,
    time_span                   VARCHAR(30),
    time_span_seconds           FLOAT,

    -- Quality flags
    timer_overflow              BOOLEAN,        -- exclude from time KPIs
    travel_outlier              BOOLEAN,        -- net_travel > 100,000mm
    no_cutting                  BOOLEAN,

    -- Cutting metrics
    net_travel_in_mm            FLOAT,          -- mm total torch travel
    mm_per_min                  FLOAT,          -- mm/min cutting speed
    speed_valid                 BOOLEAN,
    thickness                   FLOAT,          -- mm plate thickness
    thickness_recorded          BOOLEAN,
    cut_mm_mtr                  FLOAT,

    -- Gas
    net_lpg_consumption         FLOAT,          -- litres
    lpg_below_detection         BOOLEAN,
    net_o2_consumption_meter1   FLOAT,          -- litres
    net_o2_consumption_meter2   FLOAT,          -- litres
    total_o2_consumption        FLOAT           -- litres (meter1+meter2)
);
COMMENT ON TABLE gascutting.fact_summarize_gascutting IS
    'Per-cut summaries for GasCutting1. '
    'ALWAYS filter timer_overflow=FALSE AND travel_outlier=FALSE for valid KPIs. '
    'mm_per_min=mm/min, net_travel_in_mm=mm, thickness=mm, gas=litres.';

CREATE INDEX IF NOT EXISTS idx_sgc_date  ON gascutting.fact_summarize_gascutting(business_date);
CREATE INDEX IF NOT EXISTS idx_sgc_valid ON gascutting.fact_summarize_gascutting(timer_overflow, travel_outlier);


-- ── 9. fact_summarize_gascutting_noncutting ──────────────────
CREATE TABLE IF NOT EXISTS gascutting.fact_summarize_gascutting_noncutting (
    business_date               DATE,
    shift_name                  VARCHAR(10),
    machine_type                VARCHAR(20)     DEFAULT 'GASCUTTING',
    machine_name                VARCHAR(50),
    operation_category          VARCHAR(20)     DEFAULT 'non_cutting',
    on_time                     TIMESTAMPTZ,
    off_time                    TIMESTAMPTZ,
    time_span                   VARCHAR(30),
    time_span_seconds           FLOAT,

    is_instantaneous            BOOLEAN,
    timer_overflow              BOOLEAN,
    no_movement                 BOOLEAN,

    net_travel_in_mm            FLOAT,          -- mm
    mm_per_min                  FLOAT,          -- mm/min
    speed_unreliable            BOOLEAN,

    total_lpg_cons              FLOAT,          -- litres
    lpg_below_detection         BOOLEAN,
    total_heating_o2            FLOAT           -- litres O2 for preheating
);
COMMENT ON TABLE gascutting.fact_summarize_gascutting_noncutting IS
    'Non-cutting GasCutting1 ops: preheat, warmup, heating passes. '
    'Source was misnamed "nongascut_machine" — contains 100% GASCUTTING data. '
    '14,340 duplicates removed before load. speed_unreliable=TRUE for sub-5s events.';


-- =============================================================
-- SCHEMA: clad
-- =============================================================

-- ── 10. fact_summarize_clad ───────────────────────────────────
CREATE TABLE IF NOT EXISTS clad.fact_summarize_clad (
    business_date               DATE,
    shift_name                  VARCHAR(10),
    machine_type                VARCHAR(20)     DEFAULT 'CLAD',
    machine_name                VARCHAR(50),    -- Rectifier1 or Rectifier2
    oid                         VARCHAR(20),

    ontime                      TIMESTAMPTZ,
    offtime                     TIMESTAMPTZ,
    time_span                   VARCHAR(30),
    time_span_seconds           FLOAT,
    computed_duration_sec       FLOAT,

    is_instantaneous            BOOLEAN,        -- 8,341 rows=TRUE, exclude from KPIs

    avg_weld_cur                FLOAT,          -- Amperes (A)
    cur_range                   VARCHAR(15),    -- zero|low|normal|high|very_high
    avg_weld_volt               FLOAT,          -- Volts (V)
    volt_range                  VARCHAR(15),

    loss_weight                 FLOAT           -- grams cladding deposit (NULL=sensor error)
);
COMMENT ON TABLE clad.fact_summarize_clad IS
    'Per-arc-session summaries for CLAD Rectifier1 and Rectifier2. '
    'avg_weld_cur=A, avg_weld_volt=V, loss_weight=grams. '
    'is_instantaneous=TRUE for 8,341 rows (32%) — EXCLUDE from all efficiency KPIs. '
    'Rectifier2 has 7x more sessions than Rectifier1.';

CREATE INDEX IF NOT EXISTS idx_clad_date    ON clad.fact_summarize_clad(business_date);
CREATE INDEX IF NOT EXISTS idx_clad_machine ON clad.fact_summarize_clad(machine_name);
CREATE INDEX IF NOT EXISTS idx_clad_valid   ON clad.fact_summarize_clad(is_instantaneous);


-- =============================================================
-- ANALYTICS VIEWS (used by chatbot SQL generation)
-- =============================================================

-- V1: GMAW shift efficiency
CREATE OR REPLACE VIEW gmaw.v_gmaw_shift_efficiency AS
    SELECT
        d.business_date,
        d.shift_name,
        d.machine_name,
        d.active            AS active_minutes,
        d.idle              AS idle_minutes,
        d.breakdown         AS breakdown_minutes,
        d.arc_efficiency_pct,
        d.deposit,
        d.target_deposit,
        d.deposit_efficiency_pct
    FROM gmaw.fact_machine_derived_gmaw d
    WHERE d.machine_type = 'GMAW';

-- V2: GMAW sensor averages (idle excluded — CRITICAL)
CREATE OR REPLACE VIEW gmaw.v_gmaw_sensor_averages AS
    SELECT
        business_date,
        shift_name,
        machine_name,
        COUNT(*)                                            AS sample_count,
        ROUND(AVG(weld_cur)::NUMERIC, 2)                   AS avg_weld_cur_a,
        ROUND(AVG(weld_volt)::NUMERIC, 2)                  AS avg_weld_volt_v,
        ROUND(AVG(weld_gas)::NUMERIC, 2)                   AS avg_weld_gas_lmin,
        ROUND(AVG(hs_temp)::NUMERIC, 2)                    AS avg_hs_temp_c,
        ROUND(AVG(amb_temp)::NUMERIC, 2)                   AS avg_amb_temp_c,
        ROUND(AVG(rpm)::NUMERIC, 2)                        AS avg_rpm,
        SUM(CASE WHEN current_deviation_flag != 'none' THEN 1 ELSE 0 END)
                                                            AS current_deviation_events,
        SUM(CASE WHEN voltage_deviation_flag != 'none' THEN 1 ELSE 0 END)
                                                            AS voltage_deviation_events,
        SUM(CASE WHEN gas_deviation_flag     != 'none' THEN 1 ELSE 0 END)
                                                            AS gas_deviation_events
    FROM gmaw.fact_periodic_gmaw
    WHERE is_welding = TRUE             -- always exclude idle rows
    GROUP BY 1, 2, 3;

-- V3: Deviation frequency
CREATE OR REPLACE VIEW reference.v_deviation_summary AS
    SELECT
        machine_type,
        machine_name,
        parameter,
        parameter_unit,
        type                                                AS deviation_direction,
        deviation_label,
        COUNT(*)                                            AS event_count,
        ROUND(AVG(span_seconds)::NUMERIC, 1)               AS avg_duration_seconds,
        ROUND((SUM(span_seconds)/60)::NUMERIC, 1)          AS total_duration_minutes,
        MIN(start_tm)                                       AS first_occurrence,
        MAX(start_tm)                                       AS last_occurrence
    FROM gmaw.fact_deviation
    GROUP BY 1, 2, 3, 4, 5, 6;

-- V4: Gas cutting productivity (valid cuts only)
CREATE OR REPLACE VIEW gascutting.v_gascutting_productivity AS
    SELECT
        business_date,
        shift_name,
        machine_name,
        COUNT(*)                                            AS total_cuts,
        SUM(CASE WHEN thickness_recorded THEN 1 ELSE 0 END)
                                                            AS cuts_with_thickness,
        ROUND(AVG(CASE WHEN speed_valid AND NOT timer_overflow AND NOT travel_outlier
                        THEN mm_per_min END)::NUMERIC, 2)  AS avg_cut_speed_mm_per_min,
        ROUND(AVG(CASE WHEN thickness_recorded THEN thickness END)::NUMERIC, 2)
                                                            AS avg_thickness_mm,
        ROUND(SUM(CASE WHEN NOT timer_overflow AND NOT travel_outlier
                        THEN net_travel_in_mm / 1000.0 END)::NUMERIC, 2)
                                                            AS total_travel_metres,
        ROUND(SUM(CASE WHEN NOT lpg_below_detection
                        THEN net_lpg_consumption END)::NUMERIC, 2)
                                                            AS total_lpg_litres,
        ROUND(SUM(total_o2_consumption)::NUMERIC, 2)       AS total_o2_litres
    FROM gascutting.fact_summarize_gascutting
    WHERE timer_overflow = FALSE AND travel_outlier = FALSE
    GROUP BY 1, 2, 3;

-- V5: CLAD session summary (real sessions only)
CREATE OR REPLACE VIEW clad.v_clad_session_summary AS
    SELECT
        business_date,
        shift_name,
        machine_name,
        COUNT(*)                                            AS total_sessions,
        SUM(CASE WHEN NOT is_instantaneous THEN 1 ELSE 0 END)
                                                            AS valid_sessions,
        ROUND(AVG(CASE WHEN NOT is_instantaneous THEN avg_weld_cur END)::NUMERIC, 2)
                                                            AS avg_current_a,
        ROUND(AVG(CASE WHEN NOT is_instantaneous THEN avg_weld_volt END)::NUMERIC, 2)
                                                            AS avg_voltage_v,
        ROUND(SUM(CASE WHEN NOT is_instantaneous AND loss_weight IS NOT NULL
                        THEN loss_weight END)::NUMERIC, 2) AS total_loss_weight_grams,
        ROUND(SUM(CASE WHEN NOT is_instantaneous
                        THEN time_span_seconds / 60.0 END)::NUMERIC, 1)
                                                            AS total_arc_time_minutes
    FROM clad.fact_summarize_clad
    GROUP BY 1, 2, 3;
