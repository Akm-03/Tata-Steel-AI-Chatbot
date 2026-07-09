-- =============================================================
-- TATA STEEL ENTERPRISE CHATBOT — SNOWFLAKE SCHEMA
-- Phase 2B: Complete DDL
-- =============================================================
-- Database : TATA_STEEL_OPS
-- Schemas  : REFERENCE | GMAW | GASCUTTING | CLAD
-- Tables   : 12 total (3 dim + 9 fact)
-- All column comments include unit, machine type, and chatbot
-- response guidance so the AI layer always has full context.
-- =============================================================

-- ── 0. DATABASE & SCHEMAS ───────────────────────────────────
CREATE DATABASE IF NOT EXISTS TATA_STEEL_OPS
  COMMENT = 'Tata Steel operational machine data — enterprise chatbot backend';

USE DATABASE TATA_STEEL_OPS;

CREATE SCHEMA IF NOT EXISTS REFERENCE
  COMMENT = 'Dimension tables: machine types, machines, users';

CREATE SCHEMA IF NOT EXISTS GMAW
  COMMENT = 'GMAW (Gas Metal Arc Welding) machine data — 14 welding machines';

CREATE SCHEMA IF NOT EXISTS GASCUTTING
  COMMENT = 'Gas cutting machine data — GasCutting1 torch';

CREATE SCHEMA IF NOT EXISTS CLAD
  COMMENT = 'Cladding rectifier data — Rectifier1 and Rectifier2';


-- =============================================================
-- SCHEMA: REFERENCE
-- =============================================================

-- ── 1. DIM_MACHINE_TYPE ──────────────────────────────────────
USE SCHEMA REFERENCE;

CREATE OR REPLACE TABLE DIM_MACHINE_TYPE (
    MTID                TINYINT         NOT NULL,
    MACHINE_TYPE_NAME   VARCHAR(20)     NOT NULL,
    IS_ACTIVE           BOOLEAN         NOT NULL DEFAULT TRUE,
    CREATED_AT          TIMESTAMP_TZ,
    UPDATED_AT          TIMESTAMP_TZ,

    CONSTRAINT PK_MACHINE_TYPE PRIMARY KEY (MTID)
)
COMMENT = 'Master machine type lookup. 3 types: GMAW (1), CLAD (2), GASCUTTING (3). '
          'Chatbot: always resolve machine type from this table before answering '
          'any parameter question — parameters are type-specific.'
;

-- Seed data (3 rows — won't change)
INSERT INTO DIM_MACHINE_TYPE (MTID, MACHINE_TYPE_NAME, IS_ACTIVE, CREATED_AT, UPDATED_AT)
VALUES
    (1, 'GMAW',       TRUE, '2024-03-14 16:59:26.840 +05:30', '2024-03-14 16:59:26.840 +05:30'),
    (2, 'CLAD',       TRUE, '2024-03-14 16:59:36.864 +05:30', '2024-03-14 16:59:36.864 +05:30'),
    (3, 'GASCUTTING', TRUE, '2024-03-14 16:59:54.673 +05:30', '2024-03-14 16:59:54.673 +05:30')
;


-- ── 2. DIM_MACHINES ──────────────────────────────────────────
CREATE OR REPLACE TABLE DIM_MACHINES (
    MID                         SMALLINT        NOT NULL,
    NAME                        VARCHAR(50)     NOT NULL,
    HARDWARE_ID                 VARCHAR(20)     NOT NULL,
    DES                         VARCHAR(100),
    MTID                        TINYINT         NOT NULL,
    MACHINE_TYPE_NAME           VARCHAR(20)     NOT NULL,
    -- Type flags for fast filtering without joins
    IS_GMAW                     BOOLEAN         NOT NULL DEFAULT FALSE,
    IS_CLAD                     BOOLEAN         NOT NULL DEFAULT FALSE,
    IS_GASCUTTING               BOOLEAN         NOT NULL DEFAULT FALSE,
    MSID                        INT,
    HID                         INT,
    ORGID                       INT,
    MCSID                       INT,
    MCID                        INT,
    RPM_MULTIPLICATION_FACTOR   FLOAT,
    NOTIFY                      BOOLEAN,
    DELETED                     BOOLEAN         NOT NULL DEFAULT FALSE,
    CREATED_AT                  TIMESTAMP_TZ,
    UPDATED_AT                  TIMESTAMP_TZ,

    CONSTRAINT PK_MACHINES          PRIMARY KEY (MID),
    CONSTRAINT UQ_MACHINES_HW_ID    UNIQUE      (HARDWARE_ID),
    CONSTRAINT FK_MACHINES_TYPE     FOREIGN KEY (MTID)
        REFERENCES DIM_MACHINE_TYPE (MTID)
)
COMMENT = '17 registered machines. GMAW×14, CLAD×2 (Rectifier1/2), GASCUTTING×1. '
          'IS_GMAW/IS_CLAD/IS_GASCUTTING flags are used by chatbot guardrails to '
          'scope parameter queries to the correct machine type. '
          'Join on HARDWARE_ID to link real-time sensor data.'
;


-- ── 3. DIM_USERS ─────────────────────────────────────────────
CREATE OR REPLACE TABLE DIM_USERS (
    UID                 INT             NOT NULL,
    NAME                VARCHAR(100)    NOT NULL,
    EMAIL               VARCHAR(150),
    IS_TATA_EMAIL       BOOLEAN,
    PHNO                BIGINT,
    ROLEID              TINYINT,
    ROLE_NAME           VARCHAR(30),
    HID                 INT,
    ORGID               INT,
    CERTIFICATE_ID      VARCHAR(50),
    IDENTIFICATION_NO   VARCHAR(50),
    OPERATOR_RFID       VARCHAR(50),
    USERNAME            VARCHAR(100),
    DELETED             BOOLEAN         NOT NULL DEFAULT FALSE,
    ACTIVE_STATUS       BOOLEAN         NOT NULL DEFAULT FALSE,
    IS_TEST_ACCOUNT     BOOLEAN         NOT NULL DEFAULT FALSE,
    CREATED_AT          TIMESTAMP_TZ,
    UPDATED_AT          TIMESTAMP_TZ,

    CONSTRAINT PK_USERS PRIMARY KEY (UID)
)
COMMENT = 'Operator and staff user registry. '
          'SECURITY: password, session tokens, and CSRF tokens are EXCLUDED — '
          'never present in this analytics table. '
          'ROLE_NAME: Staff/Engineer=1, Operator=3, Admin/Manager=4. '
          'Chatbot: use only rows where DELETED=FALSE and IS_TEST_ACCOUNT=FALSE '
          'when answering "who is on shift" or "active operators" queries.'
;

-- NOTE: Load only from dim_users.csv (not dim_users_deleted.csv / dim_users_test.csv)
-- Those are audit files kept separately.


-- =============================================================
-- SCHEMA: GMAW
-- =============================================================
USE SCHEMA GMAW;


-- ── 4. FACT_DEVIATION ────────────────────────────────────────
-- Shared between GMAW and CLAD machines; partitioned by MACHINE_TYPE
CREATE OR REPLACE TABLE FACT_DEVIATION (
    HARDWARE_ID         VARCHAR(20)     NOT NULL,
    MID                 SMALLINT,
    MACHINE_NAME        VARCHAR(50),
    MACHINE_TYPE        VARCHAR(20),
    OID                 VARCHAR(20),
    SHID                VARCHAR(20),
    START_TM            TIMESTAMP_TZ,
    END_TM              TIMESTAMP_TZ,
    SPAN_SECONDS        FLOAT,
    SPAN_RAW            FLOAT,
    TYPE                VARCHAR(10),
    PARAMETER           VARCHAR(30),
    DEVIATION_LABEL     VARCHAR(60),
    PARAMETER_UNIT      VARCHAR(10),
    IS_GMAW             BOOLEAN,
    IS_CLAD             BOOLEAN,

    CONSTRAINT FK_DEV_MACHINE FOREIGN KEY (MID)
        REFERENCES REFERENCE.DIM_MACHINES (MID)
)
CLUSTER BY (MACHINE_TYPE, START_TM)
COMMENT = 'Out-of-threshold deviation events for GMAW and CLAD machines. '
          'PARAMETER values: weld_cur (A), weld_volt (V), weld_gas (L/min), '
          'hs_temp (°C), amb_temp (°C). '
          'TYPE: high = above upper threshold, low = below lower threshold. '
          'SPAN_SECONDS: duration of deviation in seconds (range 5–385s). '
          'DEVIATION_LABEL: e.g. weld_cur_high, weld_volt_low — use in chatbot '
          'responses: "X deviation events where weld current exceeded threshold". '
          'NOTE: 373 rows from unregistered device EC6260723F44 are in a '
          'separate quarantine file — not loaded here.'
;

-- Alias view for CLAD-only deviation queries
CREATE OR REPLACE VIEW FACT_DEVIATION_CLAD AS
    SELECT * FROM FACT_DEVIATION WHERE MACHINE_TYPE = 'CLAD';

-- Alias view for GMAW-only
CREATE OR REPLACE VIEW FACT_DEVIATION_GMAW AS
    SELECT * FROM FACT_DEVIATION WHERE MACHINE_TYPE = 'GMAW';


-- ── 5. FACT_PERIODIC_GMAW ────────────────────────────────────
CREATE OR REPLACE TABLE FACT_PERIODIC_GMAW (
    -- Identity & time
    PDID                        VARCHAR(50),
    BUSINESS_DATE               DATE,
    SHIFT_NAME                  VARCHAR(10),
    MACHINE_TYPE                VARCHAR(20)     NOT NULL DEFAULT 'GMAW',
    MACHINE_NAME                VARCHAR(50),
    HARDWARE_ID                 VARCHAR(20),
    JOB_NAME                    VARCHAR(100),
    TM                          TIMESTAMP_TZ,

    -- Weld parameters (all GMAW-specific)
    WELD_CUR                    FLOAT,          -- Unit: Amperes (A). 0 = idle. Normal range 80–270A
    WELD_VOLT                   FLOAT,          -- Unit: Volts (V). Normal range 20–30V
    WELD_GAS                    FLOAT,          -- Unit: L/min (shielding gas). Normal 20–30 L/min
    HS_TEMP                     FLOAT,          -- Unit: °C (heatsink temperature)
    AMB_TEMP                    FLOAT,          -- Unit: °C (shop floor ambient temperature)
    RPM                         FLOAT,          -- Unit: RPM (wire feed motor speed)

    -- State flags
    IS_IDLE                     BOOLEAN,        -- TRUE when weld_cur=0 or mstatus=stop
    IS_WELDING                  BOOLEAN,        -- TRUE when actively welding (not idle)
    MSTATUS                     VARCHAR(20),    -- Machine status string: active/stop

    -- Deviation flags (encoded)
    CURRENT_DEVIATION_FLAG      VARCHAR(15),    -- none | single | sustained
    VOLTAGE_DEVIATION_FLAG      VARCHAR(15),    -- none | single | sustained
    GAS_DEVIATION_FLAG          VARCHAR(15),    -- none | single | sustained

    -- Network & operator
    NETWORK                     FLOAT,          -- Unit: dBm (WiFi RSSI, e.g. -71 to -75)
    OID                         VARCHAR(20),

    -- Thresholds (set per machine)
    HIGH_WELD_CUR_THRESHOLD     FLOAT,          -- Unit: A
    LOW_WELD_CUR_THRESHOLD      FLOAT,          -- Unit: A
    HIGH_WELD_VOLT_THRESHOLD    FLOAT,          -- Unit: V
    LOW_WELD_VOLT_THRESHOLD     FLOAT,          -- Unit: V
    HIGH_WELD_GAS_THRESHOLD     FLOAT,          -- Unit: L/min
    LOW_WELD_GAS_THRESHOLD      FLOAT,          -- Unit: L/min

    -- Misc
    THICKNESS                   FLOAT,          -- Unit: mm (plate thickness if recorded)
    CUT_MM_MTR                  FLOAT,
    TYPE                        VARCHAR(20)
)
CLUSTER BY (MACHINE_NAME, BUSINESS_DATE)
COMMENT = 'Real-time periodic sensor readings for GMAW welding machines. '
          'One row per machine per sampling interval (~30s). '
          'KEY RULE: Always filter IS_IDLE=FALSE when computing weld averages — '
          'idle rows have WELD_CUR=0 and will skew current/voltage averages. '
          'Deviation flags: none=no threshold breach, single=one-time, sustained=prolonged. '
          'WELD_CUR unit=A, WELD_VOLT unit=V, WELD_GAS unit=L/min, '
          'HS_TEMP/AMB_TEMP unit=°C, RPM unit=RPM, NETWORK unit=dBm.'
;


-- ── 6. FACT_MACHINE_DERIVED_GMAW ────────────────────────────
CREATE OR REPLACE TABLE FACT_MACHINE_DERIVED_GMAW (
    BUSINESS_DATE               DATE,
    SHIFT_NAME                  VARCHAR(10),
    MACHINE_TYPE                VARCHAR(20)     NOT NULL DEFAULT 'GMAW',
    MACHINE_NAME                VARCHAR(50),
    OID                         VARCHAR(20),
    PERIOD_START_TIME           VARCHAR(30),
    PERIOD_END_TIME             VARCHAR(30),

    -- Time allocation (all in MINUTES)
    ACTIVE                      FLOAT,          -- Unit: minutes — actual arc-on time
    IDLE                        FLOAT,          -- Unit: minutes — powered but not welding
    INREPAIR                    FLOAT,          -- Unit: minutes — scheduled maintenance
    BREAKDOWN                   FLOAT,          -- Unit: minutes — unplanned downtime
    TARGET_ARC_TIME             FLOAT,          -- Unit: minutes — planned arc time for shift

    -- Weight / deposit
    DEPOSIT                     FLOAT,          -- Unit: grams — actual weld deposit
    TARGET_DEPOSIT              FLOAT,          -- Unit: grams — planned deposit

    -- Unknown columns (pending domain expert clarification)
    UNKNOWN_A                   FLOAT,
    UNKNOWN_B                   FLOAT,
    UNKNOWN_C                   FLOAT,

    -- Computed KPIs (added during cleaning)
    MID                         SMALLINT,
    MACHINE_TYPE_VERIFIED       VARCHAR(20),
    TOTAL_ACCOUNTED_MINUTES     FLOAT,
    TIME_ALLOCATION_VALID       BOOLEAN,
    ARC_EFFICIENCY_PCT          FLOAT,          -- Unit: % = (active/target_arc_time)*100
    DEPOSIT_EFFICIENCY_PCT      FLOAT,          -- Unit: % = (deposit/target_deposit)*100

    CONSTRAINT FK_MD_MACHINE FOREIGN KEY (MID)
        REFERENCES REFERENCE.DIM_MACHINES (MID)
)
COMMENT = 'Per-shift aggregated KPIs for GMAW machines. One row per machine per shift period. '
          'ARC_EFFICIENCY_PCT = active / target_arc_time × 100. Unit: %. '
          'DEPOSIT_EFFICIENCY_PCT = deposit / target_deposit × 100. Unit: %. '
          'TIME cols (ACTIVE/IDLE/INREPAIR/BREAKDOWN) all in MINUTES. '
          'DEPOSIT/TARGET_DEPOSIT in GRAMS. '
          'Chatbot: when asked "which shift was most efficient" → use ARC_EFFICIENCY_PCT, '
          'always state machine name and shift name in response.'
;


-- =============================================================
-- SCHEMA: GASCUTTING
-- =============================================================
USE SCHEMA GASCUTTING;


-- ── 7. FACT_PERIODIC_GASCUTTING ─────────────────────────────
CREATE OR REPLACE TABLE FACT_PERIODIC_GASCUTTING (
    -- Identity & time
    PDID                            VARCHAR(50),
    BUSINESS_DATE                   DATE,
    SHIFT_NAME                      VARCHAR(10),
    MACHINE_TYPE                    VARCHAR(20)     NOT NULL DEFAULT 'GASCUTTING',
    MACHINE_NAME                    VARCHAR(50),
    HARDWARE_ID                     VARCHAR(20),
    JOB_NAME                        VARCHAR(100),
    TM                              TIMESTAMP_TZ,
    MSTATUS                         VARCHAR(20),

    -- Gas parameters
    LPG_FLOW                        FLOAT,          -- Unit: L/min (fuel gas flow rate)
    O2_FLOW_METER1                  FLOAT,          -- Unit: L/min (oxygen assist, meter 1)
    O2_FLOW_METER2                  FLOAT,          -- Unit: L/min (oxygen assist, meter 2)
    TOTAL_LPG_CONSUMPTION           FLOAT,          -- Unit: litres (cumulative)
    TOTAL_O2_CONSUMPTION_METER1     FLOAT,          -- Unit: litres (cumulative)
    TOTAL_O2_CONSUMPTION_METER2     FLOAT,          -- Unit: litres (cumulative)

    -- Torch position (split from "X,Y" string in source)
    TRAVEL_IN_MM                    FLOAT,          -- Unit: mm (torch travel distance)
    POSITION_X                      FLOAT,          -- Unit: mm (X coordinate on cutting table)
    POSITION_Y                      FLOAT,          -- Unit: mm (Y coordinate on cutting table)

    -- State flags
    IS_CUTTING                      BOOLEAN,        -- TRUE when mstatus != stop
    LPG_BELOW_DETECTION             BOOLEAN,        -- TRUE when lpg_flow=0 (below meter resolution)

    -- Health status (sensor strings)
    HEALTH_STATUS_LPG_FLOW_METER    VARCHAR(20),
    HEALTH_STATUS_O2_FLOW_METER1    VARCHAR(20),
    HEALTH_STATUS_O2_FLOW_METER2    VARCHAR(20),

    -- Plate info
    THICKNESS                       FLOAT,          -- Unit: mm (plate thickness)
    CUT_MM_MTR                      FLOAT,

    -- Thresholds
    HIGH_WELD_CUR_THRESHOLD         FLOAT,
    LOW_WELD_CUR_THRESHOLD          FLOAT
)
CLUSTER BY (MACHINE_NAME, BUSINESS_DATE)
COMMENT = 'Real-time periodic sensor readings for GasCutting1 machine. '
          'POSITION_X/Y: torch XY coordinates in mm on the cutting table — split from "X,Y" string. '
          'LPG_FLOW unit=L/min; O2_FLOW unit=L/min; TRAVEL_IN_MM unit=mm. '
          'LPG_BELOW_DETECTION=TRUE means the reading is 0 due to meter resolution limits, '
          'NOT that no gas was used — always note this in chatbot responses. '
          'IS_CUTTING=FALSE means torch is idle (mstatus=stop).'
;


-- ── 8. FACT_SUMMARIZE_GASCUTTING ────────────────────────────
CREATE OR REPLACE TABLE FACT_SUMMARIZE_GASCUTTING (
    -- Identity & time
    BUSINESS_DATE               DATE,
    SHIFT_NAME                  VARCHAR(10),
    MACHINE_TYPE                VARCHAR(20)     NOT NULL DEFAULT 'GASCUTTING',
    MACHINE_NAME                VARCHAR(50),
    ON_TIME                     TIMESTAMP_TZ,
    OFF_TIME                    TIMESTAMP_TZ,
    TIME_SPAN                   VARCHAR(30),
    TIME_SPAN_SECONDS           FLOAT,          -- NULL when timer_overflow=TRUE

    -- Quality flags
    TIMER_OVERFLOW              BOOLEAN,        -- TRUE = multi-day span, exclude from KPIs
    TRAVEL_OUTLIER              BOOLEAN,        -- TRUE = net_travel > 100,000mm
    NO_CUTTING                  BOOLEAN,        -- TRUE = net_travel = 0

    -- Cutting metrics
    NET_TRAVEL_IN_MM            FLOAT,          -- Unit: mm (total torch travel for this cut)
    MM_PER_MIN                  FLOAT,          -- Unit: mm/min (cutting speed)
    SPEED_VALID                 BOOLEAN,        -- FALSE if speed is unreliable (overflow/outlier)
    THICKNESS                   FLOAT,          -- Unit: mm (plate thickness)
    THICKNESS_RECORDED          BOOLEAN,        -- FALSE if thickness was not entered
    CUT_MM_MTR                  FLOAT,          -- Unit: mm/m (material-specific cut rate)

    -- Gas consumption
    NET_LPG_CONSUMPTION         FLOAT,          -- Unit: litres (cumulative LPG used)
    LPG_BELOW_DETECTION         BOOLEAN,        -- TRUE = 0 value means below meter limit
    NET_O2_CONSUMPTION_METER1   FLOAT,          -- Unit: litres
    NET_O2_CONSUMPTION_METER2   FLOAT,          -- Unit: litres
    TOTAL_O2_CONSUMPTION        FLOAT           -- Unit: litres (meter1 + meter2)
)
CLUSTER BY (MACHINE_NAME, BUSINESS_DATE)
COMMENT = 'Per-cut job summaries for GasCutting1. One row per torch-on/torch-off cycle. '
          'ALWAYS filter TIMER_OVERFLOW=FALSE AND TRAVEL_OUTLIER=FALSE for valid KPIs. '
          'MM_PER_MIN unit=mm/min (cutting speed). NET_TRAVEL_IN_MM unit=mm. '
          'THICKNESS unit=mm. GAS units=litres. '
          'LPG_BELOW_DETECTION: if TRUE, LPG=0 does not mean zero consumption — '
          'chatbot must always clarify this when LPG figures are cited. '
          '14,470 rows (33.5%) have no thickness recorded — note in responses.'
;


-- ── 9. FACT_SUMMARIZE_GASCUTTING_NONCUTTING ─────────────────
CREATE OR REPLACE TABLE FACT_SUMMARIZE_GASCUTTING_NONCUTTING (
    -- Identity & time
    BUSINESS_DATE               DATE,
    SHIFT_NAME                  VARCHAR(10),
    MACHINE_TYPE                VARCHAR(20)     NOT NULL DEFAULT 'GASCUTTING',
    MACHINE_NAME                VARCHAR(50),
    OPERATION_CATEGORY          VARCHAR(20)     NOT NULL DEFAULT 'non_cutting',
    ON_TIME                     TIMESTAMP_TZ,
    OFF_TIME                    TIMESTAMP_TZ,
    TIME_SPAN                   VARCHAR(30),
    TIME_SPAN_SECONDS           FLOAT,

    -- Quality flags
    IS_INSTANTANEOUS            BOOLEAN,        -- TRUE = time_span=00:00:00, exclude from KPIs
    TIMER_OVERFLOW              BOOLEAN,
    NO_MOVEMENT                 BOOLEAN,        -- TRUE = net_travel=0 (stationary heating)

    -- Movement
    NET_TRAVEL_IN_MM            FLOAT,          -- Unit: mm
    MM_PER_MIN                  FLOAT,          -- Unit: mm/min
    SPEED_UNRELIABLE            BOOLEAN,        -- TRUE = speed computed from <5s event

    -- Gas
    TOTAL_LPG_CONS              FLOAT,          -- Unit: litres
    LPG_BELOW_DETECTION         BOOLEAN,
    TOTAL_HEATING_O2            FLOAT           -- Unit: litres (O2 used for preheating)
)
CLUSTER BY (MACHINE_NAME, BUSINESS_DATE)
COMMENT = 'Non-cutting operations of GasCutting1: preheating, torch warmup, heating passes. '
          'TABLE WAS MISNAMED "nongascut_machine" in source — contains 100% GASCUTTING data. '
          'OPERATION_CATEGORY=non_cutting distinguishes from FACT_SUMMARIZE_GASCUTTING. '
          'SPEED_UNRELIABLE=TRUE for 189 rows — caused by sub-5-second measurement windows. '
          'TOTAL_HEATING_O2 unit=litres (oxygen used for preheat, not plate cutting). '
          '14,340 duplicate rows were removed (32.7% of source) before load.'
;


-- =============================================================
-- SCHEMA: CLAD
-- =============================================================
USE SCHEMA CLAD;


-- ── 10. FACT_SUMMARIZE_CLAD ──────────────────────────────────
CREATE OR REPLACE TABLE FACT_SUMMARIZE_CLAD (
    -- Identity & time
    BUSINESS_DATE               DATE,
    SHIFT_NAME                  VARCHAR(10),
    MACHINE_TYPE                VARCHAR(20)     NOT NULL DEFAULT 'CLAD',
    MACHINE_NAME                VARCHAR(50),    -- Rectifier1 or Rectifier2
    OID                         VARCHAR(20),

    -- Session timestamps
    ONTIME                      TIMESTAMP_TZ,
    OFFTIME                     TIMESTAMP_TZ,
    TIME_SPAN                   VARCHAR(30),
    TIME_SPAN_SECONDS           FLOAT,
    COMPUTED_DURATION_SEC       FLOAT,          -- Cross-check: offtime - ontime

    -- Quality flags
    IS_INSTANTANEOUS            BOOLEAN,        -- TRUE = time_span=00:00:00, exclude from KPIs
                                                -- 8,341 rows (32%) affected

    -- Electrical measurements
    AVG_WELD_CUR                FLOAT,          -- Unit: Amperes (A). CLAD range: 100–500A typical
    CUR_RANGE                   VARCHAR(15),    -- zero|low(<100A)|normal(100-300A)|high(300-500A)|very_high(>500A)
    AVG_WELD_VOLT               FLOAT,          -- Unit: Volts (V)
    VOLT_RANGE                  VARCHAR(15),    -- zero|low|normal|high|very_high

    -- Weight
    LOSS_WEIGHT                 FLOAT           -- Unit: grams (g). Cladding material deposited.
                                                -- NULL where original value was negative
                                                -- (87 rows — sensor calibration error)

    -- NOTE: on_cur, off_cur, on_volt, off_volt, on_weight, off_weight
    -- were DROPPED — all NULL in source (sensor readings not captured at session boundaries)
)
CLUSTER BY (MACHINE_NAME, BUSINESS_DATE)
COMMENT = 'Per-arc-session summaries for CLAD rectifiers (Rectifier1 and Rectifier2). '
          'AVG_WELD_CUR unit=A; AVG_WELD_VOLT unit=V; LOSS_WEIGHT unit=grams. '
          'IS_INSTANTANEOUS=TRUE for 8,341 rows (32%) — exclude from all efficiency KPIs. '
          'CUR_RANGE: very_high (>500A) has 271 rows — flagged for domain expert verification. '
          'Rectifier2 has 7x more sessions than Rectifier1 (22,704 vs 3,231). '
          'Chatbot: always specify "CLAD machine (Rectifier1/2)" in responses. '
          'LOSS_WEIGHT=NULL means either no deposit or sensor error (87 rows).'
;


-- =============================================================
-- CROSS-SCHEMA ANALYTICS VIEWS
-- (Used by chatbot SQL generation layer)
-- =============================================================
USE SCHEMA REFERENCE;

-- ── V1: Machine efficiency summary (GMAW) ───────────────────
CREATE OR REPLACE VIEW V_GMAW_SHIFT_EFFICIENCY AS
    SELECT
        d.BUSINESS_DATE,
        d.SHIFT_NAME,
        d.MACHINE_NAME,
        d.ACTIVE                                AS active_minutes,
        d.IDLE                                  AS idle_minutes,
        d.BREAKDOWN                             AS breakdown_minutes,
        d.ARC_EFFICIENCY_PCT,
        d.DEPOSIT,
        d.TARGET_DEPOSIT,
        d.DEPOSIT_EFFICIENCY_PCT,
        m.HARDWARE_ID
    FROM GMAW.FACT_MACHINE_DERIVED_GMAW d
    LEFT JOIN REFERENCE.DIM_MACHINES m ON d.MID = m.MID
    WHERE d.MACHINE_TYPE = 'GMAW'
;

-- ── V2: GMAW active-welding sensor averages (idle excluded) ──
CREATE OR REPLACE VIEW V_GMAW_SENSOR_AVERAGES AS
    SELECT
        BUSINESS_DATE,
        SHIFT_NAME,
        MACHINE_NAME,
        COUNT(*)                                AS sample_count,
        ROUND(AVG(WELD_CUR), 2)                AS avg_weld_cur_a,
        ROUND(AVG(WELD_VOLT), 2)               AS avg_weld_volt_v,
        ROUND(AVG(WELD_GAS), 2)                AS avg_weld_gas_lmin,
        ROUND(AVG(HS_TEMP), 2)                 AS avg_hs_temp_c,
        ROUND(AVG(AMB_TEMP), 2)                AS avg_amb_temp_c,
        ROUND(AVG(RPM), 2)                     AS avg_rpm,
        SUM(CASE WHEN CURRENT_DEVIATION_FLAG != 'none' THEN 1 ELSE 0 END)
                                                AS current_deviation_events,
        SUM(CASE WHEN VOLTAGE_DEVIATION_FLAG != 'none' THEN 1 ELSE 0 END)
                                                AS voltage_deviation_events,
        SUM(CASE WHEN GAS_DEVIATION_FLAG     != 'none' THEN 1 ELSE 0 END)
                                                AS gas_deviation_events
    FROM GMAW.FACT_PERIODIC_GMAW
    WHERE IS_WELDING = TRUE          -- CRITICAL: always exclude idle rows
    GROUP BY 1, 2, 3
;

-- ── V3: Deviation frequency by machine and parameter ─────────
CREATE OR REPLACE VIEW V_DEVIATION_SUMMARY AS
    SELECT
        MACHINE_TYPE,
        MACHINE_NAME,
        PARAMETER,
        PARAMETER_UNIT,
        TYPE                                    AS deviation_direction,
        DEVIATION_LABEL,
        COUNT(*)                                AS event_count,
        ROUND(AVG(SPAN_SECONDS), 1)            AS avg_duration_seconds,
        ROUND(SUM(SPAN_SECONDS) / 60, 1)      AS total_duration_minutes,
        MIN(START_TM)                           AS first_occurrence,
        MAX(START_TM)                           AS last_occurrence
    FROM GMAW.FACT_DEVIATION
    GROUP BY 1, 2, 3, 4, 5, 6
;

-- ── V4: Gas cutting productivity (valid cuts only) ───────────
CREATE OR REPLACE VIEW V_GASCUTTING_PRODUCTIVITY AS
    SELECT
        BUSINESS_DATE,
        SHIFT_NAME,
        MACHINE_NAME,
        COUNT(*)                                AS total_cuts,
        SUM(CASE WHEN THICKNESS_RECORDED THEN 1 ELSE 0 END)
                                                AS cuts_with_thickness,
        ROUND(AVG(CASE WHEN SPEED_VALID AND NOT TIMER_OVERFLOW AND NOT TRAVEL_OUTLIER
                        THEN MM_PER_MIN END), 2)
                                                AS avg_cut_speed_mm_per_min,
        ROUND(AVG(CASE WHEN THICKNESS_RECORDED THEN THICKNESS END), 2)
                                                AS avg_thickness_mm,
        ROUND(SUM(CASE WHEN NOT TIMER_OVERFLOW AND NOT TRAVEL_OUTLIER
                        THEN NET_TRAVEL_IN_MM / 1000 END), 2)
                                                AS total_travel_metres,
        ROUND(SUM(CASE WHEN NOT LPG_BELOW_DETECTION THEN NET_LPG_CONSUMPTION END), 2)
                                                AS total_lpg_litres,
        ROUND(SUM(TOTAL_O2_CONSUMPTION), 2)    AS total_o2_litres
    FROM GASCUTTING.FACT_SUMMARIZE_GASCUTTING
    WHERE TIMER_OVERFLOW = FALSE
      AND TRAVEL_OUTLIER = FALSE
    GROUP BY 1, 2, 3
;

-- ── V5: CLAD rectifier session summary (real sessions only) ──
CREATE OR REPLACE VIEW V_CLAD_SESSION_SUMMARY AS
    SELECT
        BUSINESS_DATE,
        SHIFT_NAME,
        MACHINE_NAME,
        COUNT(*)                                AS total_sessions,
        SUM(CASE WHEN NOT IS_INSTANTANEOUS THEN 1 ELSE 0 END)
                                                AS valid_sessions,
        ROUND(AVG(CASE WHEN NOT IS_INSTANTANEOUS THEN AVG_WELD_CUR END), 2)
                                                AS avg_current_a,
        ROUND(AVG(CASE WHEN NOT IS_INSTANTANEOUS THEN AVG_WELD_VOLT END), 2)
                                                AS avg_voltage_v,
        ROUND(SUM(CASE WHEN NOT IS_INSTANTANEOUS AND LOSS_WEIGHT IS NOT NULL
                        THEN LOSS_WEIGHT END), 2)
                                                AS total_loss_weight_grams,
        ROUND(SUM(CASE WHEN NOT IS_INSTANTANEOUS
                        THEN TIME_SPAN_SECONDS / 60 END), 1)
                                                AS total_arc_time_minutes
    FROM CLAD.FACT_SUMMARIZE_CLAD
    GROUP BY 1, 2, 3
;


-- =============================================================
-- FILE FORMAT for CSV COPY INTO
-- =============================================================
USE DATABASE TATA_STEEL_OPS;
USE SCHEMA REFERENCE;

CREATE OR REPLACE FILE FORMAT TATA_CSV_FORMAT
    TYPE = 'CSV'
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    SKIP_HEADER = 1
    NULL_IF = ('', 'None', 'NaN', 'nan', 'NULL', 'null')
    EMPTY_FIELD_AS_NULL = TRUE
    DATE_FORMAT = 'AUTO'
    TIMESTAMP_FORMAT = 'AUTO'
    TIMEZONE = 'Asia/Kolkata'
    COMMENT = 'Standard format for all Tata Steel cleaned CSV imports'
;
