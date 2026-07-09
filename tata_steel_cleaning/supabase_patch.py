# save as supabase_patch.py in the same folder, then run it
import os, psycopg2
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
cur = conn.cursor()

# Fix 1: parameter_unit
for param, unit in [("current","A"), ("voltage","V"), ("gas","L/min")]:
    cur.execute("UPDATE gmaw.fact_deviation SET parameter_unit=%s WHERE LOWER(parameter)=%s", (unit, param))
    print(f"  parameter='{param}' → unit='{unit}': {cur.rowcount} rows")

# Fix 2a: phno in dim_users (cast float strings to int)
cur.execute("UPDATE reference.dim_users SET phno = phno::NUMERIC::BIGINT WHERE phno IS NOT NULL")
print(f"  dim_users.phno cast: {cur.rowcount} rows")

# Fix 2b: mid in fact_deviation (already smallint in DB — just verify)
cur.execute("SELECT COUNT(*) FROM gmaw.fact_deviation WHERE mid IS NOT NULL")
print(f"  fact_deviation mid not null: {cur.fetchone()[0]}")

conn.commit()

# Final verify
cur.execute("SELECT parameter_unit, COUNT(*) FROM gmaw.fact_deviation GROUP BY 1 ORDER BY 2 DESC")
print("\nparameter_unit distribution:")
for r in cur.fetchall(): print(f"  {r[0]}: {r[1]:,}")

cur.execute("SELECT COUNT(*) FROM gmaw.fact_deviation WHERE parameter_unit IS NULL")
print(f"NULL parameter_unit remaining: {cur.fetchone()[0]} (should be 0)")

cur.close(); conn.close()
print("\n✓ Supabase patched. Ready for Phase 2C.")