import pandas as pd

excel_file = r"C:\\projects\\sbrown\\Python\\temp_exports_for_db\\second_updated_workbook-relations-comments.xlsx"
sheet_name = "Sheet1"
# output_csv = "C:\\projects\\sbrown\\Python\\filtered_output.csv"



df = pd.read_excel(excel_file, sheet_name=sheet_name,engine="openpyxl")

# Query the data
projects = [3, 6, 8, 9]
for p in projects:
    # filtered_df = df.query('project == 3')
    project_df = df.query("project == @p")

    # filtered_df.to_csv(output_csv, index=False)
    project_df.to_csv(f"C:\\projects\\sbrown\\Python\\temp_exports_for_db\\project_{p}.csv", index=False)

print("Filtered CSV exported successfully.")