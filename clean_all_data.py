import pandas as pd

print("Starting global data cleaning process...")

# 1. Clean 'deviation.csv' (8 columns)
print("Cleaning deviation.csv...")
dev_cols = ['HARDWARE_ID', 'JOB_ID', 'STATUS_CODE', 'START_TIME', 'END_TIME', 'DURATION_SECS', 'DEVIATION_LEVEL', 'PARAMETER_TYPE']
df_dev = pd.read_csv('deviation.csv', names=dev_cols)
df_dev['DEVIATION_LEVEL'] = df_dev['DEVIATION_LEVEL'].str.lower()
df_dev['PARAMETER_TYPE'] = df_dev['PARAMETER_TYPE'].str.lower()
df_dev['START_TIME'] = pd.to_datetime(df_dev['START_TIME'], errors='coerce')
df_dev['END_TIME'] = pd.to_datetime(df_dev['END_TIME'], errors='coerce')
df_dev.to_csv('cleaned_deviation.csv', index=False)

# 2. Clean 'machines.csv' (15 columns)
print("Cleaning machines.csv...")
mach_cols = ['ID', 'MACHINE_NAME', 'HARDWARE_ID', 'OPERATION_TYPE', 'COL4', 'COL5', 'COL6', 'COL7', 'COL8', 'COL9', 'COL10', 'FLAG1', 'FLAG2', 'CREATED_AT', 'UPDATED_AT']
df_mach = pd.read_csv('machines.csv', names=mach_cols)
df_mach.fillna('UNKNOWN', inplace=True)
df_mach.to_csv('cleaned_machines.csv', index=False)

# 3. Clean 'machine_type.csv' (4 columns)
print("Cleaning machine_type.csv...")
mt_cols = ['ID', 'TYPE', 'CREATED_AT', 'UPDATED_AT']
df_mt = pd.read_csv('machine_type.csv', names=mt_cols)
df_mt.to_csv('cleaned_machine_type.csv', index=False)

# 4. Clean 'machine_derived.csv' (17 columns)
print("Cleaning machine_derived.csv...")
md_cols = ['TIMESTAMP', 'SHIFT', 'MACHINE_TYPE', 'MACHINE_NAME', 'HARDWARE_ID', 'START_TIME', 'END_TIME', 'METRIC1', 'METRIC2', 'METRIC3', 'METRIC4', 'METRIC5', 'METRIC6', 'METRIC7', 'METRIC8', 'METRIC9', 'METRIC10']
df_md = pd.read_csv('machine_derived.csv', names=md_cols)
df_md.to_csv('cleaned_machine_derived.csv', index=False)

# 5. Clean 'periodic_data_interval2 (2).csv' (Already has 45 columns with headers)
print("Cleaning periodic_data_interval2.csv...")
df_per = pd.read_csv('periodic_data_interval2 (2).csv')
# Standardize column names to lowercase and remove weird spacing
df_per.columns = df_per.columns.str.lower().str.strip()
df_per.to_csv('cleaned_periodic_data.csv', index=False)

# 6. Clean 'summarize_clad_details_info.csv' (17 columns)
print("Cleaning summarize_clad_details_info.csv...")
clad_cols = ['DATE', 'SHIFT', 'JOB_ID', 'OP_TYPE', 'MACHINE_NAME', 'START', 'END', 'DURATION', 'VAL1', 'VAL2', 'VAL3', 'VAL4', 'VAL5', 'VAL6', 'VAL7', 'VAL8', 'VAL9']
df_clad = pd.read_csv('summarize_clad_details_info.csv', names=clad_cols)
df_clad.to_csv('cleaned_summarize_clad.csv', index=False)

# 7. Clean 'summarize_gascutting_machine.csv' (14 columns)
print("Cleaning summarize_gascutting_machine.csv...")
gas_cols = ['DATE', 'SHIFT', 'OP_TYPE', 'MACHINE_NAME', 'START', 'END', 'DURATION', 'METRIC1', 'METRIC2', 'METRIC3', 'METRIC4', 'METRIC5', 'METRIC6', 'METRIC7']
df_gas = pd.read_csv('summarize_gascutting_machine.csv', names=gas_cols)
df_gas.to_csv('cleaned_summarize_gascutting.csv', index=False)

# 8. Clean 'summarize_nongascut_machine.csv' (11 columns)
print("Cleaning summarize_nongascut_machine.csv...")
nongas_cols = ['DATE', 'SHIFT', 'OP_TYPE', 'MACHINE_NAME', 'START', 'END', 'DURATION', 'METRIC1', 'METRIC2', 'METRIC3', 'METRIC4']
df_nongas = pd.read_csv('summarize_nongascut_machine.csv', names=nongas_cols)
df_nongas.to_csv('cleaned_summarize_nongascut.csv', index=False)

# 9. Clean 'user.csv' (22 columns)
print("Cleaning user.csv...")
user_cols = ['ID', 'NAME', 'EMAIL', 'PHONE', 'ROLE_ID', 'DEPT_ID', 'STATUS_ID', 'BADGE', 'COMPANY', 'HASH', 'COL1', 'COL2', 'IS_ACTIVE', 'CREATED_AT', 'UPDATED_AT', 'EMP_ID', 'COL3', 'COL4', 'COL5', 'COL6', 'COL7', 'COL8']
df_user = pd.read_csv('user.csv', names=user_cols)
df_user.drop(columns=['HASH'], inplace=True) # Good security practice: dropping password hashes
df_user.to_csv('cleaned_user.csv', index=False)

print("All files cleaned successfully! Check your folder for files starting with 'cleaned_'")