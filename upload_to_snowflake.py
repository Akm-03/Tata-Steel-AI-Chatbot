import os
import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from dotenv import load_dotenv

load_dotenv()

print("Connecting to Snowflake...")

try:
    # 1. Establish the cloud connection
    conn = snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA")
    )
    print("Connection successful! Preparing data...")

    # 2. Load the Cleaned Data
    df_machines = pd.read_csv('cleaned_machines.csv')
    df_deviations = pd.read_csv('cleaned_deviation.csv')

    # Force column names to uppercase (Snowflake requires this for pandas uploads)
    df_machines.columns = df_machines.columns.str.upper()
    df_deviations.columns = df_deviations.columns.str.upper()

    # 3. Upload the Data
    print("Uploading MACHINES data...")
    success_mach, nchunks_mach, nrows_mach, _ = write_pandas(conn, df_machines, 'MACHINES')
    
    print("Uploading DEVIATIONS data...")
    success_dev, nchunks_dev, nrows_dev, _ = write_pandas(conn, df_deviations, 'DEVIATIONS')

    print(f"\n--- SUCCESS ---")
    print(f"Uploaded {nrows_mach} rows to MACHINES.")
    print(f"Uploaded {nrows_dev} rows to DEVIATIONS.")

except Exception as e:
    print(f"\nERROR: {e}")
finally:
    if 'conn' in locals():
        conn.close()