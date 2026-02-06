
function non_asci_to_ascii {
    # [CmdletBinding()]
    # param (
    #     [Parameter()]
    #     [string]
    #     $ParameterName
    # ){
    
    Get-ChildItem -Path "C:\projects\sbrown\Python\db_file_exports" -Filter "*.csv" | ForEach-Object {
        Write-Host "Running script: ..\non_asci_to_ascii.py $($_.FullName) C:\projects\sbrown\Python\db_file_exports\output_csvs\$($_.Name)"
        C:\projects\sbrown\native_env\Scripts\python.exe C:\projects\sbrown\Python\non_ascii_to_ascii.py $($_.FullName) "C:\projects\sbrown\Python\db_file_exports\output_csv\$($_.Name)"
    }
    
    # }
}

function add_all_columns_to_csv {
    Get-ChildItem -Path "C:\projects\sbrown\Python\db_file_exports\output_csv" -Filter "*work_packag*.csv" | ForEach-Object {
        mkdir "C:\projects\sbrown\Python\db_file_exports\output_csv_with_additional_columns" -ErrorAction SilentlyContinue
        Write-Host "Running script: ..\csv_add_all_clumns_to_csv.py $($_.FullName) C:\projects\sbrown\Python\db_file_exports\output_csv_with_additional_columns\$($_.Name)"
        C:\projects\sbrown\native_env\Scripts\python.exe C:\projects\sbrown\Python\csv_add_all_clumns_to_csv.py $($_.FullName) "C:\projects\sbrown\Python\db_file_exports\output_csv_with_additional_columns\$($_.Name)"
    }
}

non_asci_to_ascii {}

add_all_columns_to_csv {}

Start-Process excel 

# Use Get-Data CSV to import primary workbook
# After Get Data [UTF-8] import is done, select all and convert to range
# Find and Replace for remove "[comment_Number]s" etc...

## Select the heading row 1
## These items to remove numbers from headings = ["includes", "blocks", "relates", "duplicates", "follows", "requires", "comment"]

### Format Date/Time columns [due, created, updated, start] to "dd/MMM/yy h:mm AM/PM" format

#### Version lookup for auto convert, duplicate column version_id to version_name using versions sheet and vlookup

# =VLOOKUP(VALUE(K19),versions[[id]:[name]]2,FALSE)

## Type lookups 
## Added column beside type_id
# Put this item in 

# =LET(
# typeName,VLOOKUP(C2,'_types__202602052109'!A:B,2,FALSE),
# t1_projid,IFNA(VLOOKUP(AF2,group_parents_so_sub_task_assig!A:C,3,FALSE),FALSE),
# t2_projid,IFNA(VLOOKUP(AF2,group_parents_so_sub_task_assig!F:G,2,FALSE),FALSE),
# checkValue,EXACT(t1_projid,t2_projid),
# IF(
# AND(ISNUMBER(AF2),checkValue),
# typeName&" (Sub-Task)",typeName))
