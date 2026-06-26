import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'voluntari.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE confirmari RENAME TO confirmari_old")
    cursor.execute("""
        CREATE TABLE confirmari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voluntar_id INTEGER NOT NULL,
            eveniment_id INTEGER NOT NULL,
            raspuns VARCHAR(20),
            ora_sosire VARCHAR(50),
            data_raspuns DATETIME
        )
    """)
    cursor.execute("""
        INSERT INTO confirmari (id, voluntar_id, eveniment_id, raspuns, ora_sosire, data_raspuns)
        SELECT id, voluntar_id, eveniment_id, raspuns, ora_sosire, data_raspuns
        FROM confirmari_old
    """)
    cursor.execute("DROP TABLE confirmari_old")
    conn.commit()
    print("✅ Coloana ora_sosire refacuta ca VARCHAR(50)")
except Exception as e:
    print(f"⚠️  {e}")
finally:
    conn.close()