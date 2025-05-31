import sqlite3
import os

BASEDIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASEDIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'site.db')

def add_tags_column():
    if not os.path.exists(DB_PATH):
        print(f"Database file not found at {DB_PATH}. Run init_db() first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(resource)")
    columns = [info[1] for info in cursor.fetchall()]

    if 'tags' not in columns:
        print("Adding 'tags' column to 'resource' table...")
        cursor.execute("ALTER TABLE resource ADD COLUMN tags VARCHAR(200)")
        conn.commit()
        print("'tags' column added.")
    else:
        print("'tags' column already exists. No action taken.")

    conn.close()

if __name__ == '__main__':
    add_tags_column()
