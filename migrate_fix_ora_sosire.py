import os
import sqlite3

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'voluntari.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("PRAGMA table_info(confirmari)")
    cols = [row[1] for row in cursor.fetchall()]

    if 'ora_sosire' in cols:
        cursor.execute("ALTER TABLE confirmari RENAME TO confirmari_old")
        cursor.execute("""
            CREATE TABLE confirmari (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voluntar_id INTEGER NOT NULL,
                eveniment_id INTEGER NOT NULL,
                raspuns VARCHAR(20),
                ora_sosire VARCHAR(20),
                data_raspuns DATETIME
            )
        """)
        cursor.execute("""
            INSERT INTO confirmari (id, voluntar_id, eveniment_id, raspuns, data_raspuns)
            SELECT id, voluntar_id, eveniment_id, raspuns, data_raspuns
            FROM confirmari_old
        """)
        cursor.execute("DROP TABLE confirmari_old")
    else:
        cursor.execute("ALTER TABLE confirmari ADD COLUMN ora_sosire VARCHAR(20)")

    conn.commit()
    print("✅ Migrare completă: ora_sosire corectată")
except Exception as e:
    print(f"⚠️  {e}")
finally:
    conn.close()