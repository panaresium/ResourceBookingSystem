#!/usr/bin/env python3

import sys
import os
import pathlib
import json
from werkzeug.security import generate_password_hash
from datetime import datetime, date, timedelta, time

# Refactored imports for application factory pattern
from app_factory import create_app
from extensions import db
from models import (
    User,
    Resource,
    Booking,
    Role,
    AuditLog,
    FloorMap,
    WaitlistEntry,
    resource_roles_table, # Assuming these are still relevant and defined in models.py
    user_roles_table    # or directly in extensions.py if preferred for table instances
)
# `add_tags_column` seems to be a custom migration script.
# Ensure it's compatible or adjust its import/execution.
# For now, assuming it works independently or is adapted elsewhere.
from add_resource_tags_column import add_tags_column

# Import for Azure restoration
from azure_backup import perform_startup_restore_sequence

import subprocess # For checking sqlite3 CLI availability

# Function to check SQLite CLI availability (definition)
def check_sqlite_cli_availability():
    """Checks for sqlite3 CLI tool and prints guidance if not found."""
    sqlite_exe_name = "sqlite3.exe" if sys.platform == "win32" else "sqlite3"

    # Check 1: Local './tools/' directory (relative to init_setup.py, which is project root)
    # BASE_DIR is pathlib.Path(__file__).resolve().parent, so it's the project root.
    tools_dir = os.path.join(BASE_DIR, "tools")
    local_sqlite_path = os.path.join(tools_dir, sqlite_exe_name)

    if os.path.exists(local_sqlite_path) and os.access(local_sqlite_path, os.X_OK):
        print(f"INFO: Found local sqlite3 CLI at: {local_sqlite_path}")
        return True

    # Check 2: System PATH
    try:
        process = subprocess.run([sqlite_exe_name if sys.platform == "win32" else "sqlite3", "-version"], capture_output=True, text=True, check=False, timeout=5)
        if process.returncode == 0 and "SQLite version" in process.stdout: # check=False, so verify output too
            print(f"INFO: Found sqlite3 CLI in system PATH. Version: {process.stdout.strip()}")
            return True
    except FileNotFoundError:
        # This will be caught if 'sqlite3'/'sqlite3.exe' is not even found in PATH
        pass # Will proceed to the warning message
    except subprocess.TimeoutExpired:
        print(f"WARNING: Checking for sqlite3 in PATH timed out.") # Should not happen for -version
    except Exception as e:
        print(f"WARNING: Error when checking for sqlite3 in PATH: {e}")

    # If not found in either location:
    print("-" * 60)
    print("IMPORTANT: `sqlite3` Command-Line Tool Not Found or Not Executable.")
    print("-" * 60)
    print("The database backup functionality requires the SQLite3 command-line tool.")
    print("You have two options to make it available:")
    print("\n1. Install SQLite3 and add it to your system's PATH:")
    print("   - Download from: https://www.sqlite.org/download.html")
    print("   - Ensure the directory containing `sqlite3` (or `sqlite3.exe`) is in your PATH environment variable.")
    print("\n2. Place the SQLite3 executable in the project's `./tools/` directory:")
    print(f"   - Create a directory named 'tools' in your project root: {BASE_DIR / 'tools'}")
    print(f"   - Download `sqlite3.exe` (for Windows) or `sqlite3` (for Linux/macOS) into this '{BASE_DIR / 'tools'}' directory.")
    print("   - Ensure the downloaded file is executable.")
    print("-" * 60)
    return False


AZURE_PRIMARY_STORAGE = bool(os.environ.get("AZURE_PRIMARY_STORAGE"))
if AZURE_PRIMARY_STORAGE:
    try:
        # These specific functions from azure_storage might be legacy or for a different Azure service (e.g., Blob)
        # The main restoration logic will now use azure_backup.py which uses Azure File Share.
        # Keeping these for now if they serve other purposes, but they are not part of the primary system restore.
        from azure_storage import (
            download_database as legacy_download_database, # Renamed to avoid confusion
            download_media as legacy_download_media,       # Renamed to avoid confusion
            upload_database as legacy_upload_database,     # Renamed to avoid confusion
            upload_media as legacy_upload_media            # Renamed to avoid confusion
        )
        # If legacy_download_database was intended for initial DB fetch before app starts,
        # it might need to be re-evaluated in context of perform_startup_restore_sequence.
    except Exception as exc:  # pragma: no cover - optional
        print(f"Warning: Legacy Azure storage functions (azure_storage.py) unavailable: {exc}")
        # This doesn't mean azure_backup.py (File Share) is unavailable.
        # AZURE_PRIMARY_STORAGE might need to be redefined or used more carefully.
        # For now, we'll assume it refers to the legacy Blob storage if these specific functions are key.

MIN_PYTHON_VERSION = (3, 7)
# Project root directory
BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR_NAME = "data"
STATIC_DIR_NAME = "static"
FLOOR_MAP_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "floor_map_uploads")
RESOURCE_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "resource_uploads")
DB_PATH = BASE_DIR / DATA_DIR_NAME / 'site.db' # Using pathlib for consistency

# This initial download from azure_storage.py (potentially Blob) is separate from
# the full system restore from Azure File Share handled by perform_startup_restore_sequence.
# If AZURE_PRIMARY_STORAGE implies the main system backup is on Blob, this needs review.
# Assuming perform_startup_restore_sequence is the primary mechanism for full system restore.
# This block might be redundant if perform_startup_restore_sequence handles the initial DB state.
if AZURE_PRIMARY_STORAGE:
    print("Attempting initial database download using legacy azure_storage.py (if configured)...")
    try:
        # Make sure this doesn't conflict with the main restore.
        # This might be for a very basic initial DB if no full backup exists.
        legacy_download_database()
    except NameError: # If legacy_download_database wasn't imported
        print("Legacy database download function not available.")
    except Exception as exc:
        print(f"Failed to download database using legacy azure_storage.py: {exc}")

def check_python_version():
    """Checks if the current Python version meets the minimum requirement."""
    print("Checking Python version...")
    if sys.version_info < MIN_PYTHON_VERSION:
        print(
            f"Error: Your Python version is {sys.version_info.major}.{sys.version_info.minor}."
            f" This project requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher."
        )
        sys.exit(1)
    print(f"Python version {sys.version_info.major}.{sys.version_info.minor} is sufficient.")
    return True

def create_required_directories():
    """Creates the data directory and other necessary static subdirectories if they don't exist."""
    dirs_to_create = [
        BASE_DIR / DATA_DIR_NAME,
        BASE_DIR / STATIC_DIR_NAME,
        BASE_DIR / FLOOR_MAP_UPLOADS_DIR_NAME,
        BASE_DIR / RESOURCE_UPLOADS_DIR_NAME,
        BASE_DIR / "logs" # Assuming logs directory is also desired at root
    ]
    for dir_path in dirs_to_create:
        print(f"Checking for '{dir_path}' directory...")
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"Created '{dir_path}' directory.")
            except OSError as e:
                print(f"Error: Could not create '{dir_path}' directory: {e}")
                if dir_path == BASE_DIR / DATA_DIR_NAME: # Data directory is critical
                    sys.exit(1)
        else:
            print(f"'{dir_path}' directory already exists.")

    if AZURE_PRIMARY_STORAGE:
        print("Downloading media from Azure storage...")
        try:
            download_media() # Assumes this knows target paths like FLOOR_MAP_UPLOADS_DIR_NAME
        except Exception as exc:
            print(f"Failed to download media from Azure: {exc}")
    return True

def ensure_tags_column():
    """Ensure the 'tags' column exists in the resource table."""
    if not DB_PATH.exists():
        print(f"Database file not found at {DB_PATH}, skipping 'tags' column check.")
        return
    try:
        # add_tags_column likely uses Flask-Migrate or direct SQL that needs app context if it uses SQLAlchemy
        # For simplicity, if it's raw SQL on DB_PATH, it's fine.
        # If it uses SQLAlchemy models, it needs an app context.
        # Assuming add_tags_column is self-contained or adapted for this.
        current_app = create_app()
        with current_app.app_context():
            print(f"Ensuring 'tags' column via add_tags_column. DB: {current_app.config['SQLALCHEMY_DATABASE_URI']}")
            add_tags_column() # This function needs to be callable and use the app context if using SQLAlchemy
    except Exception as exc:
        print(f"Failed to ensure 'tags' column exists: {exc}")


def ensure_db_column(table_name, column_name, column_type):
    """Generic function to ensure a column exists in a table."""
    if not DB_PATH.exists():
        print(f"Database file not found at {DB_PATH}, skipping '{column_name}' column check for table '{table_name}'.")
        return

    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        if column_name not in columns:
            print(f"Adding '{column_name}' column to '{table_name}' table...")
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            conn.commit()
            print(f"'{column_name}' column added to '{table_name}'.")
        else:
            print(f"'{column_name}' column already exists in '{table_name}'. No action taken.")
    except Exception as exc:
        print(f"Failed to ensure '{column_name}' column in '{table_name}': {exc}")
    finally:
        if conn:
            conn.close()

def ensure_all_migrations():
    """Runs all schema check/migration functions."""
    # `ensure_tags_column` will create its own app context if it needs one.
    ensure_tags_column() # Needs careful review of its implementation
    ensure_db_column('resource', 'image_filename', 'VARCHAR(255)')
    ensure_db_column('floor_map', 'location', 'VARCHAR(100)')
    ensure_db_column('floor_map', 'floor', 'VARCHAR(50)')
    ensure_db_column('resource', 'scheduled_status', 'VARCHAR(50)')
    ensure_db_column('resource', 'scheduled_status_at', 'DATETIME')


def verify_db_schema():
    """Check if the existing database has the expected tables and columns."""
    if not DB_PATH.exists():
        print(f"Database file {DB_PATH} not found for schema verification.")
        return False

    import sqlite3
    # Expected schema definition remains the same
    expected_schema = {
        'user': {'id', 'username', 'email', 'password_hash', 'is_admin', 'google_id', 'google_email'},
        'role': {'id', 'name', 'description', 'permissions'},
        'user_roles': {'user_id', 'role_id'},
        'floor_map': {'id', 'name', 'image_filename', 'location', 'floor'},
        'resource': {'id', 'name', 'capacity', 'equipment', 'tags', 'booking_restriction', 'status', 'published_at', 'allowed_user_ids', 'image_filename', 'is_under_maintenance', 'maintenance_until', 'max_recurrence_count', 'scheduled_status', 'scheduled_status_at', 'floor_map_id', 'map_coordinates', 'map_allowed_role_ids'},
        'resource_roles': {'resource_id', 'role_id'},
        'booking': {'id', 'resource_id', 'user_name', 'start_time', 'end_time', 'title', 'checked_in_at', 'checked_out_at', 'status', 'recurrence_rule'},
        'waitlist_entry': {'id', 'resource_id', 'user_id', 'timestamp'},
        'audit_log': {'id', 'timestamp', 'user_id', 'username', 'action', 'details'}
    }
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for table, cols in expected_schema.items():
            cursor.execute(f"PRAGMA table_info({table})")
            info = cursor.fetchall()
            if not info:
                print(f"Missing table: {table}")
                return False
            existing = {row[1] for row in info}
            if not cols.issubset(existing):
                missing = cols - existing
                print(f"Table '{table}' missing columns: {', '.join(missing)}")
                return False
        print("Database schema verification successful.")
        return True
    except Exception as exc:
        print(f"Error verifying database schema: {exc}")
        return False
    finally:
        if conn:
            conn.close()

def init_db(force=False):
    current_app = create_app() # Create an app instance for context
    with current_app.app_context():
        current_app.logger.info(f"Database URI used by init_db: {current_app.config.get('SQLALCHEMY_DATABASE_URI')}")
        current_app.logger.info("Starting database initialization...")

        # Run schema migrations/checks before create_all if DB exists, or after if creating new
        # If DB_PATH exists, it implies create_all might not do anything if tables are there.
        # If it doesn't exist, create_all makes them, then we might not need these.
        # For robustness, call ensure_all_migrations. If tables don't exist, they'll error gracefully.
        # This is better handled by proper migration tools like Alembic usually.
        current_app.logger.info("Creating database tables (db.create_all())...")
        db.create_all() # This creates tables based on models if they don't exist.
        current_app.logger.info("Database tables creation/verification step completed.")

        # Now that tables are guaranteed to exist, run migrations/column checks.
        # This is relevant whether the DB file existed before or was just created.
        current_app.logger.info("Ensuring all schema elements (columns) are present after table creation.")
        ensure_all_migrations()

        if not force:
            # Check if any of the core tables have data
            query = "SELECT 1 FROM user LIMIT 1" # Simple query for existence
            try:
                result = db.session.execute(db.text(query)).scalar_one_or_none()
                if result is not None:
                    current_app.logger.warning(
                        "init_db aborted: existing data detected in 'user' table (or other tables). "
                        "Pass force=True to reset database."
                    )
                    return
            except Exception as e: # Table might not exist if it's a completely fresh DB
                current_app.logger.info(f"Could not check for existing data (table might be new): {e}")


        current_app.logger.info("Attempting to delete existing data in corrected order (if force=True or no data check passed)...")
        # Order: AuditLog -> WaitlistEntry -> Booking -> resource_roles_table -> Resource
        # -> FloorMap -> user_roles_table -> User -> Role
        db.session.query(AuditLog).delete()
        db.session.query(WaitlistEntry).delete()
        db.session.query(Booking).delete()
        db.session.execute(resource_roles_table.delete())
        db.session.query(Resource).delete()
        db.session.query(FloorMap).delete()
        db.session.execute(user_roles_table.delete())
        db.session.query(User).delete()
        db.session.query(Role).delete()

        try:
            db.session.commit()
            current_app.logger.info("Successfully committed deletions of existing data.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error committing deletions during DB initialization:")
            raise # Re-raise after logging if this is critical

        current_app.logger.info("Creating default roles and users...")
        try:
            # Default Admin User from config or hardcoded fallback
            default_admin_username = current_app.config.get('DEFAULT_ADMIN_USERNAME', 'admin')
            default_admin_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
            # Changed default admin password
            default_admin_password = 'admin'

            # Role Handling
            admin_role = Role.query.filter_by(name="Administrator").first()
            if not admin_role:
                admin_role = Role(name="Administrator", description="Full system access", permissions="all_permissions,view_analytics,manage_bookings,manage_system,manage_users,manage_resources,manage_floor_maps")
                db.session.add(admin_role)
                current_app.logger.info("Administrator role created.")
            else:
                current_app.logger.info("Administrator role already exists.")

            standard_role = Role.query.filter_by(name="StandardUser").first()
            if not standard_role:
                standard_role = Role(name="StandardUser", description="Can make bookings and view resources", permissions="make_bookings,view_resources")
                db.session.add(standard_role)
                current_app.logger.info("StandardUser role created.")
            else:
                current_app.logger.info("StandardUser role already exists.")

            # Commit roles if new ones were added to ensure they have IDs before user association
            # This commit is fine here, or could be part of the larger commit at the end.
            # For clarity, let's commit them if they were added.
            if not Role.query.filter_by(name="Administrator").first() or not Role.query.filter_by(name="StandardUser").first():
                 db.session.commit() # Commit if any role was newly added.

            # Admin User Handling
            admin_user = User.query.filter_by(username=default_admin_username).first()
            if not admin_user:
                admin_user = User(username=default_admin_username, email=default_admin_email, is_admin=True)
                admin_user.set_password(default_admin_password) # Use new password
                admin_user.roles.append(admin_role)
                db.session.add(admin_user)
                current_app.logger.info(f"Default admin user '{default_admin_username}' created.")
                current_app.logger.warning(
                    f"IMPORTANT SECURITY WARNING: A default admin user ('{default_admin_username}') with password '{default_admin_password}' "
                    f"has been created. This password MUST be changed immediately in a production environment."
                )
            else:
                current_app.logger.info(f"Default admin user '{default_admin_username}' already exists. Skipping creation.")

            # Standard User Handling
            standard_user = User.query.filter_by(username="user").first()
            if not standard_user:
                standard_user = User(username="user", email="user@example.com", is_admin=False)
                standard_user.set_password("user") # Use new password
                standard_user.roles.append(standard_role)
                db.session.add(standard_user)
                current_app.logger.info("Default standard user 'user' created.")
            else:
                current_app.logger.info("Default standard user 'user' already exists. Skipping creation.")

            db.session.commit() # Commit all new users and role associations
            current_app.logger.info("Default roles and users creation/verification process completed.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error creating default roles or users:")
            raise

        # Sample Resources and Bookings
        admin_user_for_perms = User.query.filter_by(username=default_admin_username).first()
        standard_user_for_perms = User.query.filter_by(username='user').first()
        admin_user_id_str = str(admin_user_for_perms.id) if admin_user_for_perms else "1" # Fallback if not found
        standard_user_id_str = str(standard_user_for_perms.id) if standard_user_for_perms else "2"

        admin_role_for_resource = Role.query.filter_by(name="Administrator").first()
        standard_role_for_resource = Role.query.filter_by(name="StandardUser").first()

        current_app.logger.info("Adding sample resources...")
        try:
            res_list = [
                Resource(name="Conference Room Alpha", capacity=10, equipment="Projector,Whiteboard", tags="large,video", status='published', published_at=datetime.utcnow(), roles=[standard_role_for_resource, admin_role_for_resource] if standard_role_for_resource and admin_role_for_resource else []),
                Resource(name="Meeting Room Beta", capacity=6, equipment="Teleconference", tags="medium", status='published', published_at=datetime.utcnow(), allowed_user_ids=f"{standard_user_id_str},{admin_user_id_str}"),
                Resource(name="Focus Room Gamma", capacity=2, equipment="Whiteboard", tags="quiet,small", status='draft', roles=[admin_role_for_resource] if admin_role_for_resource else []),
                Resource(name="Archived Room Omega", capacity=5, status='archived', published_at=datetime.utcnow() - timedelta(days=30))
            ]
            db.session.add_all(res_list)
            db.session.commit()
            current_app.logger.info(f"Successfully added {len(res_list)} sample resources.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error adding sample resources:")

        resource_alpha = Resource.query.filter_by(name="Conference Room Alpha").first()
        if resource_alpha:
            current_app.logger.info("Adding sample bookings...")
            try:
                bookings_list = [
                    Booking(resource_id=resource_alpha.id, user_name="user", title="Team Sync Alpha", start_time=datetime.combine(date.today(), time(9,0)), end_time=datetime.combine(date.today(), time(10,0))),
                    Booking(resource_id=resource_alpha.id, user_name="admin", title="Client Meeting Alpha", start_time=datetime.combine(date.today(), time(11,0)), end_time=datetime.combine(date.today(), time(12,30))),
                ]
                db.session.add_all(bookings_list)
                db.session.commit()
                current_app.logger.info(f"Successfully added {len(bookings_list)} sample bookings.")
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception("Error adding sample bookings:")
        else:
            current_app.logger.warning("Conference Room Alpha not found, skipping sample bookings for it.")

        current_app.logger.info("Ensuring default backup schedule JSON file exists...")
        data_dir_for_json = BASE_DIR / DATA_DIR_NAME
        schedule_config_file_path = data_dir_for_json / 'backup_schedule.json'
        default_schedule_data = current_app.config.get('DEFAULT_SCHEDULE_DATA', {"is_enabled": False, "schedule_type": "daily", "time_of_day": "02:00"})

        if not schedule_config_file_path.exists():
            try:
                data_dir_for_json.mkdir(parents=True, exist_ok=True)
                with open(schedule_config_file_path, 'w', encoding='utf-8') as f:
                    json.dump(default_schedule_data, f, indent=4)
                current_app.logger.info(f"Created default backup schedule file: {schedule_config_file_path}")
            except IOError as e:
                current_app.logger.error(f"Error creating default backup schedule JSON file '{schedule_config_file_path}': {e}")
        else:
            current_app.logger.info(f"Backup schedule JSON file already exists: {schedule_config_file_path}")

        current_app.logger.info("Database initialization script completed within app context.")

        if AZURE_PRIMARY_STORAGE:
            print("Uploading database and media to Azure storage...")
            try:
                upload_database(versioned=False) # Assumes knows DB_PATH
                upload_media() # Assumes knows media paths
            except Exception as exc:
                print(f"Failed to upload data to Azure: {exc}")

def main(force_init=False):
    """Main function to run setup checks and tasks."""
    print("Starting project initialization...")
    
    check_python_version()
    print("-" * 30)
    create_required_directories() # This might also download initial media via legacy_download_media
    print("-" * 30)

    # Handle Azure restoration if requested
    restore_from_azure_flag = '--restore-from-azure' in sys.argv
    enable_auto_restore_env = os.environ.get("ENABLE_AUTO_STARTUP_RESTORE", "false").lower() == "true"

    if restore_from_azure_flag or enable_auto_restore_env:
        print("Azure restoration requested via command line or environment variable.")
        # Create app instance for restore context WITHOUT starting the scheduler
        app_for_restore = create_app(start_scheduler=False)
        with app_for_restore.app_context():
            app_for_restore.logger.info("Attempting to restore from Azure Backup (scheduler will not be started for this app instance)...")
            try:
                restore_result = perform_startup_restore_sequence(app_for_restore)
                app_for_restore.logger.info(f"Azure restore sequence completed with status: {restore_result.get('status')}, message: {restore_result.get('message')}")
                if restore_result.get('status') == 'failure':
                    app_for_restore.logger.error("Azure restoration failed. Check logs for details. Database might be in an inconsistent state.")
                    # Depending on desired behavior, might exit or continue with standard init
            except Exception as e_restore:
                app_for_restore.logger.error(f"Critical error during Azure restoration process: {e_restore}", exc_info=True)
                print(f"ERROR: Azure restoration process failed critically: {e_restore}")
                # Decide if to exit or continue. For now, let it continue to DB init logic below.
        print("-" * 30)

    # Database initialization logic (runs after potential Azure restore)
    if force_init:
        print(f"Force initializing database at {DB_PATH}...")
        init_db(force=True) # init_db creates its own app context
        print("Database force initialization process completed.")
    elif DB_PATH.exists():
        print(f"Existing database found at {DB_PATH}. Verifying structure...")
        # verify_db_schema does not use Flask app context by default, uses direct sqlite3
        if verify_db_schema():
            print("Database structure looks correct. No re-initialization needed unless --force was used.")
            print("If you need to re-initialize from scratch (ignoring any restored data), run: python init_setup.py --force")
        else:
            print("Database structure invalid or outdated. This might be expected if a restore just happened and schema changed.")
            print("Attempting to let init_db() handle schema updates or creation if necessary.")
            # init_db(force=False) will try to create tables if they don't exist and run migrations.
            # If a restore just happened, the DB exists, so it won't wipe data unless --force is used.
            # It will still run ensure_all_migrations which might add missing columns.
            init_db(force=False)
            print("Database check/update process completed after structure verification.")

    else: # No DB_PATH exists
        print(f"No database found at {DB_PATH}. Initializing database...")
        init_db(force=False) # force=False should still init if no DB exists
        print("Database initialization process completed.")

    print("-" * 30)
    print("Project initialization script completed successfully.")

if __name__ == "__main__":
    force_flag = '--force' in sys.argv
    # The main function now internally checks for --restore-from-azure
    if not check_sqlite_cli_availability(): # Call the new check function
        # Warning is printed by the function itself if not found
        pass # Decide if script should exit or just warn if not found. For now, it just warns.
    main(force_init=force_flag)


