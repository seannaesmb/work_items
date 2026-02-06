import sys
import pandas as pd



# --- Configuration ---
# input_file = "C:\\projects\\sbrown\\Python\\temp_exports_for_db\\work_packages_202601280944_non_ascii.csv"
# output_file = "C:\\projects\\sbrown\\Python\\temp_exports_for_db\\work_packages_202601280944_non_with_additional_columns.csv"

input_file = sys.argv[1]
output_file = sys.argv[2]

headings = ["includes", "blocks", "relates", "duplicates", "follows", "requires", "comment"]
repeat_count = 250
start_col = 34  # 0-based → column 35

# --- Step 1: Read CSV and clean existing headers ---
df = pd.read_csv(input_file, dtype=str)

# Remove any _number suffix from headers
df.columns = [col.split("_")[0] for col in df.columns]

# --- Step 2: Build repeated new columns ---
new_column_names = [h for h in headings for _ in range(repeat_count)]

# Create a DataFrame with empty columns
new_cols_df = pd.DataFrame(columns=new_column_names, index=df.index)

# --- Step 3: Concatenate: before + new columns + after ---
df = pd.concat([df.iloc[:, :start_col], new_cols_df, df.iloc[:, start_col:]], axis=1)

# --- Step 4: Save to Excel ---
df.to_csv(output_file.replace(".xlsx", ".csv"), index=False)


print(f"Done! {len(new_column_names)} columns added starting at column {start_col + 1}.")
