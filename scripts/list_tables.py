import pyodbc
conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-E7P613O\\STORE_DATA;DATABASE=POS_SANDBOX;UID=tzaf;PWD=240683;')
cursor = conn.cursor()
cursor.execute("SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='dbo' ORDER BY TABLE_TYPE, TABLE_NAME")
for row in cursor.fetchall():
    print(row.TABLE_TYPE, '|', row.TABLE_NAME)
conn.close()
