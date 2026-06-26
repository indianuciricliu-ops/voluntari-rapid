import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'voluntari.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute('ALTER TABLE confirmari ADD COLUMN ora_sosire VARCHAR(10)')
    conn.commit()
    print("✅ Coloana ora_sosire adaugata cu succes!")
except Exception as e:
    print(f"⚠️  {e}")
finally:
    conn.close()