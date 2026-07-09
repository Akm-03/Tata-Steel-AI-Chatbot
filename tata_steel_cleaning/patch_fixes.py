"""
patch_fixes.py
==============
Fix 1: parameter_unit was NULL in fact_deviation
        — source 'parameter' values are 'current'/'voltage'/'gas'
          but unit map used full names like 'weld_cur'
Fix 2: mid (SMALLINT) and phno (BIGINT) exported as float64
        — pandas reads int columns with NULLs as float, producing "14.0"
          which PostgreSQL COPY rejects for integer columns

Run:
    python patch_fixes.py

What it does:
    1. Patches fact_deviation.csv  → re-exports with correct parameter_unit
    2. Patches dim_users.csv       → phno as integer string
    3. Patches fact_deviation.csv + fact_machine_derived_gmaw.csv → mid as int
    4. Runs UPDATE on live PostgreSQL to fix parameter_unit in-place
    5. Re-runs COPY for the int columns that previously fell back to execute_values
"""

import pandas as pd
import numpy as np
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

CSV_DIR = os.path.join(os.path.dirname(__file__), "cleaned_output")

# ── Correct unit map matching actual 'parameter' values in deviation CSV ────
# Source has: 'current', 'voltage', 'gas'  (short form, not 'weld_cur' etc.)
UNIT_MAP_ACTUAL = {
    "current": "A",        # Amperes
    "voltage": "V",        # Volts
    "gas":     "L/min",    # Litres per minute (shielding gas)
    # CLAD-specific (if present)
    "weld_cur":  "A",
    "weld_volt": "V",
    "weld_gas":  "L/min",
    "hs_temp":   "°C",
    "amb_temp":  "°C",
    "motor_cur": "A",
    "motor_volt":"V",
}

def connect():
    return psycopg2.connect(
        host     = os.getenv("PG_HOST",     "localhost"),
        port     = os.getenv("PG_PORT",     "5432"),
        dbname   = os.getenv("PG_DATABASE", "tata_steel_ops"),
        user     = os.getenv("PG_USER",     "postgres"),
        password = os.getenv("PG_PASSWORD", ""),
    )

# ════════════════════════════════════════════════════════════════
# FIX 1: parameter_unit in fact_deviation
# ════════════════════════════════════════════════════════════════
def fix_parameter_unit():
    print("\n── FIX 1: parameter_unit in fact_deviation ──────────────")
    path = os.path.join(CSV_DIR, "fact_deviation.csv")
    df   = pd.read_csv(path, low_memory=False)

    before_nulls = df["parameter_unit"].isna().sum()
    print(f"  Null parameter_unit before fix: {before_nulls:,} / {len(df):,}")
    print(f"  Unique 'parameter' values: {df['parameter'].unique().tolist()}")

    # Apply correct unit map
    df["parameter_unit"] = df["parameter"].str.lower().str.strip().map(UNIT_MAP_ACTUAL)

    after_nulls = df["parameter_unit"].isna().sum()
    print(f"  Null parameter_unit after fix:  {after_nulls:,}")
    print(f"  Distribution: {df['parameter_unit'].value_counts().to_dict()}")

    # Save patched CSV
    df.to_csv(path, index=False)
    print(f"  ✓ Saved patched fact_deviation.csv")

    # Patch PostgreSQL directly via UPDATE (much faster than re-loading)
    print("  Patching PostgreSQL via UPDATE...")
    conn = connect()
    cur  = conn.cursor()

    for param_val, unit in UNIT_MAP_ACTUAL.items():
        cur.execute("""
            UPDATE gmaw.fact_deviation
            SET    parameter_unit = %s
            WHERE  LOWER(parameter) = %s
        """, (unit, param_val))
        print(f"    SET parameter_unit='{unit}' WHERE parameter='{param_val}' "
              f"→ {cur.rowcount} rows")

    conn.commit()

    # Verify
    cur.execute("SELECT parameter_unit, COUNT(*) FROM gmaw.fact_deviation GROUP BY 1 ORDER BY 2 DESC")
    print("\n  Verification — parameter_unit distribution in DB:")
    for row in cur.fetchall():
        print(f"    {str(row[0]):<10} → {row[1]:,} rows")

    cur.close()
    conn.close()
    print("  ✓ PostgreSQL parameter_unit patched")


# ════════════════════════════════════════════════════════════════
# FIX 2: Float → Integer coercion in CSVs + DB
# ════════════════════════════════════════════════════════════════

def int_col(series):
    """Convert float64 series to nullable integer string for CSV export.
    14.0 → '14', NaN → '' (empty = NULL in PostgreSQL COPY)
    """
    return series.apply(
        lambda x: "" if pd.isna(x) else str(int(x))
    )

def fix_integer_columns():
    print("\n── FIX 2: Float → Integer columns ──────────────────────")

    # ── 2a. dim_users: phno BIGINT ──────────────────────────────
    print("\n  2a. dim_users.phno (BIGINT)")
    path  = os.path.join(CSV_DIR, "dim_users.csv")
    df    = pd.read_csv(path)
    print(f"  phno before: {df['phno'].head(3).tolist()}")

    df["phno"] = int_col(df["phno"])
    # Also fix uid if float
    if df["uid"].dtype == float:
        df["uid"] = int_col(df["uid"])

    df.to_csv(path, index=False)
    print(f"  phno after:  {df['phno'].head(3).tolist()}")
    print(f"  ✓ Saved patched dim_users.csv")

    # Patch DB — re-load via UPDATE for 15 rows (fastest approach)
    conn = connect()
    cur  = conn.cursor()
    orig = pd.read_csv(path)
    for _, row in orig.iterrows():
        phno_val = None if row["phno"] == "" else int(row["phno"])
        cur.execute(
            "UPDATE reference.dim_users SET phno = %s WHERE uid = %s",
            (phno_val, int(row["uid"]))
        )
    conn.commit()
    cur.execute("SELECT uid, name, phno FROM reference.dim_users LIMIT 3")
    print("  DB sample after patch:")
    for r in cur.fetchall():
        print(f"    uid={r[0]} name={r[1]} phno={r[2]}")
    cur.close()
    conn.close()
    print("  ✓ dim_users.phno patched in DB")

    # ── 2b. fact_deviation: mid SMALLINT ────────────────────────
    print("\n  2b. fact_deviation.mid (SMALLINT)")
    path = os.path.join(CSV_DIR, "fact_deviation.csv")
    df   = pd.read_csv(path, low_memory=False)
    print(f"  mid before: {df['mid'].head(3).tolist()}")

    df["mid"] = int_col(df["mid"])
    df.to_csv(path, index=False)
    print(f"  mid after:  {df['mid'].head(3).tolist()}")
    print(f"  ✓ Saved patched fact_deviation.csv")

    # Patch DB — UPDATE mid where it's correctly joined
    conn = connect()
    cur  = conn.cursor()
    orig = pd.read_csv(path, low_memory=False, usecols=["hardware_id","start_tm","mid"])
    orig = orig[orig["mid"] != ""]
    # Use hardware_id + start_tm as composite key for update
    updated = 0
    for _, row in orig.iterrows():
        cur.execute("""
            UPDATE gmaw.fact_deviation
            SET    mid = %s
            WHERE  hardware_id = %s AND start_tm = %s AND mid IS DISTINCT FROM %s
        """, (int(row["mid"]), row["hardware_id"], row["start_tm"], int(row["mid"])))
        updated += cur.rowcount
    conn.commit()

    cur.execute("SELECT mid, COUNT(*) FROM gmaw.fact_deviation WHERE mid IS NOT NULL GROUP BY 1 LIMIT 3")
    print(f"  DB sample mid values: {cur.fetchall()}")
    cur.close()
    conn.close()
    print(f"  ✓ fact_deviation.mid patched in DB ({updated} rows updated)")

    # ── 2c. fact_machine_derived_gmaw: mid SMALLINT ──────────────
    print("\n  2c. fact_machine_derived_gmaw.mid (SMALLINT)")
    path = os.path.join(CSV_DIR, "fact_machine_derived_gmaw.csv")
    df   = pd.read_csv(path)
    print(f"  mid before: {df['mid'].head(3).tolist()}")

    df["mid"] = int_col(df["mid"])
    df.to_csv(path, index=False)
    print(f"  mid after:  {df['mid'].head(3).tolist()}")
    print(f"  ✓ Saved patched fact_machine_derived_gmaw.csv")

    # For 11 rows — just truncate + reload
    conn = connect()
    cur  = conn.cursor()
    cur.execute("TRUNCATE TABLE gmaw.fact_machine_derived_gmaw")

    orig = pd.read_csv(path)
    for _, row in orig.iterrows():
        cols = list(orig.columns)
        vals = []
        for v in row:
            if v == "" or (isinstance(v, float) and np.isnan(v)):
                vals.append(None)
            else:
                vals.append(v)
        placeholders = ", ".join(["%s"] * len(cols))
        col_str = ", ".join(cols)
        cur.execute(f"INSERT INTO gmaw.fact_machine_derived_gmaw ({col_str}) VALUES ({placeholders})", vals)

    conn.commit()
    cur.execute("SELECT mid, machine_name, arc_efficiency_pct FROM gmaw.fact_machine_derived_gmaw LIMIT 3")
    print(f"  DB sample: {cur.fetchall()}")
    cur.close()
    conn.close()
    print(f"  ✓ fact_machine_derived_gmaw reloaded with correct mid type")


# ════════════════════════════════════════════════════════════════
# FIX 3: Also patch loader for future reloads (prevent recurrence)
# ════════════════════════════════════════════════════════════════
def patch_loader():
    """Add INT_COLS manifest to postgres_loader.py so COPY always gets
       clean integer strings, not '14.0' floats."""
    print("\n── FIX 3: Patching postgres_loader.py ──────────────────")
    loader_path = os.path.join(os.path.dirname(__file__), "postgres_loader.py")

    int_cols_block = '''
# Integer columns per table — pandas reads these as float64 when NULLs present.
# Loader will convert 14.0 → "14", NaN → "" before COPY.
INT_COLS = {
    "reference.dim_users":              ["uid", "phno", "roleid", "hid", "orgid"],
    "reference.dim_machines":           ["mid", "mtid", "msid", "hid", "orgid", "mcsid", "mcid"],
    "gmaw.fact_deviation":              ["mid"],
    "gmaw.fact_machine_derived_gmaw":   ["mid"],
}
'''
    with open(loader_path, "r") as f:
        content = f.read()

    if "INT_COLS" in content:
        print("  postgres_loader.py already has INT_COLS — skipping")
        return

    # Insert after BOOLEAN_COLS block
    insert_after = "}\n\n\ndef coerce_booleans"
    patched = content.replace(
        insert_after,
        "}\n" + int_cols_block + "\ndef coerce_booleans"
    )

    # Add int coercion call inside load_table, after coerce_booleans line
    patched = patched.replace(
        "    df = coerce_booleans(df, table_name)",
        "    df = coerce_booleans(df, table_name)\n    df = coerce_integers(df, table_name)"
    )

    # Add coerce_integers function before coerce_booleans
    int_fn = '''
def coerce_integers(df, table_name):
    """Convert float64 integer columns to clean int strings for COPY."""
    int_col_list = INT_COLS.get(table_name, [])
    for col in int_col_list:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: "" if pd.isna(x) else str(int(float(x)))
            )
    return df

'''
    patched = patched.replace("def coerce_booleans", int_fn + "def coerce_booleans")

    with open(loader_path, "w") as f:
        f.write(patched)

    # Copy patched loader to outputs
    import shutil
    shutil.copy(loader_path, "/mnt/user-data/outputs/postgres_loader.py")
    print("  ✓ postgres_loader.py patched — future reloads will use clean int strings")


# ════════════════════════════════════════════════════════════════
# FINAL VERIFICATION
# ════════════════════════════════════════════════════════════════
def final_verify():
    print("\n── FINAL VERIFICATION ───────────────────────────────────")
    conn = connect()
    cur  = conn.cursor()

    checks = [
        ("parameter_unit NULL in deviation",
         "SELECT COUNT(*) FROM gmaw.fact_deviation WHERE parameter_unit IS NULL",
         0),
        ("parameter_unit='A' rows",
         "SELECT COUNT(*) FROM gmaw.fact_deviation WHERE parameter_unit = 'A'",
         None),
        ("parameter_unit='V' rows",
         "SELECT COUNT(*) FROM gmaw.fact_deviation WHERE parameter_unit = 'V'",
         None),
        ("parameter_unit='L/min' rows",
         "SELECT COUNT(*) FROM gmaw.fact_deviation WHERE parameter_unit = 'L/min'",
         None),
        ("dim_users phno is integer (no .0)",
         "SELECT COUNT(*) FROM reference.dim_users WHERE phno::TEXT LIKE '%.%'",
         0),
        ("fact_deviation mid is integer (not null)",
         "SELECT COUNT(*) FROM gmaw.fact_deviation WHERE mid IS NOT NULL",
         None),
    ]

    all_ok = True
    for label, sql, expected in checks:
        cur.execute(sql)
        val = cur.fetchone()[0]
        if expected is not None:
            ok = "✓" if val == expected else "✗"
            if val != expected:
                all_ok = False
        else:
            ok = "✓" if val > 0 else "ℹ"
        print(f"  {ok} {label}: {val:,}")

    cur.close()
    conn.close()
    print(f"\n  {'✓ All checks passed' if all_ok else '✗ Some checks failed — see above'}")


if __name__ == "__main__":
    fix_parameter_unit()
    fix_integer_columns()
    patch_loader()
    final_verify()
    print("\n✓ Both fixes complete. Proceed to Phase 2C.\n")