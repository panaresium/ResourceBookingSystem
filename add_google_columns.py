import sqlite3
import os

# Path to your SQLite database file
BASEDIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASEDIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'site.db')

def add_columns_to_user_table():
    if not os.path.exists(DATA_DIR):
        print(f"Data directory {DATA_DIR} not found. Make sure it exists.")
        # Attempt to create data directory if it's missing, assuming site.db might not exist yet.
        try:
            os.makedirs(DATA_DIR)
            print(f"Created data directory: {DATA_DIR}")
        except OSError as e:
            print(f"Error creating data directory {DATA_DIR}: {e}")
            return # Stop if data directory cannot be created

    if not os.path.exists(DB_PATH):
        print(f"Database file not found at {DB_PATH}. The script expects an existing database created by app.py's init_db (or similar).")
        print("If you are setting up for the first time, run app.py with init_db() uncommented first.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check if google_id column exists
        cursor.execute("PRAGMA table_info(user)")
        columns = [info[1] for info in cursor.fetchall()]

        if 'google_id' not in columns:
            print("Adding 'google_id' column to 'user' table...")
            cursor.execute("ALTER TABLE user ADD COLUMN google_id VARCHAR(200)")
            print("'google_id' column added.")
        else:
            print("'google_id' column already exists.")

        if 'google_email' not in columns:
            print("Adding 'google_email' column to 'user' table...")
            cursor.execute("ALTER TABLE user ADD COLUMN google_email VARCHAR(200)")
            print("'google_email' column added.")
        else:
            print("'google_email' column already exists.")
            
        # Note on UNIQUE constraint for google_id:
        # SQLAlchemy model defines `google_id` as unique.
        # `ALTER TABLE ADD COLUMN ... UNIQUE` is not supported in older SQLite versions.
        # If the column is added without UNIQUE and then an index is created, that's the way.
        # Let's try to create a unique index if the column was just added or if it exists without one.
        
        # Check existing indexes
        cursor.execute("PRAGMA index_list(user)")
        indexes = [idx[1] for idx in cursor.fetchall()]
        google_id_index_name = 'ix_user_google_id' # Common naming convention for SQLAlchemy

        needs_unique_index = False
        if 'google_id' in columns: # Only try to add index if column exists
            if google_id_index_name not in indexes:
                # If index doesn't exist, we want to create it.
                # If column was just added, it definitely needs an index.
                # If column existed but index didn't, we also want to create it.
                needs_unique_index = True
            else: # Index exists, check if it's unique
                cursor.execute(f"PRAGMA index_info({google_id_index_name})")
                # For a simple index on one column, if PRAGMA index_info returns a row, it's part of the index.
                # The uniqueness is part of the CREATE INDEX statement.
                # We'll assume if `ix_user_google_id` exists, it was created as unique by SQLAlchemy if possible,
                # or we create it now. It's hard to introspect if an *existing* index is unique without parsing SQL.
                # For simplicity, if the specifically named unique index isn't there, try to create it.
                # This might fail if a non-unique index with the same name exists or a unique index with a different name on the same column exists.
                print(f"Index '{google_id_index_name}' already exists. Assuming it enforces uniqueness as per model.")


        if needs_unique_index:
            try:
                print(f"Attempting to create unique index '{google_id_index_name}' on 'user(google_id)'...")
                cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {google_id_index_name} ON user (google_id)")
                print(f"Unique index '{google_id_index_name}' created or already exists.")
            except sqlite3.IntegrityError as ie:
                # This can happen if there are duplicate google_id values already in the table
                print(f"Could not create unique index on google_id. Possible duplicate values exist: {ie}")
            except sqlite3.OperationalError as oe:
                print(f"Operational error creating unique index: {oe}")


        conn.commit()
        print("Database schema update process completed.")

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    print("This script is intended to add 'google_id' and 'google_email' columns to the 'user' table ")
    print(f"for the database at {DB_PATH}, and attempt to create a unique index on 'google_id'.")
    print("IMPORTANT: PLEASE BACK UP YOUR DATABASE FILE (data/site.db) MANUALLY BEFORE PROCEEDING.")
    
    user_confirmation = input("Are you sure you want to continue? (yes/no): ")
    if user_confirmation.lower() == 'yes':
        add_columns_to_user_table()
    else:
        print("Operation cancelled by the user.")
