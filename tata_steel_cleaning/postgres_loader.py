"""
postgres_loader.py
==================
Loads all 10 cleaned CSV files into PostgreSQL in the correct order.
Handles type coercion, null values, and gives a full load report.

Requirements:
    pip install psycopg2-binary pandas python-dotenv

Usage:
    # First create a .env file with your DB credentials (see bottom of file)
    python postgres_loader.py

    # Or pass connection string directly:
    python postgres_loader.py --dsn "postgresql://user:pass@localhost:5432/tata_steel_ops"

    # To reload a single table:
    python postgres_loader.py --table fact_periodic_gmaw
"""

import os
import sys
import argparse
import time
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from io import StringIO
from dotenv import load_dotenv

load_dotenv()

# ── Connection ──────────────────────────────────────────────────────────────
def get_connection(dsn=None):
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        host     = os.getenv("PG_HOST",     "localhost"),
        port     = os.getenv("PG_PORT",     "5432"),
        dbname   = os.getenv("PG_DATABASE", "tata_steel_ops"),
        user     = os.getenv("PG_USER",     "postgres"),
        password = os.getenv("PG_PASSWORD", ""),
    )

# ── Load order: dim tables first, then fact tables ──────────────────────────
# Each entry: (csv_filename, schema.table, truncate_before_load)
LOAD_PLAN = [
    # Reference / dimension tables
    ("dim_machine_type.csv",
     "reference.dim_machine_type",
     True),

    ("dim_machines.csv",
     "reference.dim_machines",
     True),

    ("dim_users.csv",
     "reference.dim_users",
     True),

    # GMAW facts
    ("fact_deviation.csv",
     "gmaw.fact_deviation",
     True),

    ("fact_machine_derived_gmaw.csv",
     "gmaw.fact_machine_derived_gmaw",
     True),

    ("fact_periodic_gmaw.csv",
     "gmaw.fact_periodic_gmaw",
     True),

    # CLAD facts
    ("fact_summarize_clad.csv",
     "clad.fact_summarize_clad",
     True),

    # GASCUTTING facts
    ("fact_periodic_gascutting.csv",
     "gascutting.fact_periodic_gascutting",
     True),

    ("fact_summarize_gascutting.csv",
     "gascutting.fact_summarize_gascutting",
     True),

    ("fact_summarize_gascutting_noncutting.csv",
     "gascutting.fact_summarize_gascutting_noncutting",
     True),
]

# Null strings from the cleaning pipeline
NULL_VALUES = {"", "None", "NaN", "nan", "NULL", "null", "<NA>"}

# Boolean columns per table (these need conversion from True/False strings)
BOOLEAN_COLS = {
    "reference.dim_machine_type":   ["is_active"],
    "reference.dim_machines":       ["is_gmaw", "is_clad", "is_gascutting", "notify", "deleted"],
    "reference.dim_users":          ["is_tata_email", "deleted", "active_status", "is_test_account"],
    "gmaw.fact_deviation":          ["is_gmaw", "is_clad"],
    "gmaw.fact_periodic_gmaw":      ["is_idle", "is_welding"],
    "gmaw.fact_machine_derived_gmaw": ["time_allocation_valid"],
    "gascutting.fact_periodic_gascutting": ["is_cutting", "lpg_below_detection"],
    "gascutting.fact_summarize_gascutting": [
        "timer_overflow", "travel_outlier", "no_cutting",
        "speed_valid", "thickness_recorded", "lpg_below_detection"
    ],
    "gascutting.fact_summarize_gascutting_noncutting": [
        "is_instantaneous", "timer_overflow", "no_movement",
        "speed_unreliable", "lpg_below_detection"
    ],
    "clad.fact_summarize_clad":     ["is_instantaneous"],
}


def coerce_booleans(df, table_name):
    """Convert True/False string columns to Python bools."""
    bool_cols = BOOLEAN_COLS.get(table_name, [])
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].map(
                {"True": True, "False": False, "true": True, "false": False,
                 True: True, False: False}
            )
    return df


def coerce_nulls(df):
    """Replace null-string values with actual NaN."""
    return df.replace(list(NULL_VALUES), pd.NA)


def df_to_postgres(conn, df, table_name, chunk_size=5000):
    """
    Fast bulk insert using COPY from StringIO buffer.
    Falls back to execute_values if COPY fails.
    """
    cur = conn.cursor()

    # Use PostgreSQL COPY for maximum speed
    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)

    try:
        cur.copy_expert(
            f"COPY {table_name} FROM STDIN WITH CSV NULL '\\N'",
            buffer
        )
        conn.commit()
        return len(df), 0  # rows_loaded, errors
    except Exception as e:
        conn.rollback()
        print(f"    COPY failed ({e}), falling back to execute_values...")

        # Fallback: chunked execute_values
        cols   = list(df.columns)
        col_str = ", ".join(cols)
        placeholders = f"INSERT INTO {table_name} ({col_str}) VALUES %s ON CONFLICT DO NOTHING"
        errors = 0
        loaded = 0

        for i in range(0, len(df), chunk_size):
            chunk = df.iloc[i:i+chunk_size]
            rows  = [tuple(None if pd.isna(v) else v for v in row)
                     for row in chunk.itertuples(index=False)]
            try:
                execute_values(cur, placeholders, rows)
                conn.commit()
                loaded += len(rows)
            except Exception as chunk_err:
                conn.rollback()
                print(f"    Chunk {i//chunk_size} failed: {chunk_err}")
                errors += len(rows)

        cur.close()
        return loaded, errors


def load_table(conn, csv_path, table_name, truncate=True):
    """Load one CSV file into one table. Returns result dict."""
    start = time.time()
    print(f"\n  Loading {os.path.basename(csv_path)}")
    print(f"  → {table_name}")

    # ── Read CSV ────────────────────────────────────────────────
    df = pd.read_csv(csv_path, low_memory=False)
    print(f"  Read {len(df):,} rows × {len(df.columns)} cols")

    # ── Coerce ──────────────────────────────────────────────────
    df = coerce_nulls(df)
    df = coerce_booleans(df, table_name)

    # ── Get actual columns from DB (only load what DB expects) ──
    cur = conn.cursor()
    schema, tbl = table_name.split(".")
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, tbl))
    db_cols = [r[0] for r in cur.fetchall()]
    cur.close()

    # Keep only columns that exist in DB, in DB order
    csv_cols_lower = {c.lower(): c for c in df.columns}
    cols_to_load = [c for c in db_cols if c.lower() in csv_cols_lower]
    df = df[[csv_cols_lower[c.lower()] for c in cols_to_load]]
    df.columns = cols_to_load   # normalise to DB casing

    skipped_cols = set(db_cols) - set(cols_to_load)
    extra_cols   = set(c.lower() for c in csv_cols_lower) - set(c.lower() for c in db_cols)
    if skipped_cols:
        print(f"  ⚠ DB cols not in CSV (will be NULL): {skipped_cols}")
    if extra_cols:
        print(f"  ⚠ CSV cols not in DB (dropped):       {extra_cols}")

    # ── Truncate ─────────────────────────────────────────────────
    if truncate:
        cur = conn.cursor()
        cur.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE")
        conn.commit()
        cur.close()
        print(f"  Truncated {table_name}")

    # ── Load ─────────────────────────────────────────────────────
    loaded, errors = df_to_postgres(conn, df, table_name)
    elapsed = time.time() - start

    result = {
        "table":    table_name,
        "csv":      os.path.basename(csv_path),
        "rows_in":  len(df),
        "rows_loaded": loaded,
        "errors":   errors,
        "elapsed":  round(elapsed, 1),
        "status":   "✓ OK" if errors == 0 else f"⚠ {errors} errors"
    }
    print(f"  {result['status']} — {loaded:,} rows in {elapsed:.1f}s")
    return result


def verify_counts(conn):
    """Query actual row counts from all tables after load."""
    print(f"\n{'='*60}")
    print("VERIFICATION — Row counts in PostgreSQL")
    print(f"{'='*60}")

    tables = [
        ("reference", "dim_machine_type",                    3),
        ("reference", "dim_machines",                       17),
        ("reference", "dim_users",                          15),
        ("gmaw",      "fact_deviation",                 48_111),
        ("gmaw",      "fact_machine_derived_gmaw",          11),
        ("gmaw",      "fact_periodic_gmaw",             79_126),
        ("clad",      "fact_summarize_clad",            25_935),
        ("gascutting","fact_periodic_gascutting",       20_874),
        ("gascutting","fact_summarize_gascutting",      43_133),
        ("gascutting","fact_summarize_gascutting_noncutting", 29_547),
    ]

    cur = conn.cursor()
    total_actual = 0
    all_ok = True

    print(f"{'Table':<50} {'Expected':>10} {'Actual':>10} {'Status':>8}")
    print("-" * 82)

    for schema, table, expected in tables:
        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        actual = cur.fetchone()[0]
        total_actual += actual
        ok = "✓" if actual >= expected * 0.98 else "✗"  # 2% tolerance
        if ok == "✗":
            all_ok = False
        print(f"  {schema}.{table:<48} {expected:>10,} {actual:>10,} {ok:>8}")

    cur.close()
    print(f"\n  Total rows in database: {total_actual:,}")
    print(f"  Overall status: {'✓ ALL OK' if all_ok else '✗ SOME TABLES HAVE LOW COUNTS'}")
    return all_ok


def run_sanity_queries(conn):
    """Run a few representative queries to confirm data is usable."""
    print(f"\n{'='*60}")
    print("SANITY QUERIES")
    print(f"{'='*60}")

    queries = [
        (
            "GMAW avg weld current by machine (welding only)",
            """
            SELECT machine_name,
                   ROUND(AVG(weld_cur)::NUMERIC, 1) AS avg_weld_cur_A,
                   ROUND(AVG(weld_volt)::NUMERIC, 1) AS avg_weld_volt_V,
                   COUNT(*) AS readings
            FROM gmaw.fact_periodic_gmaw
            WHERE is_welding = TRUE
            GROUP BY machine_name
            ORDER BY machine_name
            LIMIT 5
            """
        ),
        (
            "CLAD session counts per machine (valid sessions only)",
            """
            SELECT machine_name,
                   COUNT(*) FILTER (WHERE NOT is_instantaneous) AS valid_sessions,
                   ROUND(AVG(avg_weld_cur) FILTER (WHERE NOT is_instantaneous)::NUMERIC, 1) AS avg_cur_A
            FROM clad.fact_summarize_clad
            GROUP BY machine_name
            ORDER BY machine_name
            """
        ),
        (
            "GASCUTTING avg cut speed by shift (valid cuts only)",
            """
            SELECT shift_name,
                   COUNT(*) AS cuts,
                   ROUND(AVG(mm_per_min)::NUMERIC, 1) AS avg_speed_mm_per_min,
                   ROUND(AVG(thickness)::NUMERIC, 1) AS avg_thickness_mm
            FROM gascutting.fact_summarize_gascutting
            WHERE timer_overflow = FALSE
              AND travel_outlier = FALSE
              AND speed_valid = TRUE
            GROUP BY shift_name
            ORDER BY shift_name
            """
        ),
        (
            "Top 5 deviation types (GMAW machines)",
            """
            SELECT deviation_label, parameter_unit,
                   COUNT(*) AS events,
                   ROUND(AVG(span_seconds)::NUMERIC, 1) AS avg_span_s
            FROM gmaw.fact_deviation
            WHERE machine_type = 'GMAW'
            GROUP BY deviation_label, parameter_unit
            ORDER BY events DESC
            LIMIT 5
            """
        ),
    ]

    cur = conn.cursor()
    for title, sql in queries:
        print(f"\n  ── {title}")
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        print("  " + " | ".join(f"{c:<28}" for c in cols))
        print("  " + "-" * (30 * len(cols)))
        for row in rows:
            print("  " + " | ".join(f"{str(v):<28}" for v in row))
    cur.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn",   default=None,
                        help="PostgreSQL DSN e.g. postgresql://user:pass@host/db")
    parser.add_argument("--dir",   default=None,
                        help="Directory containing cleaned CSVs (default: ./cleaned_output)")
    parser.add_argument("--table", default=None,
                        help="Load only this table (e.g. fact_periodic_gmaw)")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip row count verification")
    args = parser.parse_args()

    # Locate CSV directory
    csv_dir = args.dir or os.path.join(os.path.dirname(__file__), "cleaned_output")
    if not os.path.isdir(csv_dir):
        print(f"ERROR: CSV directory not found: {csv_dir}")
        print("Pass --dir /path/to/cleaned_output or run from the project folder.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("TATA STEEL — PostgreSQL Data Loader")
    print(f"  CSV source : {csv_dir}")
    print(f"{'='*60}")

    # Connect
    try:
        conn = get_connection(args.dsn)
        print(f"  Connected to PostgreSQL ✓")
    except Exception as e:
        print(f"  Connection failed: {e}")
        print("\n  Check your .env file or --dsn argument.")
        sys.exit(1)

    # Filter plan if --table specified
    plan = LOAD_PLAN
    if args.table:
        plan = [(f, t, tr) for f, t, tr in LOAD_PLAN
                if t.split(".")[-1] == args.table or t == args.table]
        if not plan:
            print(f"ERROR: Table '{args.table}' not found in load plan.")
            sys.exit(1)

    # Run loads
    results = []
    for csv_file, table_name, truncate in plan:
        csv_path = os.path.join(csv_dir, csv_file)
        if not os.path.exists(csv_path):
            print(f"\n  ✗ SKIPPED {csv_file} — file not found at {csv_path}")
            results.append({"table": table_name, "status": "file not found"})
            continue
        result = load_table(conn, csv_path, table_name, truncate)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("LOAD SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Table':<50} {'Rows':>10} {'Time':>8} Status")
    print(f"  {'-'*78}")
    total_rows = 0
    for r in results:
        rows = r.get("rows_loaded", 0)
        total_rows += rows
        t = r.get("elapsed", 0)
        print(f"  {r['table']:<50} {rows:>10,} {t:>7.1f}s {r.get('status','')}")
    print(f"\n  Total rows loaded: {total_rows:,}")

    # Verify
    if not args.no_verify and not args.table:
        verify_counts(conn)
        run_sanity_queries(conn)

    conn.close()
    print(f"\n  Done. Connection closed.\n")


if __name__ == "__main__":
    main()
