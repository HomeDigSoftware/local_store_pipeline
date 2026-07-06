
import pyodbc
import csv
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

output_file = Path("table_list.csv")

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={os.environ['MSSQL_SERVER']};"
    f"DATABASE={os.environ['MSSQL_DATABASE']};"
    f"UID={os.environ['MSSQL_USER']};"
    f"PWD={os.environ['MSSQL_PASSWORD']};"
)

cursor = conn.cursor()
cursor.execute("""
    SELECT TABLE_NAME, TABLE_TYPE
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = 'dbo'
    ORDER BY TABLE_TYPE, TABLE_NAME
""")

with output_file.open("w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow(["table_type", "table_name"])
    for row in cursor.fetchall():
        writer.writerow([row.TABLE_TYPE, row.TABLE_NAME])

conn.close()
print(f"Saved to {output_file.resolve()}")
