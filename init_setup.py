#!/usr/bin/env python3

import sys
import os
import pathlib
import json
import subprocess # For checking sqlite3 CLI availability
from werkzeug.security import generate_password_hash
from datetime import datetime, date, timedelta, time

# Define BASE_DIR early as it's used by check_sqlite_cli_availability and others
BASE_DIR = pathlib.Path(__file__).resolve().parent

# --- FUNCTION DEFINITIONS START ---

def check_sqlite_cli_availability():
    """Checks for sqlite3 CLI tool and prints guidance if not found."""
    sqlite_exe_name = "sqlite3.exe" if sys.platform == "win32" else "sqlite3"
    tools_dir = os.path.join(BASE_DIR, "tools")
    local_sqlite_path = os.path.join(tools_dir, sqlite_exe_name)

    if os.path.exists(local_sqlite_path) and os.access(local_sqlite_path, os.X_OK):
        print(f"INFO: Found local sqlite3 CLI at: {local_sqlite_path}")
        return True
    try:
        # Use the platform-specific executable name directly in the list
        process = subprocess.run([sqlite_exe_name, "-version"],
                                 capture_output=True, text=True, check=False, timeout=5)
        if process.returncode == 0 and "SQLite version" in process.stdout:
            print(f"INFO: Found sqlite3 CLI in system PATH. Version: {process.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        print(f"WARNING: Checking for sqlite3 in PATH timed out.")
    except Exception as e:
        print(f"WARNING: Error when checking for sqlite3 in PATH: {e}")

    # Attempt to download from Azure if not found locally or in PATH
    print(f"INFO: sqlite3 CLI not found locally or in PATH. Attempting to download from Azure...")
    try:
        from azure.storage.fileshare import ShareServiceClient, ShareFileClient
        from azure.core.exceptions import ResourceNotFoundError
    except ImportError:
        print("WARNING: Azure SDK not installed (azure-storage-fileshare). Cannot download sqlite3 from Azure.")
        # Fall through to standard guidance messages
        print_sqlite_guidance(tools_dir)
        return False

    connection_string = os.environ.get("AZURE_TOOLS_CONNECTION_STRING")
    tools_share_name = os.environ.get("AZURE_TOOLS_SHARE_NAME")

    # Determine the correct remote filename based on platform
    # SQLITE3_REMOTE_FILENAME_WINDOWS, SQLITE3_REMOTE_FILENAME_LINUX, SQLITE3_REMOTE_FILENAME_MACOS
    if sys.platform == "win32":
        sqlite3_remote_filename = os.environ.get("SQLITE3_REMOTE_FILENAME_WINDOWS", "sqlite3.exe")
    elif sys.platform == "linux":
        sqlite3_remote_filename = os.environ.get("SQLITE3_REMOTE_FILENAME_LINUX", "sqlite3_linux")
    elif sys.platform == "darwin": # macOS
        sqlite3_remote_filename = os.environ.get("SQLITE3_REMOTE_FILENAME_MACOS", "sqlite3_macos")
    else:
        print(f"WARNING: Unsupported platform '{sys.platform}' for automatic sqlite3 download.")
        print_sqlite_guidance(tools_dir)
        return False

    if not all([connection_string, tools_share_name, sqlite3_remote_filename]):
        print("WARNING: Azure connection details for tools (AZURE_TOOLS_CONNECTION_STRING, AZURE_TOOLS_SHARE_NAME, or platform-specific SQLITE3_REMOTE_FILENAME_*) not fully configured. Cannot download sqlite3.")
        print_sqlite_guidance(tools_dir)
        return False

    try:
        service_client = ShareServiceClient.from_connection_string(connection_string)
        share_client = service_client.get_share_client(tools_share_name)
        # Assuming sqlite3 is in the root of the tools share, or a 'sqlite' subdirectory.
        # For simplicity, let's assume root for now. Adjust 'sqlite3_remote_path' if it's in a subdir.
        # Example: sqlite3_remote_path = f"sqlite/{sqlite3_remote_filename}"
        sqlite3_remote_path = sqlite3_remote_filename

        file_client = share_client.get_file_client(sqlite3_remote_path)

        if not os.path.exists(tools_dir):
            os.makedirs(tools_dir)
            print(f"INFO: Created tools directory: {tools_dir}")

        print(f"INFO: Downloading '{sqlite3_remote_path}' from Azure share '{tools_share_name}' to '{local_sqlite_path}'...")
        with open(local_sqlite_path, "wb") as file_handle:
            download_stream = file_client.download_file()
            file_handle.write(download_stream.readall())

        print(f"INFO: Downloaded sqlite3 to {local_sqlite_path}.")

        if sys.platform != "win32":
            print(f"INFO: Setting execute permission for {local_sqlite_path}...")
            os.chmod(local_sqlite_path, 0o755) # rwxr-xr-x

        # Verify again after download
        if os.path.exists(local_sqlite_path) and os.access(local_sqlite_path, os.X_OK):
            print(f"INFO: Successfully downloaded and configured local sqlite3 CLI at: {local_sqlite_path}")
            return True
        else:
            print(f"ERROR: sqlite3 downloaded to {local_sqlite_path} but it's not found or not executable.")
            print_sqlite_guidance(tools_dir)
            return False

    except ResourceNotFoundError:
        print(f"ERROR: sqlite3 executable '{sqlite3_remote_path}' not found in Azure share '{tools_share_name}'.")
        print_sqlite_guidance(tools_dir)
        return False
    except ImportError: # Should have been caught earlier, but good for safety
        print("ERROR: Azure SDK (azure-storage-fileshare) import failed during download attempt.")
        print_sqlite_guidance(tools_dir)
        return False
    except Exception as e:
        print(f"ERROR: Failed to download or configure sqlite3 from Azure: {e}")
        print_sqlite_guidance(tools_dir)
        return False

    # Fallback if all methods (local, PATH, Azure download) fail
    print_sqlite_guidance(tools_dir)
    return False

def print_sqlite_guidance(tools_dir_path):
    """Helper function to print manual installation guidance for sqlite3."""
    print("-" * 60)
    print("IMPORTANT: `sqlite3` Command-Line Tool Not Found or Not Executable.")
    print("-" * 60)
    print("The database backup functionality requires the SQLite3 command-line tool.")
    print("\nPlease ensure it's available by one of these methods:")
    print("\n1. Install SQLite3 and add it to your system's PATH:")
    print("   - Download from: https://www.sqlite.org/download.html")
    print("   - Ensure the directory containing `sqlite3` (or `sqlite3.exe`) is in your PATH environment variable.")
    print(f"\n2. Place the SQLite3 executable in the project's `./tools/` directory ({tools_dir_path}):")
    print(f"   - If the 'tools' directory doesn't exist, create it: {tools_dir_path}")
    print(f"   - Download `sqlite3.exe` (for Windows) or `sqlite3` (for Linux/macOS) into this directory.")
    print("   - Ensure the downloaded file is executable (e.g., `chmod +x ./tools/sqlite3` on Linux/macOS).")
    print("-" * 60)

# Refactored imports for application factory pattern
from app_factory import create_app
from extensions import db
from models import (
    User, Resource, Booking, Role, AuditLog, FloorMap,
    WaitlistEntry, resource_roles_table, user_roles_table
)
from add_resource_tags_column import add_tags_column
from azure_backup import perform_startup_restore_sequence

AZURE_PRIMARY_STORAGE = bool(os.environ.get("AZURE_PRIMARY_STORAGE"))
if AZURE_PRIMARY_STORAGE:
    try:
        from azure_storage import (
            download_database as legacy_download_database,
            download_media as legacy_download_media,
            upload_database as legacy_upload_database,
            upload_media as legacy_upload_media
        )
    except Exception as exc:
        print(f"Warning: Legacy Azure storage functions (azure_storage.py) unavailable: {exc}")

MIN_PYTHON_VERSION = (3, 7)
DATA_DIR_NAME = "data"
STATIC_DIR_NAME = "static"
FLOOR_MAP_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "floor_map_uploads")
RESOURCE_UPLOADS_DIR_NAME = os.path.join(STATIC_DIR_NAME, "resource_uploads")
DB_PATH = BASE_DIR / DATA_DIR_NAME / 'site.db'

if AZURE_PRIMARY_STORAGE:
    print("Attempting initial database download using legacy azure_storage.py (if configured)...")
    try:
        if 'legacy_download_database' in globals():
            legacy_download_database()
        else:
            print("Legacy database download function not available (definition missing).")
    except NameError:
        print("Legacy database download function not available (NameError).")
    except Exception as exc:
        print(f"Failed to download database using legacy azure_storage.py: {exc}")

def check_python_version():
    print("Checking Python version...")
    if sys.version_info < MIN_PYTHON_VERSION:
        sys.exit(f"Error: Your Python version is {sys.version_info.major}.{sys.version_info.minor}. This project requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher.")
    print(f"Python version {sys.version_info.major}.{sys.version_info.minor} is sufficient.")
    return True

def create_required_directories():
    dirs_to_create = [
        BASE_DIR / DATA_DIR_NAME, BASE_DIR / STATIC_DIR_NAME,
        BASE_DIR / FLOOR_MAP_UPLOADS_DIR_NAME, BASE_DIR / RESOURCE_UPLOADS_DIR_NAME,
        BASE_DIR / "logs"
    ]
    tools_dir_path = BASE_DIR / "tools"
    if not tools_dir_path.exists():
        try:
            tools_dir_path.mkdir(parents=True, exist_ok=True)
            print(f"Created directory: {tools_dir_path} (recommended for local sqlite3 executable)")
        except OSError as e:
            print(f"Warning: Could not create 'tools' directory: {e}")
    for dir_path in dirs_to_create:
        print(f"Checking for '{dir_path}' directory...")
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"Created '{dir_path}' directory.")
            except OSError as e:
                print(f"Error: Could not create '{dir_path}' directory: {e}")
                if dir_path == BASE_DIR / DATA_DIR_NAME: sys.exit(1)
        else:
            print(f"'{dir_path}' directory already exists.")
    if AZURE_PRIMARY_STORAGE:
        print("Downloading media from Azure storage...")
        try:
            if 'legacy_download_media' in globals(): legacy_download_media()
            else: print("Legacy media download function not available.")
        except Exception as exc: print(f"Failed to download media from Azure: {exc}")
    return True

def ensure_tags_column():
    if not DB_PATH.exists(): return
    try:
        current_app = create_app()
        with current_app.app_context():
            add_tags_column()
    except Exception as exc: print(f"Failed to ensure 'tags' column exists: {exc}")

def ensure_db_column(table_name, column_name, column_type):
    if not DB_PATH.exists(): return
    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        columns = [info[1] for info in conn.execute(f"PRAGMA table_info({table_name})")]
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            conn.commit()
    except Exception as exc: print(f"Failed to ensure '{column_name}' in '{table_name}': {exc}")
    finally:
        if conn: conn.close()

def ensure_all_migrations():
    ensure_tags_column()
    ensure_db_column('resource', 'image_filename', 'VARCHAR(255)')
    ensure_db_column('floor_map', 'location', 'VARCHAR(100)')
    # ... (other ensure_db_column calls)
    ensure_db_column('floor_map', 'floor', 'VARCHAR(50)')
    ensure_db_column('resource', 'scheduled_status', 'VARCHAR(50)')
    ensure_db_column('resource', 'scheduled_status_at', 'DATETIME')

def verify_db_schema():
    if not DB_PATH.exists(): return False
    import sqlite3
    # ... (schema definition and verification logic as before) ...
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
                print(f"Missing table: {table}"); return False
            existing = {row[1] for row in info}
            if not cols.issubset(existing):
                print(f"Table '{table}' missing columns: {cols - existing}"); return False
        print("Database schema verification successful.")
        return True
    except Exception as exc:
        print(f"Error verifying database schema: {exc}"); return False
    finally:
        if conn: conn.close()


def init_db(force=False):
    # ... (init_db logic as before, ensuring it calls create_app within its own scope or has app passed) ...
    current_app = create_app()
    with current_app.app_context():
        # ... (rest of init_db)
        current_app.logger.info(f"Database URI used by init_db: {current_app.config.get('SQLALCHEMY_DATABASE_URI')}")
        current_app.logger.info("Starting database initialization...")
        current_app.logger.info("Creating database tables (db.create_all())...")
        db.create_all()
        current_app.logger.info("Database tables creation/verification step completed.")
        current_app.logger.info("Ensuring all schema elements (columns) are present after table creation.")
        ensure_all_migrations()

        if not force:
            query = "SELECT 1 FROM user LIMIT 1"
            try:
                result = db.session.execute(db.text(query)).scalar_one_or_none()
                if result is not None:
                    current_app.logger.warning("init_db aborted: existing data detected. Pass force=True to reset.")
                    return
            except Exception as e:
                current_app.logger.info(f"Could not check for existing data: {e}")

        current_app.logger.info("Attempting to delete existing data...")
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
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error committing deletions:")
            raise

        current_app.logger.info("Creating default roles and users...")
        try:
            admin_role = Role(name="Administrator", description="Full system access", permissions="all_permissions,view_analytics,manage_bookings,manage_system,manage_users,manage_resources,manage_floor_maps,manage_maintenance")
            standard_role = Role(name="StandardUser", description="Can make bookings and view resources", permissions="make_bookings,view_resources")
            db.session.add_all([admin_role, standard_role])
            db.session.commit() # Commit roles to get IDs

            admin_user = User(username='admin', email='admin@example.com', is_admin=True)
            admin_user.set_password('admin')
            admin_user.roles.append(admin_role)
            db.session.add(admin_user)
            current_app.logger.info(f"Default admin user 'admin' created.")
            current_app.logger.warning("IMPORTANT: Default admin password is 'admin'. Change immediately.")

            standard_user = User(username="user", email="user@example.com", is_admin=False)
            standard_user.set_password("user")
            standard_user.roles.append(standard_role)
            db.session.add(standard_user)
            current_app.logger.info("Default standard user 'user' created.")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error creating default roles/users:")
            raise

        # ... (Sample data creation as before) ...
        admin_user_for_perms = User.query.filter_by(username='admin').first()
        standard_user_for_perms = User.query.filter_by(username='user').first()
        admin_user_id_str = str(admin_user_for_perms.id) if admin_user_for_perms else "1"
        standard_user_id_str = str(standard_user_for_perms.id) if standard_user_for_perms else "2"
        admin_role_for_resource = Role.query.filter_by(name="Administrator").first()
        standard_role_for_resource = Role.query.filter_by(name="StandardUser").first()
        try:
            res_list = [
                Resource(name="Conference Room Alpha", capacity=10, equipment="Projector,Whiteboard", tags="large,video", status='published', published_at=datetime.utcnow(), roles=[standard_role_for_resource, admin_role_for_resource] if standard_role_for_resource and admin_role_for_resource else []),
                Resource(name="Meeting Room Beta", capacity=6, equipment="Teleconference", tags="medium", status='published', published_at=datetime.utcnow(), allowed_user_ids=f"{standard_user_id_str},{admin_user_id_str}"),
            ]
            db.session.add_all(res_list)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error adding sample resources:")

        # ... (Backup schedule file creation as before) ...
        data_dir_for_json = BASE_DIR / DATA_DIR_NAME
        schedule_config_file_path = data_dir_for_json / 'backup_schedule.json'
        default_schedule_data = current_app.config.get('DEFAULT_SCHEDULE_DATA', {"is_enabled": False, "schedule_type": "daily", "time_of_day": "02:00"})
        if not schedule_config_file_path.exists():
            try:
                data_dir_for_json.mkdir(parents=True, exist_ok=True)
                with open(schedule_config_file_path, 'w', encoding='utf-8') as f:
                    json.dump(default_schedule_data, f, indent=4)
            except IOError as e:
                current_app.logger.error(f"Error creating default backup schedule JSON: {e}")

        current_app.logger.info("Database initialization script completed.")

        if AZURE_PRIMARY_STORAGE:
            print("Uploading database and media to Azure storage...")
            try:
                if 'legacy_upload_database' in globals(): legacy_upload_database(versioned=False)
                else: print("Legacy database upload function not available.")
                if 'legacy_upload_media' in globals(): legacy_upload_media()
                else: print("Legacy media upload function not available.")
            except Exception as exc: print(f"Failed to upload data to Azure: {exc}")


def main(force_init=False):
    """Main function to run setup checks and tasks."""
    print("Starting project initialization...")
    
    check_python_version()
    print("-" * 30)
    create_required_directories()
    print("-" * 30)

    restore_from_azure_flag = '--restore-from-azure' in sys.argv
    enable_auto_restore_env = os.environ.get("ENABLE_AUTO_STARTUP_RESTORE", "false").lower() == "true"

    if restore_from_azure_flag or enable_auto_restore_env:
        print("Azure restoration requested.")
        app_for_restore = create_app(start_scheduler=False)
        with app_for_restore.app_context():
            app_for_restore.logger.info("Attempting to restore from Azure Backup...")
            try:
                restore_result = perform_startup_restore_sequence(app_for_restore)
                app_for_restore.logger.info(f"Azure restore sequence completed: {restore_result.get('status')}, {restore_result.get('message')}")
                if restore_result.get('status') == 'failure':
                    app_for_restore.logger.error("Azure restoration failed.")
            except Exception as e_restore:
                app_for_restore.logger.error(f"Critical error during Azure restoration: {e_restore}", exc_info=True)
        print("-" * 30)

    if force_init:
        print(f"Force initializing database at {DB_PATH}...")
        init_db(force=True)
        print("Database force initialization completed.")
    elif DB_PATH.exists():
        print(f"Existing database found at {DB_PATH}. Verifying structure...")
        if verify_db_schema():
            print("Database structure correct. No re-initialization needed unless --force used.")
        else:
            print("Database structure invalid/outdated. Attempting init_db() to update/create.")
            init_db(force=False)
            print("Database check/update process completed.")
    else:
        print(f"No database found at {DB_PATH}. Initializing database...")
        init_db(force=False)
        print("Database initialization completed.")

    print("-" * 30)
    print("Project initialization script completed successfully.")

if __name__ == "__main__":
    force_flag = '--force' in sys.argv
    if not check_sqlite_cli_availability(): # Call the new check function
        # Warning is printed by the function itself if not found
        print("Continuing setup despite missing sqlite3 CLI. Backup functionality will be affected.")
    main(force_init=force_flag)
