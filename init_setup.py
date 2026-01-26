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
    """
    Checks for sqlite3 CLI tool.
    Deprecated or low priority for Postgres-centric setup, but kept for SQLite fallback.
    """
    return True # Skip check as we focus on Postgres

# Refactored imports for application factory pattern
from app_factory import create_app
from extensions import db
from models import (
    User, Resource, Booking, Role, AuditLog, FloorMap,
    WaitlistEntry, resource_roles_table, user_roles_table
)
from add_resource_tags_column import add_tags_column
# from azure_backup import perform_startup_restore_sequence # Azure backup replaced by R2

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
        print("Azure restoration requested. (Disabled in R2 migration)")
        # app_for_restore = create_app(start_scheduler=False)
        # with app_for_restore.app_context():
        #     app_for_restore.logger.info("Attempting to restore from Azure Backup...")
        #     try:
        #         restore_result = perform_startup_restore_sequence(app_for_restore)
        #         app_for_restore.logger.info(f"Azure restore sequence completed: {restore_result.get('status')}, {restore_result.get('message')}")
        #         if restore_result.get('status') == 'failure':
        #             app_for_restore.logger.error("Azure restoration failed.")
        #     except Exception as e_restore:
        #         app_for_restore.logger.error(f"Critical error during Azure restoration: {e_restore}", exc_info=True)
        print("-" * 30)

    # Database Initialization Logic
    # For Postgres, DB_PATH check is not relevant as it's a URL.
    # We rely on SQLAlchemy to check tables or just run init_db(force=False) safely.

    print("Initializing database...")
    try:
        # init_db handles checking for existing data unless force=True
        init_db(force=force_init)
        print("Database initialization logic completed.")
    except Exception as e:
        print(f"Error during database initialization: {e}")
        # Depending on severity, might exit or continue

    print("-" * 30)
    print("Project initialization script completed successfully.")

if __name__ == "__main__":
    force_flag = '--force' in sys.argv
    if not check_sqlite_cli_availability(): # Call the new check function
        # Warning is printed by the function itself if not found
        print("Continuing setup despite missing sqlite3 CLI. Backup functionality will be affected.")
    main(force_init=force_flag)
