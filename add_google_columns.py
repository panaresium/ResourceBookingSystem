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
        print(f"Attempting to connect to database at: {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        print("Successfully connected to the database.")

        # Operations for adding columns
        try:
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
            
            conn.commit() # Commit after column additions
            print("Column addition checks completed and committed.")

        except sqlite3.Error as e:
            print(f"SQLite error during column addition: {e}")
            if conn:
                conn.rollback()
                print("Column addition changes rolled back due to error.")
            # Re-raise or handle as appropriate if further operations depend on this
            raise # Re-raise to be caught by the outer try/except for final cleanup

        # Check if google_id column now exists before trying to create an index on it
        cursor.execute("PRAGMA table_info(user)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'google_id' in columns:
            # Operations for creating unique index
            try:
                cursor.execute("PRAGMA index_list(user)")
                indexes = [idx[1] for idx in cursor.fetchall()]
                google_id_index_name = 'ix_user_google_id'

                if google_id_index_name not in indexes:
                    print(f"Attempting to create unique index '{google_id_index_name}' on 'user(google_id)'...")
                    # Using IF NOT EXISTS is idempotent for index creation.
                    cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {google_id_index_name} ON user (google_id)")
                    conn.commit() # Commit after successful index creation
                    print(f"Unique index '{google_id_index_name}' created or already exists and was committed.")
                else:
                    print(f"Index '{google_id_index_name}' already exists. No action taken for index creation.")
            
            except sqlite3.IntegrityError as ie:
                # This occurs if data violates the unique constraint (e.g., duplicate google_id values)
                print(f"Could not create unique index on google_id due to data integrity issues (e.g., duplicate values): {ie}")
                print("Please manually ensure all existing 'google_id' values are unique before re-running, or remove them if they are incorrect.")
                if conn:
                    conn.rollback() # Rollback this specific transaction (index creation)
                    print("Index creation changes rolled back.")
            except sqlite3.Error as e: # Catch other SQLite errors during index creation
                print(f"SQLite error during index creation: {e}")
                if conn:
                    conn.rollback()
                    print("Index creation changes rolled back.")
                # Re-raise or handle as appropriate
                raise # Re-raise to be caught by the outer try/except for final cleanup
        else:
            print("Skipping index creation because 'google_id' column does not exist (this is unexpected after attempting to add it).")

        print("Database schema update process completed successfully.")

    except sqlite3.Error as e:
        print(f"An SQLite error occurred: {e}")
        # Rollback is already handled in inner blocks for specific operations,
        # but if connect() itself failed, conn might be None.
        # The main purpose of a rollback here would be if there were uncommitted changes
        # before a failure in a part not covered by inner try-excepts.
        # Given the structure, this outer rollback is a general safety net.
        if conn: 
            conn.rollback()
            print("Outer transaction rolled back due to an error.")
    except Exception as ex:
        print(f"An unexpected error occurred: {ex}")
        if conn:
            conn.rollback()
            print("Outer transaction rolled back due to an unexpected error.")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == '__main__':
    print("This script is intended to add 'google_id' and 'google_email' columns to the 'user' table ")
    print(f"for the database at {DB_PATH}, and attempt to create a unique index on 'google_id'.")
    print("IMPORTANT: PLEASE BACK UP YOUR DATABASE FILE (data/site.db) MANUALLY BEFORE PROCEEDING.")
    
    user_confirmation = input("Are you sure you want to continue? (yes/no): ")
    if user_confirmation.lower() == 'yes':
        add_columns_to_user_table()
    else:
        print("Operation cancelled by the user.")
