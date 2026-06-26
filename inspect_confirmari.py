import os
import sqlite3

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'voluntari.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(confirmari)")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()